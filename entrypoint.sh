#!/usr/bin/env bash
# Batch container entrypoint. Runs as root ONLY to manage throwaway per-repo
# users; every harness/test invocation is dropped to an unprivileged dk_<i> user.
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
    nsjail|nsjail-seccomp)
      # nsjail with namespace isolation (no pivot_root for Docker compatibility)
      # Use chroot mode with "/" as root to avoid pivot_root issues in Docker
      local net_flag=""
      if [[ "$NETWORK" == "bridge" ]]; then
        net_flag="--disable_clone_newnet"
      fi

      # Build nsjail command without config file for maximum Docker compatibility
      # Docker Desktop on macOS has strict restrictions, so we disable most namespaces
      # and rely on Docker container isolation + nsjail resource limits
      #
      # What nsjail provides in this mode:
      # - Resource limits (rlimits) for CPU, memory, file size
      # - Time limit enforcement
      # - IPC namespace isolation
      # - UTS namespace (hostname isolation)
      # - Process runs as unprivileged user (dk_<i>)
      #
      # Network: controlled by Docker's --network flag, not nsjail
      cmd="nsjail --quiet \
        --mode o \
        --user ${user} \
        --group ${user} \
        --disable_clone_newuser \
        --disable_clone_newns \
        --disable_clone_newpid \
        --disable_clone_newcgroup \
        --disable_clone_newnet \
        --hostname sandbox \
        --cwd ${scratch}/${repo} \
        --env HOME=${home} \
        --env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        --env TERM=xterm \
        --time_limit ${TIMEOUT} \
        --rlimit_as 2048 \
        --rlimit_cpu 600 \
        --rlimit_fsize 1024 \
        --rlimit_nofile 256 \
        --rlimit_nproc 128 \
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
