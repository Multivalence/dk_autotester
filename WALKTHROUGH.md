# Walkthrough: testing folders of code with dk_autotester

This guide uses the ready-made demo under [demo/](demo/) to show, step by step,
how dk_autotester runs a single bash file against many folders of code and reports
pass/fail per test. By the end you will know:

- where your test folders live and how they are laid out
- where the bash harness lives and what it must do
- how to write a configuration (manifest) file
- the input convention and the output convention
- how to confirm everything works (with and without Docker)

---

## 0. The demo at a glance

```
demo/
  config.yaml                 # the manifest (input convention)
  run_tests.sh                # the bash file run once per folder
  projects/                   # the folders of code to test
    calculator/               # passing project
      package.json
      src/calculator.js
      test/unit.js
      test/lint.js
    string-utils/             # passing project
      package.json
      src/string-utils.js
      test/unit.js
      test/lint.js
    broken-widget/            # has a deliberately FAILING unit test
      package.json
      src/widget.js
      test/unit.js
      test/lint.js
```

Three folders: two pass, one fails on purpose so you can see both outcomes.

---

## 1. Prerequisites

- Python 3.10+ (`python3 --version`)
- Node.js (`node --version`) - the demo projects are Node projects
- Docker with BuildKit, only for the full run in Step 6 (`docker version`)

Install the orchestrator from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2. Where local test folders go

Each "source" is just a directory of code. They can live anywhere on disk; in the
demo they sit under [demo/projects/](demo/projects/). A folder only needs whatever
your harness expects - here each one has a `package.json` with two scripts:

```json
{
  "scripts": {
    "test:unit": "node test/unit.js",
    "test:lint": "node test/lint.js"
  }
}
```

You point dk_autotester at each folder with a `path:` entry in the manifest (see
Step 4). Local folders are **copied** into the test image - there is no git clone
and no SSH key involved.

> Folders can also be git repos instead (use `url:` instead of `path:`); see
> [README.md](README.md). You can mix both in one run.

---

## 3. Where the bash file goes (the harness)

The harness is a single bash file run once per folder. In the demo it is
[demo/run_tests.sh](demo/run_tests.sh), and the manifest points at it with
`test_script:`. It can live anywhere; dk_autotester copies it into the image as
`/work/harness/run_tests.sh`.

Contract the harness must follow:

1. It is invoked as `run_tests.sh <folder>`.
2. It runs whatever you want (install dependencies, build, run tests).
3. For every check, it prints exactly one result line in the output convention
   (Step 5). The easiest way is the `dk_emit` helper in
   [harness/emit.sh](harness/emit.sh), which dk_autotester always ships next to
   your harness.

The demo harness does a **pre-install** then runs each `test:*` script:

```bash
# pre-install
npm install ... && dk_emit pass "preinstall" "Install dependencies (npm install)" ...

# run each test:* script, emitting one result per script
npm run test:unit && dk_emit pass "unit_tests" "Run 'test:unit'" ...
npm run test:lint && dk_emit pass "lint_tests" "Run 'test:lint'" ...
```

Read the full version in [demo/run_tests.sh](demo/run_tests.sh).

---

## 4. How to write a configuration file (the manifest)

The manifest is YAML. The demo's is [demo/config.yaml](demo/config.yaml):

```yaml
language: node                 # node | python (the runner base image)
test_script: ./run_tests.sh    # the bash file (relative to THIS file)

timeout_seconds: 120           # per-folder hard timeout
batch_size: 2                  # folders per container (resource control)
sandbox: none                  # none | nsjail
network: none                  # none | bridge

resources:                     # optional caps per batch container
  memory: 1g
  cpus: "1"
  pids_limit: 256

sources:                       # the list of folders/repos to test
  - name: calculator
    description: "Arithmetic helpers - expected to pass"
    path: ./projects/calculator

  - name: string-utils
    description: "String helpers - expected to pass"
    path: ./projects/string-utils

  - name: broken-widget
    description: "Widget renderer with a known bug - unit test fails"
    path: ./projects/broken-widget
```

Rules (this is the **input convention**):

- Every source needs a `name` and a `description`. These flow into the report so
  each result is self-describing.
- Each source has **exactly one** of `path:` (local folder) or `url:` (git repo,
  with optional `ref:`).
- `ssh_secret:` is only required when at least one source is a git `url:`. The
  demo is all local, so it is omitted entirely.
- All relative paths (`test_script`, `path`, `ssh_secret`) resolve relative to the
  manifest file's directory.

The manifest is fully validated before any Docker work; mistakes fail fast with a
clear message.

---

## 5. The output convention (what the harness prints)

dk_autotester reads results from stdout. Your harness emits one JSON object per
test, wrapped by `BEGIN`/`END` markers that dk_autotester adds automatically per
folder:

```
##DKTEST_BEGIN## calculator
##DKTEST## {"name":"preinstall","description":"Install dependencies (npm install)","status":"pass","message":"","duration_ms":0}
##DKTEST## {"name":"unit_tests","description":"Run 'test:unit'","status":"pass","message":"","duration_ms":12}
##DKTEST_END## calculator 0
```

Each `##DKTEST##` object must contain:

| field         | required | meaning                                |
|---------------|----------|----------------------------------------|
| `name`        | yes      | unique test name                        |
| `description` | yes      | human-readable description              |
| `status`      | yes      | `pass` or `fail`                        |
| `message`     | no       | failure detail / notes                  |
| `duration_ms` | no       | integer milliseconds                    |

