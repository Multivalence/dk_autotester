"""The test-output convention and its parser.

A compliant harness writes, on stdout, framing markers around one JSON object per
test result:

    ##DKTEST_BEGIN## <repo_name>
    ##DKTEST## {"name": "...", "description": "...", "status": "pass|fail|partial",
                "points_earned": 8, "full_points": 10, ...}
    ##DKTEST_END## <repo_name> <harness_exit_code>

Status is derived from points:
  - "pass" if points_earned == full_points (100%)
  - "fail" if points_earned == 0 (0%)
  - "partial" if 0 < points_earned < full_points (1-99%)

Any deviation (malformed JSON, bad status, unmatched markers, a repo that emits
zero results) raises ProtocolError so the orchestrator can terminate the run, as
required by the spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

BEGIN = "##DKTEST_BEGIN##"
END = "##DKTEST_END##"
RESULT = "##DKTEST##"

VALID_STATUSES = {"pass", "fail", "partial"}


class ProtocolError(Exception):
    """Raised when harness output violates the test-output convention."""


@dataclass
class TestResult:
    repo: str
    name: str
    description: str
    status: str
    points_earned: float = 0.0
    full_points: float = 0.0
    message: str = ""
    duration_ms: int = 0

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    @property
    def partial(self) -> bool:
        return self.status == "partial"

    @property
    def failed(self) -> bool:
        return self.status == "fail"


def _derive_status(points_earned: float, full_points: float) -> str:
    """Derive status from points: pass (100%), fail (0%), partial (1-99%)."""
    if full_points <= 0:
        # If no points assigned, treat as pass (backward compat for legacy harnesses)
        return "pass"
    if points_earned >= full_points:
        return "pass"
    if points_earned <= 0:
        return "fail"
    return "partial"


def _parse_result_line(line: str, repo: str) -> TestResult:
    payload = line[len(RESULT):].strip()
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"[{repo}] result line is not valid JSON: {payload!r} ({exc})")
    if not isinstance(obj, dict):
        raise ProtocolError(f"[{repo}] result must be a JSON object, got: {payload!r}")

    for key in ("name", "description"):
        if key not in obj or obj[key] in (None, ""):
            raise ProtocolError(f"[{repo}] result missing required field '{key}': {payload!r}")

    # Parse points (new fields, with backward compatibility)
    try:
        full_points = float(obj.get("full_points", 0))
    except (TypeError, ValueError):
        raise ProtocolError(f"[{repo}] full_points must be a number, got {obj.get('full_points')!r}")

    try:
        points_earned = float(obj.get("points_earned", 0))
    except (TypeError, ValueError):
        raise ProtocolError(f"[{repo}] points_earned must be a number, got {obj.get('points_earned')!r}")

    # Determine status: if explicitly provided use it, otherwise derive from points
    if "status" in obj and obj["status"]:
        status = str(obj["status"]).lower()
        if status not in VALID_STATUSES:
            raise ProtocolError(
                f"[{repo}] invalid status '{status}'; expected one of {sorted(VALID_STATUSES)}"
            )
        # If status provided but no points, infer points from status for backward compat
        if full_points == 0:
            if status == "pass":
                full_points = 1.0
                points_earned = 1.0
            elif status == "fail":
                full_points = 1.0
                points_earned = 0.0
            # partial without points is invalid
            elif status == "partial":
                raise ProtocolError(
                    f"[{repo}] status 'partial' requires points_earned and full_points"
                )
    else:
        # Derive status from points
        if full_points == 0:
            raise ProtocolError(
                f"[{repo}] result must have either 'status' or 'full_points' field: {payload!r}"
            )
        status = _derive_status(points_earned, full_points)

    duration = obj.get("duration_ms", 0)
    try:
        duration_ms = int(duration)
    except (TypeError, ValueError):
        raise ProtocolError(f"[{repo}] duration_ms must be an integer, got {duration!r}")

    return TestResult(
        repo=repo,
        name=str(obj["name"]),
        description=str(obj["description"]),
        status=status,
        points_earned=points_earned,
        full_points=full_points,
        message=str(obj.get("message", "")),
        duration_ms=duration_ms,
    )


def parse_stream(text: str, expected_repos: list[str]) -> list[TestResult]:
    """Parse a batch container's stdout into results, validating the convention.

    `expected_repos` is the list of repos that the container was asked to run; each
    one must appear with a BEGIN/END pair and at least one result line.
    """
    results: list[TestResult] = []
    current_repo: str | None = None
    seen_in_current = 0
    closed_repos: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(BEGIN):
            if current_repo is not None:
                raise ProtocolError(
                    f"nested {BEGIN} for '{line}' while '{current_repo}' still open"
                )
            current_repo = line[len(BEGIN):].strip()
            if not current_repo:
                raise ProtocolError(f"{BEGIN} marker without a repo name")
            seen_in_current = 0
        elif line.startswith(END):
            if current_repo is None:
                raise ProtocolError(f"{END} marker without a matching {BEGIN}: {line!r}")
            parts = line[len(END):].split()
            ended_repo = parts[0] if parts else ""
            if ended_repo != current_repo:
                raise ProtocolError(
                    f"{END} for '{ended_repo}' does not match open repo '{current_repo}'"
                )
            if seen_in_current == 0:
                raise ProtocolError(f"[{current_repo}] produced zero test results")
            closed_repos.add(current_repo)
            current_repo = None
        elif line.startswith(RESULT):
            if current_repo is None:
                raise ProtocolError(f"{RESULT} line outside of a {BEGIN}/{END} block: {line!r}")
            results.append(_parse_result_line(line, current_repo))
            seen_in_current += 1
        # Non-marker lines (build logs, npm output, etc.) are ignored.

    if current_repo is not None:
        raise ProtocolError(f"[{current_repo}] missing closing {END} marker")

    missing = [r for r in expected_repos if r not in closed_repos]
    if missing:
        raise ProtocolError(
            f"no results emitted for repos: {missing} (output convention not followed)"
        )

    return results
