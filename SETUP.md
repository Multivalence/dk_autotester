# Setup & Run Guide

This guide walks through installing dk_autotester, preparing inputs, and running
it against a list of repositories.

## 1. Prerequisites

- **Docker** with BuildKit (Docker 18.09+; any modern Docker Desktop / Engine).
  BuildKit is required for `--secret` mounts. Verify:

  ```bash
  docker version
  docker buildx version   # optional, confirms modern build backend
  ```

- **Python 3.10+** for the orchestrator. Verify:

  ```bash
  python3 --version
  ```

## 2. Install the orchestrator

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The only runtime dependency is `PyYAML`. The orchestrator shells out to the
`docker` CLI, so no Docker SDK is needed.

## 3. Prepare your inputs

### a. SSH key for cloning (git sources only)

Skip this step if all your sources are local folders (`path:`) -- no key is
needed and no clone stage is built.

Otherwise place the private key used to clone your repos somewhere the
orchestrator can read it (the default manifest expects `./secrets/id_ed25519`):

```bash
mkdir -p secrets
cp ~/.ssh/id_ed25519 secrets/id_ed25519
chmod 600 secrets/id_ed25519
```

The key is passed to `docker build` as a BuildKit secret and is mounted **only**
during the clone stage; it never lands in an image layer or the runner stage.
`secrets/` is gitignored.

> Host keys: the clone stage trusts `github.com` via `ssh-keyscan`. To support
> other hosts (e.g. GitLab), add them to `KNOWN_HOSTS` in
> [dkautotester/dockerfile.py](dkautotester/dockerfile.py).

### b. The test harness (bash file)

The harness installs dependencies and runs tests for a single repo, emitting the
output convention. Start from [harness/run_tests.sh](harness/run_tests.sh) and
adapt the install/test commands to your project. It is invoked as:

```bash
run_tests.sh <repo_dir>
```

Use the `dk_emit` helper to produce compliant result lines:

```bash
source "$(dirname "${BASH_SOURCE[0]}")/emit.sh"
dk_emit pass "build" "Project compiles" "" 1500
dk_emit fail "lint" "Lint passes" "3 errors"
```

### c. The manifest

Copy and edit the example:

```bash
cp examples/config.yaml my-run.yaml
```

Edit `my-run.yaml`: set `language`, point `test_script` at your harness, choose a
`batch_size`, and list your `sources`. Each source needs `name` + `description`
plus exactly one of:

- `url:` (+ optional `ref:`) for a git repo -- requires `ssh_secret:`, or
- `path:` for a local folder of tests -- no SSH key, no clone.

You can mix both kinds in one run. Paths (`ssh_secret`, `test_script`, local
`path`) are resolved relative to the manifest file. (`repos:` still works as an
alias for `sources:`.)

## 4. Run

```bash
python -m dkautotester --config my-run.yaml --output results.json
```

What happens:

1. The manifest is validated (fails fast on errors).
2. A multistage image is built once: git sources are cloned with the SSH secret
   (this stage is skipped if there are none) and local folders are copied in.
3. Sources run in sequential batches of `batch_size`; each one runs as an isolated
   throwaway user inside its batch container.
4. Output is parsed against the convention; a violation terminates the run.
5. A `results.json` report is written and a summary is printed to stdout.

### Useful flags

| flag                 | purpose                                                        |
|----------------------|----------------------------------------------------------------|
| `-c, --config`       | path to the manifest (required)                                |
| `-s, --script`       | path to test script (overrides config's `test_script`)         |
| `-o, --output`       | JSON report path (default `results.json`)                      |
| `-t, --tag`          | docker image tag to build (default `dkautotester:run`)         |
| `--print-dockerfile` | render the generated Dockerfile and exit (no Docker needed)    |
| `--skip-build`       | reuse an existing image (`--tag`) instead of rebuilding        |
| `--version`          | print version                                                  |

Inspect the generated Dockerfile without building:

```bash
python -m dkautotester --config my-run.yaml --print-dockerfile
```

## 5. Reading the results

Stdout shows a grouped, per-repo summary:

```
widget-api  (Order widget REST service)
  1/2 passed
    [PASS] npm_install: Install Node dependencies
    [FAIL] npm_test: Run the npm test suite  - 2 failing

================================================
TOTAL: 1 passed, 1 failed, 2 tests
```

`results.json` contains the machine-readable report (`summary` counts plus
per-repo test arrays with name, description, status, message, and duration).

The process exit code reflects the outcome (see the table in
[README.md](README.md#exit-codes)): `0` all passed, `1` some failed, `2` config
error, `3` convention violated, `4` docker error. This makes it easy to gate CI.

## 6. Enabling nsjail later

nsjail support is pre-wired. To turn it on once the image includes nsjail:

1. Set `sandbox: nsjail` in the manifest. This makes `dockerfile.py` add the
   nsjail install to the runner stage and tells the container to use the
   `NsjailExecutor` path.
2. Provide an nsjail config at `/work/nsjail.cfg` in the image (extend
   [dkautotester/dockerfile.py](dkautotester/dockerfile.py) to COPY it in) and
   flesh out `NsjailExecutor.wrap` in
   [dkautotester/executor.py](dkautotester/executor.py) / the `nsjail` branch in
   [entrypoint.sh](entrypoint.sh).

Each repo then gets a kernel-level sandbox on top of the per-user separation.

## Troubleshooting

- **`docker not found`**: install Docker and ensure `docker` is on your `PATH`.
- **Clone fails / permission denied (publickey)**: confirm the SSH key has access
  to the repos and that the git host is in `KNOWN_HOSTS`.
- **`protocol violation, terminating`**: your harness emitted output that breaks
  the convention. Run it locally on one repo and check the `##DKTEST##` lines, or
  use `dk_emit` to guarantee correct formatting.
- **A batch hangs**: lower `batch_size`, lower `timeout_seconds`, or set tighter
  `resources` caps. Each repo is hard-killed at `timeout_seconds`.
