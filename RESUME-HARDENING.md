# vLLM privilege-separation handoff

Updated: 2026-09-04, America/Chicago

## 2026-09-04 vLLM and OpenCode update

The root-owned deployment was updated through a reviewed `guardian` staging
snapshot from vLLM 0.26.0 to `vllm/vllm-openai:v0.28.0`. The current service
reports `system_fingerprint: vllm-0.28.0-4495fb3e`.

Automatic tool choice is enabled with the fixed arguments
`--enable-auto-tool-choice --tool-call-parser hermes`; Qwen3 reasoning parsing
remains `qwen3`. Local verification passed for `/health`, `/v1/models`, an
ordinary chat completion, and a real `tool_choice: "auto"` request. The tool
test returned a structured call with valid JSON arguments and
`finish_reason: "tool_calls"`. The model remains `Qwen3-32B-AWQ` with maximum
model length 8192.

The validated user configuration was expanded with conservative settings for
pipeline parallelism, tokenizer and load modes, seed, renderer workers,
scheduling, logging, logprob limits, optimization level, and performance mode.
Networking, authentication, filesystem paths, plugins, remote-code trust, and
arbitrary JSON/extra arguments remain unavailable to `ali`.

The permission boundary behaved as designed: `ali` could change repository
staging files and restart the service, but could not overwrite
`/etc/vllm/compose.yaml`. Changes to root-owned deployment files still require
review and installation by `guardian`.

## Session closure

Hardening and post-login verification are complete. At the final check,
`vllm.service` and `vllm-docker.service` were active, and both the local and
Tailscale health endpoints returned HTTP 200. No further security work is
pending from this session.

The repository was reduced to the hardened deployment sources and Markdown
documentation. The final cleanup removes the unused tracked `.env.example`,
root-level `compose.yaml`, and `start-vllm.sh`, and updates `.gitignore`, this
handoff, and `README.md`. These cleanup changes are intentionally left in the
working tree for review and commit; the last existing commit is `aa5fc03`
(`Update hardening`). The live `vllm.env` and `models/` remain ignored local
runtime data and must not be committed.

## Goal

Run vLLM through root-owned systemd and Docker definitions while `ali` remains
an unprivileged everyday account. `ali` may edit only model files and a strictly
validated vLLM configuration, and may start/stop/restart only `vllm.service`.

## Current state

- A separate administrator account named `guardian` was created and its sudo
  access was verified with `sudo id` returning uid 0.
- `ali` was removed from `wheel`.
- `getent group wheel` returned `wheel:x:10:guardian`.
- A complete sign-out/sign-in was performed. The fresh session has no stale
  supplementary `wheel` or `docker` membership.
- Do not enter or record either account password in this file.

## Installed design

- `/etc/vllm/compose.yaml`: root-owned fixed Compose definition.
- `/etc/systemd/system/vllm.service`: root-owned vLLM Compose service.
- `/etc/systemd/system/vllm-docker.service`: root-owned dedicated Docker daemon.
- `/etc/sudoers.d/vllm`: only passwordless start, stop, and restart of
  `vllm.service` using exact `/usr/bin/systemctl` commands.
- `/usr/local/bin/vllmctl`: day-to-day helper.
- `/usr/local/bin/vllm-validate-config`: strict parser; does not source shell.
- `/usr/local/bin/vllm-docker/`: root-owned private Docker toolchain.
- `/usr/local/lib/vllm-runc/`: root-owned runc libraries.
- `/var/home/ali/vLLM/vllm.env`: `ali:ali`, mode 0600, safe settings only.
- `/var/home/ali/vLLM/models`: `ali`-owned model files, mounted read-only.
- `/var/log/vllm/vllm.log`: `root:ali`, mode 0640.
- `/run/docker.sock`: `root:root`, mode 0660 while daemon is running.

The copied Homebrew ELF executables were rewritten so their ELF interpreter,
RPATH, and RUNPATH do not load from `ali`-writable Homebrew paths. The installed
`runc` uses `/usr/local/lib/vllm-runc`. Static checks passed for all nine copied
executables.

