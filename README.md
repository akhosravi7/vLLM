# Local model servers on Bazzite

This workspace contains three OpenAI-compatible model servers for the RTX 5090:

| Server | Local API | Model ID |
| --- | --- | --- |
| llama-server (rootless Podman) | `http://127.0.0.1:8080/v1` | `laguna-xs-2.1` |
| vLLM (hardened system service) | `http://127.0.0.1:8000/v1` | `Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| Speaches ASR (rootless Podman) | `http://127.0.0.1:8001/v1` | `kotoba-tech/kotoba-whisper-v2.0-faster` |

Only one GPU-backed server runs at a time.

## Model manager (current)

All GGUF chat models, including the former LM Studio downloads, are now driven
by `model-manager/`. It runs as the `local-model-manager.service` systemd user
service, keeps the selected model on `127.0.0.1:8002`, and exposes a small
token-protected API on `127.0.0.1:8010`:

```bash
systemctl --user status local-model-manager.service
TOKEN=$(sed -n 's/^MODEL_MANAGER_TOKEN=//p' model-manager/model-manager.env)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8010/models
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"id":"qwen2.5-7b-fast"}' http://127.0.0.1:8010/switch
curl -H "Authorization: Bearer $TOKEN" -X POST http://127.0.0.1:8010/restore-japanese
```

The catalog is `model-manager/models.json`. The manager does not touch Tailscale;
the chat PWA keeps the root route and proxies model switches through this API.
`model-manager` autostarts Japanese mode when no GPU workload is running, so
Japanese ASR + translation remain the default.

`local-searxng.service` runs `searxng/` on `127.0.0.1:8888` for the chat app's
optional web search. The old `switch-model`, `japanese-mode`, and `lagunactl`
workflows remain for manual use but reset the Tailscale route table.


## Switching servers and Tailscale

Run these commands from `/var/home/ali/vLLM`:

```bash
# Stop the other GPU servers, start the selected one, wait for health,
# then point the Tailscale route at it.
./switch-model asr
./switch-model vllm
./switch-model laguna

# Inspect the current route and running containers
./switch-model status
```

`switch-model` uses the existing passwordless `vllmctl` helper for the system
vLLM service. The older manual sequence is still available:

```bash
# Laguna
vllmctl stop
./laguna/lagunactl start
./tailscale-model laguna

# vLLM
./laguna/lagunactl stop
vllmctl start
./tailscale-model vllm

# ASR
vllmctl stop
./laguna/lagunactl stop
./kotoba/kotoba-asrctl start
./tailscale-model asr
```

`tailscale-model` changes only the route and refuses to switch to an unhealthy
server. Stop one GPU server before starting another. The three single-server
routes share the private Tailscale API URL `https://alibazz.tailf4ff3b.ts.net/v1`;
clients must select the model ID appropriate to the active server. When Laguna is
selected, its web UI is at `https://alibazz.tailf4ff3b.ts.net`. When ASR is
selected, use `/v1/audio/transcriptions` on that base URL.

Japanese mode uses `./tailscale-model japanese`: ASR stays at the root, while
`/v1/models` and `/v1/chat/completions` are routed to the translation server.
That makes chat clients such as Reins discover `qwen2.5-7b-instruct` while
transcription keeps working on the same base URL.

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

## Japanese transcription

