"""Render the multistage Dockerfile.

Stage 1 (cloner) clones every repo using the SSH key mounted as a BuildKit
secret, so the key never lands in an image layer. Stage 2 (runner) copies only the
cloned repos forward (the secret never crosses this boundary) and installs the
tooling needed to run the harness as throwaway per-repo users.

When nsjail sandboxing is enabled, an additional build stage compiles nsjail from
source for maximum compatibility with the runner base image.
"""

from __future__ import annotations

import shlex

from .config import Config, RepoSpec

RUNNER_BASE = {
    "node": "node:20-slim",
    "python": "python:3.12-slim",
}

# Host keys to trust inside the clone stage. Extend per git host as needed.
KNOWN_HOSTS = ["github.com"]

# nsjail version to build (pinned for reproducibility)
NSJAIL_VERSION = "3.4"


def _clone_command(repo: RepoSpec) -> str:
    target = shlex.quote(repo.name)
    url = shlex.quote(repo.url)
    branch = f"-b {shlex.quote(repo.ref)} " if repo.ref else ""
    return (
        "RUN --mount=type=secret,id=sshkey "
        'GIT_SSH_COMMAND="ssh -i /run/secrets/sshkey -o IdentitiesOnly=yes '
        '-o UserKnownHostsFile=/etc/ssh/ssh_known_hosts" '
        f"git clone --depth 1 {branch}{url} {target}"
    )


def _uses_nsjail(config: Config) -> bool:
    """Check if the config requires nsjail."""
    return config.sandbox.startswith("nsjail")


def render_dockerfile(config: Config) -> str:
    base = RUNNER_BASE[config.language]
    keyscan = " ".join(KNOWN_HOSTS)
    git_repos = config.git_repos
    local_repos = config.local_repos
    uses_nsjail = _uses_nsjail(config)

    lines: list[str] = ["# syntax=docker/dockerfile:1.7", ""]

    # ---- Stage: nsjail-builder (only present when nsjail is enabled) ----
    if uses_nsjail:
        lines += [
            "# ---- Stage: nsjail-builder (compile nsjail from source) ----",
            "FROM debian:bookworm-slim AS nsjail-builder",
            "",
            "# Install build dependencies in a single layer for caching",
            "RUN apt-get update && apt-get install -y --no-install-recommends \\",
            "    autoconf \\",
            "    automake \\",
            "    bison \\",
            "    ca-certificates \\",
            "    flex \\",
            "    gcc \\",
            "    g++ \\",
            "    git \\",
            "    libprotobuf-dev \\",
            "    libnl-route-3-dev \\",
            "    libtool \\",
            "    make \\",
            "    pkg-config \\",
            "    protobuf-compiler \\",
            "    && rm -rf /var/lib/apt/lists/*",
            "",
            f"# Clone and build nsjail (pinned to version {NSJAIL_VERSION})",
            f"RUN git clone --depth 1 --branch {NSJAIL_VERSION} https://github.com/google/nsjail.git /nsjail \\",
            "    && cd /nsjail \\",
            "    && make -j$(nproc)",
            "",
        ]

    # ---- Stage: clone (only present when there are git sources) ----
    if git_repos:
        lines += [
            "# ---- Stage: clone (SSH secret lives here only) ----",
            "FROM alpine/git AS cloner",
            "WORKDIR /src/repos",
            f"RUN mkdir -p /etc/ssh && ssh-keyscan {keyscan} >> /etc/ssh/ssh_known_hosts",
        ]
        lines += [_clone_command(repo) for repo in git_repos]
        # Drop VCS metadata so it cannot leak between stages or bloat the image.
        lines.append("RUN find /src/repos -name .git -type d -prune -exec rm -rf {} +")
        lines.append("")

    # ---- Stage: runner (no secret present) ----
    lines += [
        "# ---- Stage: runner (no secret present) ----",
        f"FROM {base} AS runner",
    ]

    # Base packages for privilege dropping
    base_packages = "util-linux"
    if config.language == "python":
        base_packages += " git"

    # nsjail runtime dependencies
    if uses_nsjail:
        # libnl-route-3-200 and libprotobuf are runtime dependencies
        base_packages += " libnl-route-3-200 libprotobuf32"

    lines.append(
        f"RUN apt-get update && apt-get install -y --no-install-recommends {base_packages} "
        "&& rm -rf /var/lib/apt/lists/*"
    )

    # Copy nsjail binary from builder stage
    if uses_nsjail:
        lines.append("")
        lines.append("# Copy nsjail binary from builder stage")
        lines.append("COPY --from=nsjail-builder /nsjail/nsjail /usr/local/bin/nsjail")

    lines.append("")
    lines.append("WORKDIR /work")

    # Git sources arrive from the clone stage; local folders are copied straight
    # from the (staged) build context. Both land under /work/repos/<name>.
    if git_repos:
        lines.append("COPY --from=cloner /src/repos /work/repos")
    for repo in local_repos:
        lines.append(f"COPY local_repos/{repo.name} /work/repos/{repo.name}")

    lines += [
        "COPY harness /work/harness",
        "COPY entrypoint.sh /work/entrypoint.sh",
    ]

    # Copy nsjail configuration files when using nsjail
    if uses_nsjail:
        lines.append("COPY nsjail /work/nsjail")

    lines += [
        "RUN chmod +x /work/entrypoint.sh /work/harness/*.sh",
        # entrypoint runs as root only to manage per-repo users; untrusted test
        # code is always executed as an unprivileged dk_<i> user.
        'ENTRYPOINT ["/work/entrypoint.sh"]',
        "",
    ]

    return "\n".join(lines)