Obsolete `/opt/vllm` and `/usr/local/libexec/vllm` copies were moved to:

`/var/backups/vllm/obsolete-20260902/`

## Verified functionality

- Both `vllm-docker.service` and `vllm.service` reached active/running.
- Dedicated Docker socket was `0660 root:root` and direct Docker access by
  `ali` was denied.
- NVIDIA runtime created the container successfully.
- Existing four-shard Qwen3 AWQ checkpoint loaded successfully.
- vLLM 0.26.0 used the RTX 5090 and allocated about 28.6 GiB.
- `GET http://127.0.0.1:8000/health` returned HTTP 200.
- `GET http://127.0.0.1:8000/v1/models` returned `Qwen3-32B-AWQ`, max length
  8192.
- `GET https://alibazz.tailf4ff3b.ts.net/health` returned HTTP 200.
- Tailscale Serve remains persistently configured to proxy to
  `http://127.0.0.1:8000`.
- `vllmctl restart` succeeded, changed the systemd invocation, reloaded the
  model, and returned to healthy state.
- `hf --version` returned 1.26.0.
- Systemd and Compose syntax validation passed.
- Validator tests rejected command substitution, symlinks, and unsafe modes.

`--swap-space` was removed because vLLM 0.26.0 rejects that option.

## Final post-login verification

Completed 2026-09-02 after a full fresh login as `ali`.

- `id` returned only `uid=1000(ali) gid=1000(ali) groups=1000(ali)`.
- `sudo -n -l` listed only the exact `start`, `stop`, and `restart` commands for
  `vllm.service` shown below. It did not list `(ALL) ALL`.
- Arbitrary `id`, `daemon-reload`, control of `vllm-docker.service`, and an
  allowed command with an extra argument were all rejected by sudo.
- The private Docker client and a direct HTTP request to `/run/docker.sock`
  were denied. The live socket was `0660 root:root`.
- `vllmctl status` and a bounded `vllmctl logs -n 5` worked without sudo.
- `vllmctl stop` made the unit inactive and the endpoint unreachable.
- `vllmctl start` made the unit active and returned the model to health after
  about two minutes.
- `vllmctl restart` changed the systemd invocation ID and returned the model to
  health after about 130 seconds.
- Final local health and Tailscale health both returned HTTP 200.
- `/v1/models` reported `Qwen3-32B-AWQ` with `max_model_len` 8192.
- `nvidia-smi` reported `VLLM::EngineCore` using 29,578 MiB.
- Both `vllm.service` and `vllm-docker.service` were active at handoff.
- The installed Compose file, both units, validator, and helper were byte-for-
  byte identical to their reviewed `deploy/` staging files.
- All nine private Docker ELF executables had no interpreter, RPATH, or RUNPATH
  referring to `/home/linuxbrew`.
- Compose validation resolved the fixed image, loopback-only port, read-only
  model bind mount, named cache, and only the then-current ten validated
  settings. The allowlist was expanded in the 2026-09-04 update above.
- Validator tests rejected command substitution, unknown keys, duplicate keys,
  whitespace, out-of-range values, group/world-writable input, and symlinks.
  Valid input produced a mode 0600 output file.
- Systemd and Compose syntax checks passed. The root-owned PATH components and
  `/etc/docker/daemon.json` were also checked.

## Canonical installed content

The human-readable canonical copies are:

- `deploy/compose.yaml`
- `deploy/vllm.service`
- `deploy/vllm-docker.service`
- `deploy/vllm.sudoers`
- `deploy/vllmctl`
- `deploy/validate-config.py`
- `deploy/patch-runc-rpath.py`
- `deploy/vllm.logrotate`

The security-sensitive installed copies are root-owned and must be reviewed
and changed only by `guardian`. The live sudoers content is exactly:

```sudoers
ali ALL=(root) NOPASSWD: /usr/bin/systemctl start vllm.service, /usr/bin/systemctl stop vllm.service, /usr/bin/systemctl restart vllm.service
```