The ASR server is [Speaches](https://speaches.ai/) running the CTranslate2 build
of [kotoba-whisper-v2.0](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0-faster)
through rootless Podman. It is GPU-backed and uses the same switch flow:

```bash
./switch-model asr
./kotoba/transcribe --text recording.m4a
./kotoba/transcribe recording.m4a | jq -r .text
```

`transcribe` defaults to `language=ja`. Use
`./kotoba/transcribe AUDIO LANG` for another language. The OpenAI-compatible
endpoint is:

```bash
curl --fail http://127.0.0.1:8001/v1/audio/transcriptions \
  -F file=@recording.m4a \
  -F model=kotoba-tech/kotoba-whisper-v2.0-faster \
  -F language=ja \
  -F response_format=verbose_json
```

The container is named `kotoba-asr`, listens on `127.0.0.1:8001`, and is
controlled with:

```bash
./kotoba/kotoba-asrctl start
./kotoba/kotoba-asrctl status
./kotoba/kotoba-asrctl logs
./kotoba/kotoba-asrctl stop
```

The model is downloaded on first start into the `kotoba-hf-cache` Podman volume.
Remove it with `podman volume rm kotoba-hf-cache` to reclaim the space or force a
fresh download. The image is pinned by digest in `kotoba/kotoba-asrctl`. It uses
`WHISPER__COMPUTE_TYPE=float16` because CTranslate2's int8 CUDA kernels do not
work on RTX 50-series cards; the ONNX voice-activity detector is forced to CPU
because its CUDA provider can crash on this host.

## Japanese mode (ASR + translation together)

`japanese-mode` runs the ASR server and a separate translation LLM at the same
time. It does not touch the hardened vLLM service or `vllm.env`.

```bash
./japanese/japanese-mode          # start both and select the Tailscale route
./tailscale-model japanese        # re-select the route without restarting
./japanese/japanese-mode status
./japanese/japanese-mode logs     # translation model logs
./japanese/japanese-mode asr-logs # ASR logs
./japanese/japanese-mode stop
```

The translation model is
[Qwen2.5-32B-Instruct Q5_K_M](https://huggingface.co/bartowski/Qwen2.5-32B-Instruct-GGUF)
served by rootless Podman llama.cpp, the same pinned image as Laguna. On first
start it downloads to `models/qwen2.5-32b-instruct/`. The served model ID stays
`qwen2.5-7b-instruct` for compatibility with existing clients. Both endpoints
are OpenAI-compatible:

- Transcription: `http://127.0.0.1:8001/v1/audio/transcriptions`
- Translation: `http://127.0.0.1:8002/v1/chat/completions`, served as
  `qwen2.5-7b-instruct`

`japanese-mode` points the Tailscale route at Speaches (port 8001) so ASR works,
and adds `/v1/models` and `/v1/chat/completions` routes to the translation server
(port 8002). Clients such as Reins that discover models via `/v1/models` therefore
see `qwen2.5-7b-instruct`, while transcription stays on the same base URL.
Speaches also proxies `/v1/chat/completions` to the translation server using
`CHAT_COMPLETION_BASE_URL` (default `http://127.0.0.1:8002/v1`), which remains the
fallback for clients that post through the root route:

In Reins, add an OpenAI-compatible server with base URL
`https://alibazz.tailf4ff3b.ts.net/v1` and no API key. The app discovers
`qwen2.5-7b-instruct` from `/v1/models`.

```bash
# Transcription and translation through the tailnet endpoint
curl --fail https://alibazz.tailf4ff3b.ts.net/v1/audio/transcriptions ...
curl --fail https://alibazz.tailf4ff3b.ts.net/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-7b-instruct","messages":[{"role":"user","content":"Translate to English. Reply with only the translation:\nこんにちは。"}],"max_tokens":256,"temperature":0.2}'
```

Example translation request after transcription:

```bash
curl --fail http://127.0.0.1:8002/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-7b-instruct",
    "messages": [{"role": "user", "content": "Translate to English. Reply with only the translation:\nこんにちは。"}],
    "max_tokens": 256,
    "temperature": 0.2
  }'
```

The same model can act as a tutor, using the surrounding context and breaking
down grammar and nuance:

```bash
curl --fail http://127.0.0.1:8002/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-7b-instruct",
    "messages": [{"role": "user", "content": "Act as a Japanese tutor. Translate this sentence, then break down the main grammar points and nuance:\n雨が降りそうだから、傘を持っていったほうがいいよ。"}],
    "max_tokens": 700,
    "temperature": 0.3
  }'
```

It uses about 25 GiB of VRAM with ASR running, leaving roughly 6 GiB free.

Japanese mode is independent of `switch-model`; run it directly. It will fail
cleanly if another GPU server is holding the memory, so stop vLLM first with
`vllmctl stop`.

## Model files

The current Qwen3-Coder checkpoint lives directly in `models/`. Laguna weights
live separately in `models/laguna-xs-2.1-poolside/`. For vLLM, place a complete
Hugging Face checkpoint directly in `models/`.
At minimum, this normally includes `config.json`, tokenizer files, and every
file referenced by `model.safetensors.index.json`. The directory is excluded
from Git and mounted read-only inside the container. The ASR weights are not in
`models/`; Speaches keeps them in the `kotoba-hf-cache` Podman volume. The
Japanese-mode translation weights live in `models/qwen2.5-32b-instruct/`.

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

These settings apply only to the vLLM service. The ASR service is configured
directly in `kotoba/kotoba-asrctl`; it does not use `vllm.env` or the hardened
vLLM deployment.

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
