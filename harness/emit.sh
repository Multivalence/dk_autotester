#!/usr/bin/env bash
# Helper for writing dk_autotester result lines from a bash harness.
#
# Source this file and call one of:
#
#   dk_emit pass|fail <name> <description> [message] [duration_ms]
#     Legacy mode: pass = 1/1 points, fail = 0/1 points
#
#   dk_emit_points <points_earned> <full_points> <name> <description> [message] [duration_ms]
#     Points mode: status derived from points (pass=100%, fail=0%, partial=1-99%)
#
# It prints exactly one compliant line:
#   ##DKTEST## {"name":...,"description":...,"status":...,"points_earned":...,"full_points":...,...}

# JSON-escape a string (quotes, backslashes, control chars).
_dk_json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\n'/\\n}"
  printf '%s' "$s"
}

# Legacy emit: pass/fail with implicit 1/0 points
dk_emit() {
  local status="$1" name="$2" description="$3" message="${4:-}" duration="${5:-0}"

  if [[ "$status" != "pass" && "$status" != "fail" ]]; then
    echo "dk_emit: status must be 'pass' or 'fail', got '$status'" >&2
    return 1
  fi

  local points_earned=0
  local full_points=1
  if [[ "$status" == "pass" ]]; then
    points_earned=1
  fi

  printf '##DKTEST## {"name":"%s","description":"%s","status":"%s","points_earned":%s,"full_points":%s,"message":"%s","duration_ms":%s}\n' \
    "$(_dk_json_escape "$name")" \
    "$(_dk_json_escape "$description")" \
    "$status" \
    "$points_earned" \
    "$full_points" \
    "$(_dk_json_escape "$message")" \
    "${duration}"
}

# Points-based emit: status derived from points_earned/full_points ratio
dk_emit_points() {
  local points_earned="$1" full_points="$2" name="$3" description="$4" message="${5:-}" duration="${6:-0}"

  # Derive status from points using awk for portable float comparison
  local status
  status=$(awk -v earned="$points_earned" -v full="$full_points" 'BEGIN {
    if (earned >= full) print "pass"
    else if (earned <= 0) print "fail"
    else print "partial"
  }')

  printf '##DKTEST## {"name":"%s","description":"%s","status":"%s","points_earned":%s,"full_points":%s,"message":"%s","duration_ms":%s}\n' \
    "$(_dk_json_escape "$name")" \
    "$(_dk_json_escape "$description")" \
    "$status" \
    "$points_earned" \
    "$full_points" \
    "$(_dk_json_escape "$message")" \
    "${duration}"
}