The live `vllm.env` values are intentionally not duplicated here. Its accepted
keys and defaults are documented in `deploy/vllm.env.example`.

## Ownership and modes

| Path | Owner | Mode |
| --- | --- | --- |
| `/etc/vllm` | `root:root` | `0755` |
| `/etc/vllm/compose.yaml` | `root:root` | `0644` |
| `/etc/systemd/system/vllm*.service` | `root:root` | `0644` |
| `/etc/sudoers.d/vllm` | `root:root` | `0440` |
| `/etc/docker/daemon.json` | `root:root` | `0644` |
| `/usr/local/bin/vllmctl` | `root:root` | `0755` |
| `/usr/local/bin/vllm-validate-config` | `root:root` | `0755` |
| `/usr/local/bin/vllm-docker/` and executables | `root:root` | `0755` |
| `/usr/local/lib/vllm-runc/` | `root:root` | `0755` |
| `/usr/local/lib/vllm-runc/*.so.*` | `root:root` | `0644` |
| `/var/home/ali/vLLM/vllm.env` | `ali:ali` | `0600` |
| `/var/home/ali/vLLM/models` | `ali:ali` | `0755` |
| `/var/log/vllm` | `root:ali` | `0750` |
| `/var/log/vllm/vllm.log` | `root:ali` | `0640` |
| `/run/docker.sock` while running | `root:root` | `0660` |

## Day-to-day commands for `ali`

```bash
vllmctl start
vllmctl stop
vllmctl restart
vllmctl status
vllmctl logs
vllmctl logs -n 100
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models
curl --fail https://alibazz.tailf4ff3b.ts.net/health
```

Edit only `vllm.env` and model files. A bad configuration is rejected during
start/restart without being interpreted as shell. Startup normally takes about
two minutes for the current checkpoint.

## Administrator commands for `guardian`

```bash
sudo systemctl status vllm.service vllm-docker.service
sudo systemctl restart vllm.service
sudo journalctl -u vllm.service -u vllm-docker.service
sudo visudo -cf /etc/sudoers.d/vllm
sudo systemd-analyze verify /etc/systemd/system/vllm.service /etc/systemd/system/vllm-docker.service
```

To install reviewed changes, copy `deploy/` to a new root-only staging
directory, review that immutable copy, and run its installer. Never run the
user-writable `deploy/install.sh` directly with sudo.

## Rollback procedure for `guardian`

Rollback requires an authenticated `guardian` session. First stop and disable
the service pair:

```bash
sudo systemctl stop vllm.service vllm-docker.service
sudo systemctl disable vllm.service vllm-docker.service
```

Then move these installed definitions and helpers into a new root-only backup
directory rather than deleting them:

```text
/etc/vllm/
/etc/systemd/system/vllm.service
/etc/systemd/system/vllm-docker.service
/etc/sudoers.d/vllm
/etc/logrotate.d/vllm
/usr/local/bin/vllmctl
/usr/local/bin/vllm-validate-config
/usr/local/bin/vllm-patch-runc-rpath
/usr/local/bin/vllm-docker/
/usr/local/lib/vllm-runc/
/usr/local/lib/vllm-runtime/
```

Run `sudo systemctl daemon-reload` afterward. Preserve `models/`, `vllm.env`,
`/var/log/vllm/`, and Docker volumes unless data deletion is explicitly wanted.
The obsolete pre-hardening installation is preserved at
`/var/backups/vllm/obsolete-20260902/`; review it before restoring anything.
Tailscale Serve is persistent and independent of these units, so remove or
change it separately only if the private endpoint itself should be retired.

## Staged source files

The user-writable staging files are under `/var/home/ali/vLLM/deploy/`. They are
not executed by systemd. Guardian installation used a root-owned reviewed copy
under `/root/vllm-install-staging/`.

The unused root-level `compose.yaml`, `.env.example`, and `start-vllm.sh` legacy
files were removed after verification. The hardened deployment sources live
only under `deploy/`.
