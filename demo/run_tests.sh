#!/usr/bin/env bash
# Demo dk_autotester harness.
#
# dk_autotester runs this file ONCE per source folder:
#     run_tests.sh <folder>
#
# It performs a pre-install step and then runs each "test:*" npm script in the
# folder, emitting one ##DKTEST## result line per step (see emit.sh / the output
# convention). The BEGIN/END framing around these lines is added by dk_autotester.
#
# This demo shows both legacy dk_emit (pass/fail) and dk_emit_points (partial credit).

set -u

FOLDER="${1:?usage: run_tests.sh <folder>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Locate emit.sh both inside the container (/work/harness/emit.sh, same dir) and
# when running locally from the repo (../harness/emit.sh).
for cand in "${HERE}/emit.sh" "${HERE}/../harness/emit.sh"; do
  if [[ -f "$cand" ]]; then
    # shellcheck source=/dev/null
    source "$cand"
    break
  fi
done

now_ms() {
  # Milliseconds since epoch. Falls back to seconds*1000 on systems whose `date`
  # lacks %N (e.g. macOS), so the harness also runs locally for quick checks.
  local n
  n=$(date +%s%3N 2>/dev/null)
  if [[ -z "$n" || "$n" == *N* ]]; then
    n=$(( $(date +%s) * 1000 ))
  fi
  printf '%s' "$n"
}

cd "$FOLDER" || {
  # Using dk_emit_points: 0 out of 5 points for failing to enter folder
  dk_emit_points 0 5 "setup" "Enter the source folder" "cannot cd into $FOLDER"
  exit 1
}

# --- pre-install step (worth 5 points) ---
start=$(now_ms)
if npm install --no-audit --no-fund >/tmp/install.log 2>&1; then
  dk_emit_points 5 5 "preinstall" "Install dependencies (npm install)" "" "$(( $(now_ms) - start ))"
else
  dk_emit_points 0 5 "preinstall" "Install dependencies (npm install)" \
    "$(tail -n 3 /tmp/install.log | tr '\n' ' ')" "$(( $(now_ms) - start ))"
  exit 0   # nothing else can run; results already emitted
fi

# --- run every test:* script defined in package.json ---
# Unit tests worth 10 points, lint tests worth 5 points
declare -A stage_points=( ["unit"]=10 ["lint"]=5 )

for stage in unit lint; do
  script="test:${stage}"
  points="${stage_points[$stage]}"

  # Skip scripts a project does not define.
  if ! node -e "process.exit((require('./package.json').scripts||{})['${script}']?0:1)" 2>/dev/null; then
    continue
  fi
  start=$(now_ms)
  if npm run "${script}" >/tmp/"${stage}".log 2>&1; then
    dk_emit_points "$points" "$points" "${stage}_tests" "Run '${script}'" "" "$(( $(now_ms) - start ))"
  else
    dk_emit_points 0 "$points" "${stage}_tests" "Run '${script}'" \
      "$(tail -n 3 /tmp/${stage}.log | tr '\n' ' ')" "$(( $(now_ms) - start ))"
  fi
done