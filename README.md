# Qwen3-32B-AWQ with vLLM

This repository serves a local Qwen3-32B-AWQ checkpoint through vLLM's
OpenAI-compatible API. On the deployed Bazzite host, vLLM runs through a
privilege-separated systemd installation: service definitions and the private
Docker toolchain are root-owned, while the everyday `ali` account can edit only
the model files and a strictly validated configuration.

The API listens on `127.0.0.1:8000` without an API key. Tailscale Serve exposes
that loopback endpoint privately to the tailnet.

## Model files

Place one complete Qwen3-32B-AWQ Hugging Face checkpoint directly in `models/`.
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

Startup takes about two minutes for the current four-shard checkpoint. Verify
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
    "model": "Qwen3-32B-AWQ",
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
- `REASONING_PARSER`
- `DTYPE`
- `KV_CACHE_DTYPE`
- `MAX_NUM_SEQS`
- `MAX_NUM_BATCHED_TOKENS`
- `CPU_OFFLOAD_GB`

Unknown keys, duplicate keys, whitespace-containing values, unsafe modes,
symlinks, and out-of-range values are rejected during service startup. There is
no arbitrary extra-arguments setting. After editing the file, apply it with:

```bash
vllmctl restart
```

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
