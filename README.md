# Local model servers on Bazzite

This workspace contains two OpenAI-compatible model servers for the RTX 5090:

| Server | Local API | Model ID |
| --- | --- | --- |
| llama-server (rootless Podman) | `http://127.0.0.1:8080/v1` | `laguna-xs-2.1` |
| vLLM (hardened system service) | `http://127.0.0.1:8000/v1` | `Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |

As of 2026-09-07, Laguna XS 2.1 Q4_K_M is running and selected through
Tailscale. See [Laguna setup and validation](laguna/README.md) for pinned
model/image downloads, GPU settings, and start/stop commands.

## Switching servers and Tailscale

Run these commands from `/var/home/ali/vLLM`:

```bash
# Switch the running model to Laguna
vllmctl stop
./laguna/lagunactl start
# Once the model is ready:
./tailscale-model laguna

# Or switch the running model to vLLM
./laguna/lagunactl stop
vllmctl start
# Once the model is ready:
./tailscale-model vllm

# Inspect the current route
./tailscale-model status
```

`tailscale-model` changes only the route and refuses to switch to an unhealthy
server. Stop one GPU server before starting the other. Both share the private
Tailscale API URL `https://alibazz.tailf4ff3b.ts.net/v1`; clients must select the
model ID appropriate to the active server. When Laguna is selected, its web UI
is at `https://alibazz.tailf4ff3b.ts.net`.

Laguna starts manually and does not start at boot. vLLM's existing enabled boot
setting was left unchanged. Tailscale retains its selected route across restarts;
that route works only while the selected backend is running.

## vLLM deployment

vLLM uses `vllm/vllm-openai:v0.28.0` through a privilege-separated systemd
installation. Service definitions and the private Docker toolchain are
root-owned; `ali` can edit model files and validated configuration. Local
configuration currently selects `qwen3_xml` for tool parsing. vLLM was stopped
and was not revalidated during the Laguna session. See
[client setup](OPENCODE_SETUP.md) for validation limits.

## Model files

The current Qwen3-Coder checkpoint lives directly in `models/`. Laguna weights
live separately in `models/laguna-xs-2.1-poolside/`. For vLLM, place a complete
Hugging Face checkpoint directly in `models/`.
At minimum, this normally includes `config.json`, tokenizer files, and every
file referenced by `model.safetensors.index.json`. The directory is excluded
from Git and mounted read-only inside the container.

## Day-to-day operation on the hardened host

Use the installed helper; do not run the repository's Compose definition or a
Docker client with sudo:

```bash
vllmctl start
vllmctl stop
vllmctl restart
vllmctl status
vllmctl logs
vllmctl logs -n 100
```

Allow time for model loading, then verify the local endpoint. The tailnet
health check applies to whichever backend `tailscale-model status` reports:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models
curl --fail https://alibazz.tailf4ff3b.ts.net/health
```

The OpenAI-compatible base URLs are:

- Local: `http://127.0.0.1:8000/v1`
- Tailnet: `https://alibazz.tailf4ff3b.ts.net/v1`

Send a minimal chat request locally:

```bash
curl --fail http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
    "messages": [{"role": "user", "content": "Reply with: hello"}],
    "max_tokens": 32
  }'
```

## Configuration

The live configuration is `vllm.env`. It is local-only, mode `0600`, and is
parsed as data rather than sourced as shell. Start from the documented example:

```bash
cp deploy/vllm.env.example vllm.env
chmod 0600 vllm.env
```

Accepted settings are:

- `SERVED_MODEL_NAME`
- `MAX_MODEL_LEN`
- `GPU_MEMORY_UTILIZATION`
- `TENSOR_PARALLEL_SIZE`
- `PIPELINE_PARALLEL_SIZE`
- `REASONING_PARSER`
- `TOKENIZER_MODE`
- `DTYPE`
- `LOAD_FORMAT`
- `KV_CACHE_DTYPE`
- `SEED`
- `RENDERER_NUM_WORKERS`
- `MAX_NUM_SEQS`
- `MAX_NUM_BATCHED_TOKENS`
- `CPU_OFFLOAD_GB`
- `SCHEDULING_POLICY`
- `UVICORN_LOG_LEVEL`
- `MAX_LOGPROBS`
- `OPTIMIZATION_LEVEL`
- `PERFORMANCE_MODE`

Set `REASONING_PARSER=none` for models such as Qwen2.5 that do not emit a
separate reasoning stream. Named parsers remain strictly allowlisted. Changing
this setting requires only `vllmctl restart` after the deployment has been
installed; no administrator session is needed.

Unknown keys, duplicate keys, whitespace-containing values, unsafe modes,
symlinks, and out-of-range values are rejected during service startup. There is
no arbitrary extra-arguments setting. Options that can change networking,
authentication, filesystem access, executable or plugin loading, remote-code
trust, or arbitrary JSON configuration remain fixed in the root-owned
deployment. After editing the file, apply it with:

```bash
vllmctl restart
```

The local vLLM configuration sets a 30,000-token limit. Historical KV-cache
measurements in the handoff notes apply to the checkpoints tested at that time;
they were not remeasured for the current Qwen3-Coder checkpoint in this session.

If startup fails because the model does not fit, first reduce `MAX_MODEL_LEN`.
Review the error with `vllmctl logs -n 200`.

## Hardened deployment files

The files under `deploy/` are reviewable staging sources for the installed
root-owned configuration. They are never executed directly by systemd.

An administrator must copy them to a new root-only staging directory, review
that immutable copy, and run the copied installer. Never run the user-writable
`deploy/install.sh` directly with sudo. See
[deploy/README-install.md](deploy/README-install.md) for the trust-boundary
details and [RESUME-HARDENING.md](RESUME-HARDENING.md) for the verified
installation, ownership table, administrator commands, and rollback procedure.

The deployment is host-specific. In particular, the installer currently
expects user `ali` with uid 1000, project path `/var/home/ali/vLLM`, the Bazzite
Homebrew Docker packages, and the NVIDIA Container Toolkit runtime.

Direct Docker access is intentionally unavailable to `ali` on the hardened
host. The named `vllm-cache` volume is retained across normal container removal.
