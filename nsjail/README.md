# nsjail Configuration Guide

This directory contains nsjail configuration files for kernel-level sandboxing of test execution in dk_autotester.

## Overview

[nsjail](https://github.com/google/nsjail) is a lightweight process isolation tool that uses Linux namespaces and seccomp-bpf to create secure sandboxes. dk_autotester uses nsjail to provide additional isolation on top of Docker container isolation.

## Docker Compatibility Note

Due to restrictions in Docker Desktop (especially on macOS), nsjail runs in a **Docker-compatible mode** that disables namespace features that conflict with Docker's own isolation:

- User namespace: Disabled (uses Docker's user)
- Mount namespace: Disabled (uses Docker's filesystem)
- PID namespace: Disabled (uses Docker's PID namespace)
- Cgroup namespace: Disabled (uses Docker's cgroups)
- Network namespace: Disabled (uses Docker's network)

**What nsjail provides in Docker-compatible mode:**
- **Resource limits** (rlimits) for CPU, memory, file size, processes
- **Time limit enforcement** with automatic termination
- **IPC namespace** isolation (System V IPC, POSIX message queues)
- **UTS namespace** (hostname isolation)
- **Unprivileged user execution** (process runs as dk_<i> user)

For full namespace isolation, deploy on a native Linux host (not Docker Desktop).

## Configuration Files

### Docker Desktop (macOS/Windows) - uses `entrypoint.sh`

| File | Sandbox Mode | Description |
|------|--------------|-------------|
| `base.cfg` | `nsjail` | Resource limits + IPC/UTS isolation (Docker-compatible) |
| `seccomp.cfg` | `nsjail-seccomp` | Same as nsjail (seccomp not active in Docker mode) |

### Native Linux - uses `entrypoint-linux.sh`

| File | Sandbox Mode | Description |
|------|--------------|-------------|
| `base-linux.cfg` | `nsjail` | Full namespace isolation (user, mount, PID, IPC, UTS, cgroup, net) |
| `seccomp-linux.cfg` | `nsjail-seccomp` | Full namespace isolation + seccomp syscall filtering |

## Choosing the Right Entrypoint

| Environment | Entrypoint | Config Files |
|-------------|------------|--------------|
| Docker Desktop (macOS) | `entrypoint.sh` | `base.cfg`, `seccomp.cfg` |
| Docker Desktop (Windows) | `entrypoint.sh` | `base.cfg`, `seccomp.cfg` |
| Docker on Linux | `entrypoint-linux.sh` | `base-linux.cfg`, `seccomp-linux.cfg` |
| Native Linux (no Docker) | `entrypoint-linux.sh` | `base-linux.cfg`, `seccomp-linux.cfg` |
| CI/CD (GitHub Actions, etc.) | `entrypoint-linux.sh` | `base-linux.cfg`, `seccomp-linux.cfg` |

To use the Linux entrypoint, modify `dockerfile.py` to copy `entrypoint-linux.sh` instead of `entrypoint.sh`.

## Sandbox Modes

### Mode: `none` (default)

```yaml
sandbox: none
```

Uses `runuser` for UID-based isolation. Each test runs as a separate unprivileged user (`dk_0`, `dk_1`, etc.) with its own home directory. This provides:
- Process isolation via separate UIDs
- Filesystem isolation via `chmod 700` on home directories
- No resource limit enforcement beyond Docker limits

**Use when:** You need maximum compatibility and trust the test code.

### Mode: `nsjail`

```yaml
sandbox: nsjail
```

**On Docker Desktop (macOS/Windows):**
- **IPC namespace:** Isolated System V IPC and POSIX message queues
- **UTS namespace:** Isolated hostname (prevents leaking container hostname)
- **Resource limits:** Hard limits on memory, CPU time, file size, processes
- **Time limit:** Automatic process termination after timeout
- **Unprivileged user:** Tests run as non-root dk_<i> user

**On Native Linux (using `entrypoint-linux.sh`):**
- **User namespace:** UID/GID mapping for unprivileged sandboxing
- **Mount namespace:** Isolated filesystem with pivot_root
- **PID namespace:** Process isolation (jailed process is PID 1)
- **IPC namespace:** Isolated System V IPC and POSIX message queues
- **UTS namespace:** Isolated hostname
- **Cgroup namespace:** Isolated cgroup view
- **Network namespace:** Complete network isolation (optional)
- **Resource limits:** Hard limits via rlimits
- **Time limit:** Automatic process termination

**Use when:** You want enforced resource limits and namespace isolation.

### Mode: `nsjail-seccomp`

```yaml
sandbox: nsjail-seccomp
```

**On Docker Desktop:** Same as `nsjail` mode (seccomp not active due to Docker restrictions).

**On Native Linux (using `entrypoint-linux.sh`):**
Uses nsjail with full namespace isolation AND seccomp-bpf syscall filtering:
- All namespace protections from `nsjail` mode
- **Seccomp whitelist:** Only explicitly allowed syscalls work
- **Blocked syscalls:** ptrace, mount, module loading, etc. return `EPERM`

**Use when:** Running untrusted code where you want maximum security. Be aware that some legitimate operations may be blocked.

## Network Modes

Network access is controlled independently of sandbox mode:

```yaml
network: none    # Default - no network access
network: bridge  # Inherit Docker container's network
```

| Network Mode | nsjail Behavior |
|--------------|-----------------|
| `none` | Network namespace enabled (isolated) |
| `bridge` | Network namespace disabled (inherits host) |

## Configuration Syntax

nsjail uses Protocol Buffer text format. Here's the structure:

### Basic Structure

```protobuf
name: "sandbox_name"
description: "Description"
mode: ONCE  # ONCE, LISTEN, EXECVE

hostname: "sandbox"

# Namespace flags
clone_newuser: true
clone_newns: true
clone_newpid: true
clone_newipc: true
clone_newuts: true
clone_newcgroup: true
clone_newnet: true

# Resource limits
rlimit_as: 2048       # Virtual memory (MB)
rlimit_cpu: 600       # CPU time (seconds)
rlimit_fsize: 1024    # Max file size (MB)
rlimit_nofile: 256    # Open file descriptors
rlimit_nproc: 128     # Processes/threads
```

### Mount Configuration

```protobuf
# Bind mount (map host path into jail)
mount {
    src: "/host/path"
    dst: "/jail/path"
    is_bind: true
    rw: false           # Read-only by default
    mandatory: true     # Fail if mount fails
}

# Tmpfs mount (in-memory filesystem)
mount {
    dst: "/tmp"
    fstype: "tmpfs"
    rw: true
    options: "size=512M"
}

# Proc filesystem
mount {
    dst: "/proc"
    fstype: "proc"
    rw: false
}
```

### Seccomp Policy (Kafel syntax)

```protobuf
seccomp_string: "POLICY name {\n\
  ALLOW {\n\
    read, write, open, close,\n\
    # ... syscalls to allow\n\
  }\n\
}\n\
USE name DEFAULT KILL\n"
```

## Customizing Configurations

### Adding Allowed Syscalls

If a test requires a syscall blocked by seccomp, add it to the `ALLOW` block in `seccomp.cfg`:

```protobuf
ALLOW {
    # ... existing syscalls ...
    my_new_syscall,
}
```

### Adding Mount Points

If tests need access to additional paths:

```protobuf
mount {
    src: "/path/on/host"
    dst: "/path/in/jail"
    is_bind: true
    rw: false  # Set to true if write access needed
}
```

### Adjusting Resource Limits

```protobuf
# Increase memory limit to 4GB
rlimit_as: 4096

# Allow more processes (for parallel tests)
rlimit_nproc: 256

# Allow more open files
rlimit_nofile: 512
```

## Runtime Overrides

The following are set dynamically by `entrypoint.sh`:

| Flag | Purpose |
|------|---------|
| `--config <path>` | Select base.cfg or seccomp.cfg |
| `--user <uid>` | Run as specified user |
| `--group <gid>` | Run as specified group |
| `--cwd <path>` | Working directory |
| `--time_limit <sec>` | Timeout (from `DK_TIMEOUT`) |
| `--bindmount <src>:<dst>` | Mount repo directory (read-write) |
| `--bindmount_ro <src>:<dst>` | Mount harness directory (read-only) |
| `--env <VAR>=<val>` | Pass environment variables |
| `--disable_clone_newnet` | Enable host network (when `network: bridge`) |

## Troubleshooting

### "Operation not permitted" errors

**Cause:** Seccomp is blocking a required syscall.

**Solution:**
1. Run with `sandbox: nsjail` (no seccomp) to confirm
2. Identify the blocked syscall using `strace`
3. Add it to the `ALLOW` block in `seccomp.cfg`

### "Permission denied" on file access

**Cause:** File/directory not mounted or mounted read-only.

**Solution:**
1. Check if the path is included in `mount {}` blocks
2. Verify `rw: true` if write access is needed
3. Check `mandatory: true/false` setting

### nsjail fails to start

**Cause:** Missing kernel features or capabilities.

**Solution:**
1. Ensure Docker is run with `--cap-add SYS_ADMIN --cap-add SYS_PTRACE`
2. Check kernel supports user namespaces: `cat /proc/sys/kernel/unprivileged_userns_clone`
3. Verify kernel version is 4.6+ for full namespace support

### Tests hang inside jail

**Cause:** Time limit not being enforced.

**Solution:**
1. Check `--time_limit` is being passed
2. Verify `rlimit_cpu` in config file
3. Container-level timeout should catch runaways

### Network not working (when expected)

**Cause:** Network namespace is isolating the jail.

**Solution:**
1. Set `network: bridge` in manifest
2. This passes `--disable_clone_newnet` to nsjail

## Security Considerations

### What nsjail Protects Against

1. **Filesystem tampering:** Read-only mounts prevent modification of system files
2. **Process snooping:** PID namespace hides other processes
3. **Network exfiltration:** Network namespace blocks unauthorized connections
4. **Resource exhaustion:** rlimits cap memory, CPU, and file descriptors
5. **Privilege escalation:** Capabilities are dropped, seccomp blocks dangerous syscalls
6. **Information leaks:** UTS namespace hides real hostname

### What nsjail Does NOT Protect Against

1. **Kernel exploits:** A kernel vulnerability could escape the jail
2. **Side-channel attacks:** Timing/cache attacks are not prevented
3. **Covert channels:** Shared CPU resources could leak information
4. **Resource exhaustion at Docker level:** Use Docker's `--memory` and `--cpus` flags

### Defense in Depth

dk_autotester uses multiple layers:

```
┌─────────────────────────────────────────────┐
│  Docker Container                           │
│  ├── Resource limits (--memory, --cpus)     │
│  ├── Network isolation (--network none)     │
│  │                                          │
│  │  ┌───────────────────────────────────┐   │
│  │  │  nsjail Sandbox                   │   │
│  │  │  ├── Namespace isolation          │   │
│  │  │  ├── Seccomp filtering (optional) │   │
│  │  │  ├── Resource limits (rlimits)    │   │
│  │  │  │                                │   │
│  │  │  │  ┌─────────────────────────┐   │   │
│  │  │  │  │  Unprivileged User      │   │   │
│  │  │  │  │  (dk_0, dk_1, ...)      │   │   │
│  │  │  │  │  ├── Private HOME       │   │   │
│  │  │  │  │  └── chmod 700          │   │   │
│  │  │  │  └─────────────────────────┘   │   │
│  │  └───────────────────────────────────┘   │
│  └──────────────────────────────────────────┘
└─────────────────────────────────────────────┘
```

## Examples

### Minimal manifest with nsjail

```yaml
language: node
test_script: ./harness/run_tests.sh
sandbox: nsjail
network: none

sources:
  - name: my-project
    description: "Test project"
    path: ./projects/my-project
```

### Maximum security with seccomp

```yaml
language: node
test_script: ./harness/run_tests.sh
sandbox: nsjail-seccomp
network: none
timeout_seconds: 300

resources:
  memory: 1g
  cpus: "1"
  pids_limit: 64

sources:
  - name: untrusted-submission
    description: "Student submission"
    url: git@github.com:student/assignment.git
```

### Allow network access for integration tests

```yaml
language: python
test_script: ./harness/integration_tests.sh
sandbox: nsjail
network: bridge

sources:
  - name: api-service
    description: "API with external dependencies"
    path: ./services/api
```

## References

- [nsjail GitHub](https://github.com/google/nsjail)
- [nsjail Documentation](https://github.com/google/nsjail/blob/master/README.md)
- [Kafel (Seccomp Policy Language)](https://github.com/google/kafel)
- [Linux Namespaces](https://man7.org/linux/man-pages/man7/namespaces.7.html)
- [Seccomp BPF](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)
