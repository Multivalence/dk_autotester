"""Manifest loading + validation (the input convention).

A manifest describes the repos to test, the SSH secret used to clone them, the
language runtime, and the bash harness to run. Validation fails fast (before any
Docker work) so misconfigured runs never spin up containers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

SUPPORTED_LANGUAGES = {"node", "python"}
SUPPORTED_SANDBOXES = {"none", "nsjail", "nsjail-seccomp"}
SUPPORTED_NETWORKS = {"none", "bridge"}


class ConfigError(Exception):
    """Raised when a manifest violates the input convention."""


@dataclass(frozen=True)
class RepoSpec:
    name: str
    description: str
    kind: str  # "git" or "local"
    url: Optional[str] = None
    ref: Optional[str] = None
    path: Optional[str] = None


@dataclass(frozen=True)
class Resources:
    memory: Optional[str] = None
    cpus: Optional[str] = None
    pids_limit: Optional[int] = None


@dataclass(frozen=True)
class Config:
    language: str
    ssh_secret: Optional[str]
    test_script: str
    repos: list[RepoSpec]
    timeout_seconds: int = 600
    batch_size: int = 25
    sandbox: str = "none"
    network: str = "none"
    resources: Resources = field(default_factory=Resources)

    @property
    def git_repos(self) -> list[RepoSpec]:
        return [r for r in self.repos if r.kind == "git"]

    @property
    def local_repos(self) -> list[RepoSpec]:
        return [r for r in self.repos if r.kind == "local"]


def _require(mapping: dict, key: str, where: str) -> object:
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"{where}: missing required field '{key}'")
    return mapping[key]


def _parse_repo(raw: object, index: int, base_dir: str) -> RepoSpec:
    where = f"sources[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: must be a mapping with name/description and url or path")
    name = str(_require(raw, "name", where))
    description = str(_require(raw, "description", where))

    has_url = bool(raw.get("url"))
    has_path = bool(raw.get("path"))
    if has_url and has_path:
        raise ConfigError(f"{where}: set either 'url' (git repo) or 'path' (local folder), not both")
    if not has_url and not has_path:
        raise ConfigError(f"{where}: must set 'url' (git repo) or 'path' (local folder)")

    if has_url:
        ref = raw.get("ref")
        return RepoSpec(
            name=name,
            description=description,
            kind="git",
            url=str(raw["url"]),
            ref=str(ref) if ref else None,
        )

    path = _resolve_path(str(raw["path"]), base_dir)
    if not os.path.isdir(path):
        raise ConfigError(f"{where}: local path is not a directory: {path}")
    return RepoSpec(name=name, description=description, kind="local", path=path)


def _parse_resources(raw: object) -> Resources:
    if raw is None:
        return Resources()
    if not isinstance(raw, dict):
        raise ConfigError("resources: must be a mapping")
    pids = raw.get("pids_limit")
    return Resources(
        memory=str(raw["memory"]) if raw.get("memory") else None,
        cpus=str(raw["cpus"]) if raw.get("cpus") else None,
        pids_limit=int(pids) if pids is not None else None,
    )


def load_config(path: str) -> Config:
    """Load and validate a manifest from a YAML file."""
    if not os.path.isfile(path):
        raise ConfigError(f"manifest not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError("manifest root must be a mapping")

    base_dir = os.path.dirname(os.path.abspath(path))

    language = str(_require(raw, "language", "manifest")).lower()
    if language not in SUPPORTED_LANGUAGES:
        raise ConfigError(
            f"language '{language}' not supported; expected one of {sorted(SUPPORTED_LANGUAGES)}"
        )

    sandbox = str(raw.get("sandbox", "none")).lower()
    if sandbox not in SUPPORTED_SANDBOXES:
        raise ConfigError(
            f"sandbox '{sandbox}' not supported; expected one of {sorted(SUPPORTED_SANDBOXES)}"
        )

    network = str(raw.get("network", "none")).lower()
    if network not in SUPPORTED_NETWORKS:
        raise ConfigError(
            f"network '{network}' not supported; expected one of {sorted(SUPPORTED_NETWORKS)}"
        )

    test_script = _resolve_path(str(_require(raw, "test_script", "manifest")), base_dir)
    if not os.path.isfile(test_script):
        raise ConfigError(f"test_script not found: {test_script}")

    sources_raw = raw.get("sources", raw.get("repos"))
    if sources_raw in (None, ""):
        raise ConfigError("manifest: missing required field 'sources' (or legacy 'repos')")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ConfigError("sources: must be a non-empty list")
    repos = [_parse_repo(r, i, base_dir) for i, r in enumerate(sources_raw)]

    # The SSH key (and clone stage) is only needed when a git source is present.
    needs_git = any(r.kind == "git" for r in repos)
    ssh_secret_raw = raw.get("ssh_secret")
    ssh_secret: Optional[str] = None
    if ssh_secret_raw:
        ssh_secret = _resolve_path(str(ssh_secret_raw), base_dir)
        if not os.path.isfile(ssh_secret):
            raise ConfigError(f"ssh_secret not found: {ssh_secret}")
    if needs_git and not ssh_secret:
        raise ConfigError(
            "ssh_secret is required because the manifest contains git sources (url:)"
        )

    seen: set[str] = set()
    for repo in repos:
        if repo.name in seen:
            raise ConfigError(f"duplicate repo name '{repo.name}'")
        seen.add(repo.name)

    batch_size = int(raw.get("batch_size", 25))
    if batch_size < 1:
        raise ConfigError("batch_size must be >= 1")

    timeout_seconds = int(raw.get("timeout_seconds", 600))
    if timeout_seconds < 1:
        raise ConfigError("timeout_seconds must be >= 1")

    return Config(
        language=language,
        ssh_secret=ssh_secret,
        test_script=test_script,
        repos=repos,
        timeout_seconds=timeout_seconds,
        batch_size=batch_size,
        sandbox=sandbox,
        network=network,
        resources=_parse_resources(raw.get("resources")),
    )


def _resolve_path(p: str, base_dir: str) -> str:
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))
