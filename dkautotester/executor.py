"""Executor abstraction: how a single repo's harness command is wrapped.

This is the seam for sandboxing. Today `DirectExecutor` runs the harness as the
per-repo unprivileged user via `runuser`. `NsjailExecutor` wraps the same command
in nsjail for kernel-level namespace isolation, optionally with seccomp filtering.

The executor only builds an argv list -- it does not itself run anything inside the
container; that is done by entrypoint.sh, which these classes mirror. The
orchestrator uses `executor_directive()` to tell entrypoint.sh which mode to use.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from .config import Config


class Executor(ABC):
    """Builds the shell directive entrypoint.sh uses to launch a repo's harness."""

    name: str

    @abstractmethod
    def wrap(self, user: str, script_path: str, repo_dir: str) -> str:
        """Return a shell command string that runs `script_path repo_dir` as `user`."""


class DirectExecutor(Executor):
    name = "direct"

    def wrap(self, user: str, script_path: str, repo_dir: str) -> str:
        return f'runuser -u {user} -- bash {script_path} "{repo_dir}"'


class NsjailExecutor(Executor):
    """Kernel-level sandbox using nsjail with namespace isolation.

    Supports two modes:
    - nsjail: Namespace isolation only (base.cfg)
    - nsjail-seccomp: Namespace isolation + seccomp syscall filtering (seccomp.cfg)

    Network access is controlled via the --disable_clone_newnet flag:
    - When network=none: network namespace is enabled (isolated)
    - When network=bridge: network namespace is disabled (inherits host network)
    """

    def __init__(self, seccomp: bool = False, network: str = "none"):
        self.seccomp = seccomp
        self.network = network

    @property
    def name(self) -> str:
        return "nsjail-seccomp" if self.seccomp else "nsjail"

    def wrap(self, user: str, script_path: str, repo_dir: str) -> str:
        # Select config file based on seccomp setting
        config_file = "/work/nsjail/seccomp.cfg" if self.seccomp else "/work/nsjail/base.cfg"

        # Home directory is the parent of repo_dir (e.g., /home/dk_0)
        home_dir = os.path.dirname(repo_dir)

        # Build nsjail command
        parts = [
            "nsjail",
            "--quiet",
            f"--config {config_file}",
            f"--cwd {repo_dir}",
            # Bind mount the harness directory (read-only)
            "--bindmount_ro /work/harness:/work/harness",
            # Bind mount the user's home directory (read-write for test artifacts)
            f"--bindmount {home_dir}:{home_dir}",
            # Pass essential environment variables
            f"--env HOME={home_dir}",
            "--env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "--env TERM=xterm",
        ]

        # Network handling: disable network namespace to allow network access
        if self.network == "bridge":
            parts.append("--disable_clone_newnet")

        # Command to execute
        parts.append(f"-- /bin/bash {script_path} {repo_dir}")

        return " ".join(parts)


def get_executor(config: Config) -> Executor:
    """Factory function to create the appropriate executor based on config."""
    if config.sandbox == "nsjail":
        return NsjailExecutor(seccomp=False, network=config.network)
    elif config.sandbox == "nsjail-seccomp":
        return NsjailExecutor(seccomp=True, network=config.network)
    return DirectExecutor()


def executor_directive(config: Config) -> str:
    """The value passed to the container as DK_SANDBOX so entrypoint.sh matches it."""
    return get_executor(config).name
