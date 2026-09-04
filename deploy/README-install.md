# Hardened vLLM service installation

The files in this directory are staging copies. The administrator must first
copy them to a root-only staging directory, review that immutable snapshot, and
run the installer from there. Never execute this user-writable installer as
root, and never configure a root service to execute these staging files.

The dedicated Docker daemon remains a root service and its socket is explicitly
owned by `root:root`. `ali` is not added to a Docker group. The vLLM service is
the only Compose client in normal operation.

The installer copies the known-working Homebrew `runc` and its two private
libraries, then rewrites its embedded RPATH to `/usr/local/lib/vllm-runc`. It
aborts if a Homebrew library path remains, so the daemon never executes or
loads code from an `ali`-writable Homebrew directory after installation.

`vllm.env` is parsed by a strict Python parser. It is not sourced. Unknown keys,
duplicates, whitespace, shell metacharacters outside the served-name grammar,
symlinks, unexpected ownership, and group/world-writable modes are rejected.
There is deliberately no arbitrary `EXTRA_ARGS` setting. Common low-risk
numeric and enum options are exposed through the allowlist documented in the
top-level README. Networking, authentication, filesystem paths, executable or
plugin loading, remote-code trust, and arbitrary JSON configuration remain
fixed in the root-owned deployment.

The root-owned `vllm-entrypoint` maps `REASONING_PARSER=none` to an omitted
vLLM argument and maps each other allowlisted value to exactly one
`--reasoning-parser` argument. It never evaluates configuration as shell code.

Before installation, the installer makes timestamped backups of every
destination that exists. The verified installation, ownership table, operating
commands, and rollback procedure are documented in `../RESUME-HARDENING.md`.