Use `dk_emit` so you never format this by hand:

```bash
dk_emit pass "unit_tests" "Run the unit suite" "" 12
dk_emit fail "unit_tests" "Run the unit suite" "2 assertions failed" 34
```

If a folder emits malformed JSON, a bad `status`, a missing field, or zero
results, **the whole run terminates** with exit code 3. This is intentional: a
harness that does not follow the convention is treated as a hard error rather than
silently producing a wrong report.

---

## 6. Confirm it works

### Step 6a - Quick check: run the harness on one folder (no Docker)

This is the fastest way to confirm your harness and a folder are wired correctly.
From the project root:

```bash
bash demo/run_tests.sh demo/projects/calculator
```

Expected: three compliant result lines, all `"status":"pass"`:

```
##DKTEST## {"name":"preinstall","description":"Install dependencies (npm install)","status":"pass",...}
##DKTEST## {"name":"unit_tests","description":"Run 'test:unit'","status":"pass",...}
##DKTEST## {"name":"lint_tests","description":"Run 'test:lint'","status":"pass",...}
```

Now try the broken one and watch a `fail` line appear:

```bash
bash demo/run_tests.sh demo/projects/broken-widget
```

> The local `npm install` may drop a `package-lock.json` / `node_modules` in the
> folder; both are gitignored. Inside Docker each folder is a throwaway copy, so
> nothing leaks between runs.

### Step 6b - Inspect the generated Dockerfile (no Docker needed)

See exactly what will be built (note: no clone stage and no secret, because the
demo is all local folders):

```bash
python -m dkautotester --config demo/config.yaml --print-dockerfile
```

### Step 6c - See the full report without Docker (optional)

This drives the real config loader, the protocol parser, and the report renderer
over locally-produced output - handy for verifying the whole chain on a machine
without Docker:

```bash
python - <<'PY'
import subprocess, io
from dkautotester.config import load_config
from dkautotester.protocol import parse_stream
from dkautotester.report import Report

cfg = load_config("demo/config.yaml")
stream = io.StringIO()
for r in cfg.repos:
    out = subprocess.run(["bash", "demo/run_tests.sh", r.path],
                         text=True, capture_output=True)
    stream.write(f"##DKTEST_BEGIN## {r.name}\n{out.stdout}##DKTEST_END## {r.name} {out.returncode}\n")
report = Report(parse_stream(stream.getvalue(), [r.name for r in cfg.repos]), cfg)
print(report.render_text())
PY
```

Expected summary:

```
calculator     3/3 passed
string-utils   3/3 passed
broken-widget  2/3 passed   ([FAIL] unit_tests)
================================================
TOTAL: 8 passed, 1 failed, 9 tests
```

### Step 6d - The real thing: run through Docker

This builds the image (copying the folders in) and runs the batches:

```bash
python -m dkautotester --config demo/config.yaml --output results.json
```

You can also override the test script from the command line with `--script`:

```bash
python -m dkautotester --config demo/config.yaml --script ./my_harness.sh --output results.json
```

You will see batch progress on stderr (3 folders, `batch_size: 2` -> 2 batches),
the same grouped summary on stdout, and a machine-readable `results.json`.

---

## 7. Reading the results

stdout shows a per-folder summary grouped by source, with the name and description
of every test. `results.json` is the machine-readable version:

```json
{
  "summary": { "repos": 3, "tests": 9, "passed": 8, "failed": 1 },
  "repos": [
    {
      "name": "broken-widget",
      "description": "Widget renderer with a known bug - unit test fails",
      "passed": 2,
      "failed": 1,
      "tests": [
        { "name": "preinstall",  "status": "pass", ... },
        { "name": "unit_tests",  "status": "fail", "message": "...", ... },
        { "name": "lint_tests",  "status": "pass", ... }
      ]
    }
  ]
}
```

The process exit code reflects the outcome, so you can gate CI on it:

| code | meaning                          |
|------|----------------------------------|
| 0    | all tests passed                  |
| 1    | ran fine, at least one test failed |
| 2    | bad manifest                      |
| 3    | output convention violated        |
| 4    | docker build/run error            |

---

## 8. Prove the pass/fail wiring yourself

Make the failing project pass: open
[demo/projects/broken-widget/src/widget.js](demo/projects/broken-widget/src/widget.js)
and fix `render` so it includes the label:

```js
function render(label) {
  return `<button>${label}</button>`;
}
```

Re-run Step 6a (or 6c/6d). `broken-widget` now reports `3/3 passed` and the total
becomes `9 passed, 0 failed`. Break it again to flip it back.

---

## 9. Use it on your own folders

1. Put each project in its own folder (anywhere).
2. Copy [demo/config.yaml](demo/config.yaml) to a new manifest and list your
   folders under `sources:` with `path:`, each with a `name` and `description`.
3. Adapt [demo/run_tests.sh](demo/run_tests.sh): change the install/test commands
   to fit your projects, and emit one `dk_emit` line per check.
4. Verify one folder locally (Step 6a), then run the whole set (Step 6d).

For git repositories instead of local folders, SSH key handling, the python
runtime, batching/isolation details, and enabling nsjail, see
[README.md](README.md) and [SETUP.md](SETUP.md).
