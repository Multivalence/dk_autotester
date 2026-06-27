"""Drive Docker: build the image once, then run repos in isolated batches.

The build uses BuildKit with the SSH key passed as `--secret` so it is mounted
only during the clone stage. Each batch is a separate `docker run` (one container
alive at a time -> bounded CPU/memory), and inside each container repos are
further isolated as throwaway per-user processes by entrypoint.sh.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from .config import Config, RepoSpec
from .dockerfile import render_dockerfile
from .executor import executor_directive

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRYPOINT_SRC = os.path.join(PACKAGE_ROOT, "entrypoint.sh")
EMIT_SRC = os.path.join(PACKAGE_ROOT, "harness", "emit.sh")
NSJAIL_CFG_DIR = os.path.join(PACKAGE_ROOT, "nsjail")


class DockerError(Exception):
    """Raised when a docker build/run command fails."""


@dataclass
class BatchRun:
    repos: list[RepoSpec]
    stdout: str
    stderr: str
    returncode: int


def _check_docker() -> None:
    if shutil.which("docker") is None:
        raise DockerError("`docker` not found on PATH; install Docker to run dk_autotester")


def _stage_build_context(config: Config) -> str:
    """Assemble a build context dir with the Dockerfile, entrypoint, and harness."""
    ctx = tempfile.mkdtemp(prefix="dkautotester-ctx-")
    with open(os.path.join(ctx, "Dockerfile"), "w", encoding="utf-8") as fh:
        fh.write(render_dockerfile(config))

    shutil.copy2(ENTRYPOINT_SRC, os.path.join(ctx, "entrypoint.sh"))

    harness_dir = os.path.join(ctx, "harness")
    os.makedirs(harness_dir, exist_ok=True)
    shutil.copy2(EMIT_SRC, os.path.join(harness_dir, "emit.sh"))
    # The user's bash file always lands at the path entrypoint.sh expects.
    shutil.copy2(config.test_script, os.path.join(harness_dir, "run_tests.sh"))

    # Local-folder sources are copied into the context so the runner stage can
    # COPY them in (no git clone / SSH key involved for these).
    for repo in config.local_repos:
        dst = os.path.join(ctx, "local_repos", repo.name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copytree(repo.path, dst)

    # Copy nsjail configuration files when using nsjail sandbox
    if _uses_nsjail(config) and os.path.isdir(NSJAIL_CFG_DIR):
        nsjail_dst = os.path.join(ctx, "nsjail")
        shutil.copytree(NSJAIL_CFG_DIR, nsjail_dst)

    return ctx


def build_image(config: Config, tag: str = "dkautotester:run") -> str:
    """Build the runner image, returning its tag."""
    _check_docker()
    ctx = _stage_build_context(config)
    try:
        cmd = ["docker", "build"]
        # The SSH secret is only mounted when there are git sources to clone.
        if config.git_repos:
            cmd += ["--secret", f"id=sshkey,src={config.ssh_secret}"]
        cmd += ["-f", os.path.join(ctx, "Dockerfile"), "-t", tag, ctx]
        env = {**os.environ, "DOCKER_BUILDKIT": "1"}
        proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
        if proc.returncode != 0:
            raise DockerError(
                f"docker build failed (exit {proc.returncode}):\n{proc.stderr}"
            )
        return tag
    finally:
        shutil.rmtree(ctx, ignore_errors=True)


def _uses_nsjail(config: Config) -> bool:
    """Check if the config requires nsjail."""
    return config.sandbox.startswith("nsjail")


def _run_args(config: Config) -> list[str]:
    args = ["docker", "run", "--rm", "--network", config.network]

    # nsjail requires additional capabilities to create namespaces
    if _uses_nsjail(config):
        args += [
            "--cap-add", "SYS_ADMIN",      # Required for namespace creation
            "--cap-add", "SYS_PTRACE",     # Required for seccomp and process control
            "--security-opt", "apparmor=unconfined",  # Avoid AppArmor conflicts
        ]

    res = config.resources
    if res.memory:
        args += ["--memory", res.memory]
    if res.cpus:
        args += ["--cpus", res.cpus]
    if res.pids_limit is not None:
        args += ["--pids-limit", str(res.pids_limit)]
    return args


def run_batch(config: Config, image: str, batch: list[RepoSpec]) -> BatchRun:
    """Run a single batch container for the given repos and capture its stdout."""
    names = " ".join(r.name for r in batch)
    args = _run_args(config) + [
        "-e", f"DK_REPO_NAMES={names}",
        "-e", f"DK_TIMEOUT={config.timeout_seconds}",
        "-e", f"DK_SANDBOX={executor_directive(config)}",
        "-e", f"DK_NETWORK={config.network}",
        image,
    ]
    # Allow each repo its full timeout plus container startup overhead.
    wall_timeout = config.timeout_seconds * len(batch) + 120
    try:
        proc = subprocess.run(args, text=True, capture_output=True, timeout=wall_timeout)
    except subprocess.TimeoutExpired as exc:
        raise DockerError(
            f"batch container exceeded wall timeout ({wall_timeout}s) for repos "
            f"{[r.name for r in batch]}"
        ) from exc
    return BatchRun(
        repos=batch,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )


def chunk(repos: list[RepoSpec], size: int) -> list[list[RepoSpec]]:
    return [repos[i:i + size] for i in range(0, len(repos), size)]
