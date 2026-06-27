"""Aggregate parsed results into a JSON report and a human-readable summary."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .config import Config, RepoSpec
from .protocol import TestResult


@dataclass
class Report:
    results: list[TestResult]
    config: Config

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def partial(self) -> int:
        return sum(1 for r in self.results if r.partial)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.failed)

    @property
    def total_points_earned(self) -> float:
        return sum(r.points_earned for r in self.results)

    @property
    def total_full_points(self) -> float:
        return sum(r.full_points for r in self.results)

    def to_dict(self) -> dict:
        by_repo: dict[str, list[TestResult]] = {}
        for r in self.results:
            by_repo.setdefault(r.repo, []).append(r)

        descriptions = {repo.name: repo.description for repo in self.config.repos}

        return {
            "summary": {
                "repos": len(by_repo),
                "tests": self.total,
                "passed": self.passed,
                "partial": self.partial,
                "failed": self.failed,
                "points_earned": self.total_points_earned,
                "full_points": self.total_full_points,
            },
            "repos": [
                {
                    "name": repo_name,
                    "description": descriptions.get(repo_name, ""),
                    "passed": sum(1 for r in tests if r.passed),
                    "partial": sum(1 for r in tests if r.partial),
                    "failed": sum(1 for r in tests if r.failed),
                    "points_earned": sum(r.points_earned for r in tests),
                    "full_points": sum(r.full_points for r in tests),
                    "tests": [
                        {
                            "name": r.name,
                            "description": r.description,
                            "status": r.status,
                            "points_earned": r.points_earned,
                            "full_points": r.full_points,
                            "message": r.message,
                            "duration_ms": r.duration_ms,
                        }
                        for r in tests
                    ],
                }
                for repo_name, tests in by_repo.items()
            ],
        }

    def write_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
            fh.write("\n")

    def render_text(self) -> str:
        lines: list[str] = []
        by_repo: dict[str, list[TestResult]] = {}
        for r in self.results:
            by_repo.setdefault(r.repo, []).append(r)

        descriptions = {repo.name: repo.description for repo in self.config.repos}

        for repo_name, tests in by_repo.items():
            repo_points_earned = sum(r.points_earned for r in tests)
            repo_full_points = sum(r.full_points for r in tests)
            lines.append(f"\n{repo_name}  ({descriptions.get(repo_name, '')})")
            lines.append(f"  {repo_points_earned}/{repo_full_points} points")
            for r in tests:
                if r.passed:
                    mark = "PASS"
                elif r.partial:
                    mark = "PARTIAL"
                else:
                    mark = "FAIL"
                points_str = f" ({r.points_earned}/{r.full_points})"
                detail = f"  - {r.message}" if r.message else ""
                lines.append(f"    [{mark}] {r.name}: {r.description}{points_str}{detail}")

        lines.append("")
        lines.append("=" * 48)
        partial_str = f", {self.partial} partial" if self.partial > 0 else ""
        lines.append(
            f"TOTAL: {self.passed} passed{partial_str}, {self.failed} failed, {self.total} tests"
        )
        lines.append(
            f"POINTS: {self.total_points_earned}/{self.total_full_points}"
        )
        return "\n".join(lines)
