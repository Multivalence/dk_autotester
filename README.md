# dk_autotester

Run a single bash test harness against many git repositories inside isolated,
batched Docker containers, and collect a pass/fail report.

It is built for an autograder-style workflow: each source is a "submission", the
bash harness installs dependencies and runs that source's tests, and every test
result is reported with a name and description.

Each source can be **either** a git repository (cloned with an SSH key) **or** a
local folder of tests (copied in directly). The two can be mixed in one run, and
the SSH key + clone stage are skipped entirely when no git source is present.

## How it works

```
manifest + ssh key + harness
            |
            v
   [ multistage docker build ]
   stage 1 (cloner)  -- clones git sources using the SSH key as a BuildKit
                        secret (skipped if there are no git sources)
   stage 2 (runner)  -- copies ONLY the sources forward (cloned repos + local
                        folders); no secret present
            |
            v
   sources run in batches of N (one container at a time -> bounded resources)
   inside each container every source runs as its own throwaway Linux user
            |
            v
   harness emits the test-output convention -> parsed -> results.json + summary
```

See [SETUP.md](SETUP.md) for installation and run instructions.

## Isolation model (hybrid)

- Repos are processed in **batches of `batch_size`**; each batch is one
  `docker run`. Only one container is alive at a time, so CPU/memory stay bounded
  regardless of repo count.
- Within a container, each repo runs as a distinct unprivileged user (`dk_<i>`)
  with its own `HOME`, a private `chmod 700` copy of the repo, and full teardown
  (kill processes, delete user + files) before the next repo. Repos cannot see
  each other's `node_modules`/venv, files, ports, or processes.
- The SSH key is only ever mounted during the clone build stage via BuildKit
  `--secret`, and is dropped before the runner stage.
- `nsjail` is wired as a future second isolation layer (see `sandbox: nsjail`),
  with the executor and entrypoint already structured to support it.

## Input convention (manifest)

A YAML manifest describes the run. Every source must declare `name` and
`description`, plus exactly one of `url` (git repo) or `path` (local folder). See
[examples/config.yaml](examples/config.yaml).

```yaml
language: node                     # node | python
ssh_secret: ./secrets/id_ed25519   # only used/required if a git source exists
test_script: ./harness/run_tests.sh
timeout_seconds: 600               # per-source harness timeout
batch_size: 25                     # sources per container
sandbox: none                      # none | nsjail
network: none                      # none | bridge
resources:
  memory: 2g
  cpus: "2"
  pids_limit: 512
sources:                           # `repos:` is also accepted (legacy alias)
  - name: widget-api               # git repo: cloned with the SSH key
    description: "Order widget REST service"
    url: git@github.com:example-org/widget-api.git
    ref: main                      # optional
  - name: sample-local             # local folder: copied in, no SSH/clone
    description: "Local test folder"
    path: ./sample_tests
```

The manifest is fully validated before any Docker work; bad languages, missing
files, duplicate names, sources that set both/neither `url` and `path`, a missing
local `path`, or a git source without `ssh_secret` all fail fast.

## Output convention (test results)

The harness writes results to stdout. The orchestrator adds the `BEGIN`/`END`
framing per repo; the harness emits the `##DKTEST##` lines (use the `dk_emit`
helper in [harness/emit.sh](harness/emit.sh)):

```
##DKTEST_BEGIN## <repo_name>
##DKTEST## {"name":"npm_test","description":"Run suite","status":"pass","message":"","duration_ms":900}
##DKTEST_END## <repo_name> <harness_exit_code>
```

Each `##DKTEST##` object must contain:

| field         | required | meaning                                  |
|---------------|----------|------------------------------------------|
| `name`        | yes      | unique test name                          |
| `description` | yes      | human-readable description of the test    |
| `status`      | yes      | `pass` or `fail`                          |
| `message`     | no       | failure detail / notes (default `""`)     |
| `duration_ms` | no       | integer milliseconds (default `0`)        |

**The run terminates** (exit code 3) if the convention is violated: malformed
JSON, an invalid `status`, a missing required field, unmatched markers, or a repo
that emits zero results.

## Project layout

```
dkautotester/        orchestrator package
  config.py          manifest loading + validation (input convention)
  protocol.py        output convention parser + termination logic
  dockerfile.py      multistage Dockerfile renderer
  docker_runner.py   BuildKit build + batched docker run
  executor.py        DirectExecutor (runuser) + NsjailExecutor stub
  report.py          results.json + stdout summary
  cli.py             pipeline entrypoint
entrypoint.sh        container loop: per-repo user create/run/cleanup
harness/
  run_tests.sh       example harness (adapt to your project)
  emit.sh            dk_emit helper for compliant output
examples/config.yaml example manifest
```

## Exit codes

| code | meaning                                  |
|------|------------------------------------------|
| 0    | all tests passed                          |
| 1    | ran successfully, at least one test failed |
| 2    | configuration error                       |
| 3    | output convention violated (terminated)   |
| 4    | docker build/run error                    |
