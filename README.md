# Qwen2.5-Coder-32B-Instruct-AWQ with vLLM

This repository serves a local Qwen2.5-Coder-32B-Instruct-AWQ checkpoint through vLLM's
OpenAI-compatible API. On the deployed Bazzite host, vLLM runs through a
privilege-separated systemd installation: service definitions and the private
Docker toolchain are root-owned, while the everyday `ali` account can edit only
the model files and a strictly validated configuration.

The deployment is pinned to `vllm/vllm-openai:v0.28.0`. Automatic tool calling
is enabled with the Hermes parser. The current Qwen2.5 checkpoint emits textual
`<tools>` blocks that Hermes does not convert into structured `tool_calls`; see
`OPENCODE_SETUP.md` before relying on agent use.

The API listens on `127.0.0.1:8000` without an API key. Tailscale Serve exposes
that loopback endpoint privately to the tailnet.

## Model files

Place one complete Qwen2.5-Coder-32B-Instruct-AWQ Hugging Face checkpoint directly in `models/`.
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

Startup takes about two minutes for the current five-shard checkpoint. Verify
the local and tailnet endpoints with:

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
    "model": "Qwen2.5-Coder-32B-Instruct-AWQ",
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

The live limit is 30,000 tokens. With vLLM 0.28.0, the current Qwen2.5 Coder
checkpoint and 32 GiB RTX 5090 measured a 33,488-token FP16 KV cache, so this
limit uses most of the available context capacity while retaining about 10.4%
headroom. `MAX_NUM_BATCHED_TOKENS` may remain lower: it controls scheduler
prefill work per iteration, not the maximum context accepted by the API.

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
