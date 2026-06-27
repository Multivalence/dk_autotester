#!/usr/bin/env bash
# Example dk_autotester harness (the "bash file" in the manifest).
#
# Contract:
#   - Invoked as: run_tests.sh <repo_dir>
#   - Runs as an unprivileged per-repo user inside the batch container.
#   - MUST emit one `##DKTEST##` line per test via dk_emit (see emit.sh).
#   - The surrounding ##DKTEST_BEGIN##/##DKTEST_END## framing is added by
#     entrypoint.sh, so the harness only emits result lines.
#
# This sample installs dependencies and runs `npm test`. Adapt the install/test
# commands to your project; the only hard requirement is the emitted output.

set -u

REPO_DIR="${1:?usage: run_tests.sh <repo_dir>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${HERE}/emit.sh"

cd "$REPO_DIR" || {
  dk_emit fail "setup" "Enter the repository directory" "cannot cd into $REPO_DIR"
  exit 1
}

# --- install dependencies ---
start=$(date +%s%3N)
if [[ -f package.json ]]; then
  if npm install --no-audit --no-fund >/tmp/install.log 2>&1; then
    dk_emit pass "npm_install" "Install Node dependencies" "" "$(( $(date +%s%3N) - start ))"
  else
    dk_emit fail "npm_install" "Install Node dependencies" "$(tail -n 3 /tmp/install.log | tr '\n' ' ')" "$(( $(date +%s%3N) - start ))"
    exit 0   # nothing more to test; results already emitted
  fi
else
  dk_emit fail "npm_install" "Install Node dependencies" "no package.json found"
  exit 0
fi

# --- run the test suite ---
start=$(date +%s%3N)
if npm test >/tmp/test.log 2>&1; then
  dk_emit pass "npm_test" "Run the npm test suite" "" "$(( $(date +%s%3N) - start ))"
else
  dk_emit fail "npm_test" "Run the npm test suite" "$(tail -n 3 /tmp/test.log | tr '\n' ' ')" "$(( $(date +%s%3N) - start ))"
fi
