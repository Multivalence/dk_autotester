#!/usr/bin/env bash
# Batch container entrypoint for NATIVE LINUX hosts.
# This version uses full nsjail namespace isolation capabilities.
#
# Use this entrypoint when running on:
# - Native Linux (bare metal or VM)
# - Linux CI/CD runners (GitHub Actions, GitLab CI, etc.)
# - Docker on Linux (not Docker Desktop)
#
# For Docker Desktop (macOS/Windows), use entrypoint.sh instead.
#
# Inputs (env):
#   DK_REPO_NAMES  newline- or space-separated repo names to run in this batch
#   DK_TIMEOUT     per-repo harness timeout in seconds (default 600)
#   DK_SANDBOX     "direct" (runuser), "nsjail", or "nsjail-seccomp"
#   DK_NETWORK     "none" (isolated) or "bridge" (inherit host network)
#
# Emits the test-output convention on stdout:
#   ##DKTEST_BEGIN## <repo>
#   ##DKTEST## {...}        (produced by the harness)
#   ##DKTEST_END## <repo> <exit_code>

set -u

HARNESS="/work/harness/run_tests.sh"
TIMEOUT="${DK_TIMEOUT:-600}"
SANDBOX="${DK_SANDBOX:-direct}"
NETWORK="${DK_NETWORK:-none}"
REPOS="${DK_REPO_NAMES:-}"

if [[ -z "${REPOS// /}" ]]; then
  echo "entrypoint: DK_REPO_NAMES is empty" >&2
  exit 2
fi

run_one() {
  local idx="$1" repo="$2"
  local user="dk_${idx}"
  local src="/work/repos/${repo}"
  local home="/home/${user}"
  local scratch="${home}/work"

  if [[ ! -d "$src" ]]; then
    echo "entrypoint: cloned repo dir missing: $src" >&2
    return 3
  fi

  # Fresh unprivileged user with an isolated HOME.
  useradd -m -d "$home" -s /bin/bash "$user" >/dev/null 2>&1

  # Private copy of the repo, readable only by this user.
  mkdir -p "$scratch"
  cp -a "$src" "${scratch}/${repo}"
  chown -R "$user":"$user" "$home"
  chmod 700 "$home"

  echo "##DKTEST_BEGIN## ${repo}"

  local cmd rc
  case "$SANDBOX" in
    nsjail)
      # Full namespace isolation (no seccomp filtering)
      # This mode provides maximum isolation on native Linux
      local nsjail_cfg="/work/nsjail/base-linux.cfg"
      local net_flag=""
      if [[ "$NETWORK" == "bridge" ]]; then
        net_flag="--disable_clone_newnet"
      fi

      # Full nsjail with all namespace features enabled
      # Requires: --privileged or --cap-add SYS_ADMIN --cap-add SYS_PTRACE
      cmd="nsjail --quiet \
        --config ${nsjail_cfg} \
        --cwd ${scratch}/${repo} \
        --bindmount_ro /work/harness:/work/harness \
        --bindmount ${home}:${home} \
        --env HOME=${home} \
        --env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        --env TERM=xterm \
        --env USER=${user} \
        --time_limit ${TIMEOUT} \
        ${net_flag} \
        -- /bin/bash ${HARNESS} ${scratch}/${repo}"
      ;;
    nsjail-seccomp)
      # Full namespace isolation + seccomp syscall filtering
      # Maximum security mode - only whitelisted syscalls allowed
      local nsjail_cfg="/work/nsjail/seccomp-linux.cfg"
      local net_flag=""
      if [[ "$NETWORK" == "bridge" ]]; then
        net_flag="--disable_clone_newnet"
      fi

      cmd="nsjail --quiet \
        --config ${nsjail_cfg} \
        --cwd ${scratch}/${repo} \
        --bindmount_ro /work/harness:/work/harness \
        --bindmount ${home}:${home} \
        --env HOME=${home} \
        --env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        --env TERM=xterm \
        --env USER=${user} \
        --time_limit ${TIMEOUT} \
        ${net_flag} \
        -- /bin/bash ${HARNESS} ${scratch}/${repo}"
      ;;
    *)
      # Default: runuser-based isolation (no nsjail)
      cmd="runuser -u ${user} -- bash ${HARNESS} ${scratch}/${repo}"
      ;;
  esac

  # For direct mode, use timeout wrapper; nsjail has its own --time_limit
  if [[ "$SANDBOX" == "direct" ]]; then
    timeout --signal=KILL "${TIMEOUT}" bash -c "$cmd"
  else
    bash -c "$cmd"
  fi
  rc=$?

  echo "##DKTEST_END## ${repo} ${rc}"

  # Teardown: no leftover processes, files, or ports leak to the next repo.
  pkill -KILL -u "$user" >/dev/null 2>&1 || true
  userdel -r "$user" >/dev/null 2>&1 || true
  rm -rf "$home"
}

i=0
for repo in $REPOS; do
  run_one "$i" "$repo"
  i=$((i + 1))
done
