# Laguna XS 2.1 with llama-server on Bazzite

This setup runs the official llama.cpp CUDA 13 server image through rootless
Podman on the RTX 5090. No changes to the immutable operating system are needed.

## Operation

From `/var/home/ali/vLLM`:

```bash
./laguna/lagunactl start
./laguna/lagunactl status
./laguna/lagunactl logs
./laguna/lagunactl stop
```

Open the web UI at http://127.0.0.1:8080.
The OpenAI-compatible base URL is `http://127.0.0.1:8080/v1` and the model ID is
`laguna-xs-2.1`. No API key is configured; clients requiring a nonempty key can
use `local`. The published port is bound to localhost only.

## Switch Tailscale

From `/var/home/ali/vLLM`:

```bash
./tailscale-model laguna
./tailscale-model vllm
./tailscale-model status
```

The helper switches the private HTTPS route after checking the selected server's
health. It does not start or stop servers. Both use the same API base URL:
`https://alibazz.tailf4ff3b.ts.net/v1`. For Laguna, the web UI is available at
`https://alibazz.tailf4ff3b.ts.net`.

To change the running server as well:

```bash
# Switch to Laguna
vllmctl stop
./laguna/lagunactl start
# Wait for /health to report ready, then:
./tailscale-model laguna

# Switch to vLLM
./laguna/lagunactl stop
vllmctl start
# Wait for vLLM to finish loading, then:
./tailscale-model vllm
```

## API example

```bash
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"laguna-xs-2.1","messages":[{"role":"user","content":"Write a Python function that checks whether a number is prime."}],"max_tokens":1024}'
```

Reasoning uses the model's embedded Jinja template. Thinking is off by default
in this template. Enable it per request with
`"chat_template_kwargs":{"enable_thinking":true}`; use `false` to disable it.
Thinking can consume the entire output budget before a final answer appears.

The starting configuration uses 32,768 context tokens, one request slot, full
GPU offload, flash attention, and the default FP16 KV cache. Sampling defaults
match Poolside's recipe: temperature 1.0, top-k 20, top-p 1.0; min-p is disabled.

Stop Laguna before starting vLLM or a game that needs substantial VRAM.
This Laguna container starts on demand and does not start automatically after
reboot. The existing vLLM service uses port 8000 and retains its current boot setting.
If vLLM is running, use `vllmctl stop` before starting Laguna.

`restart` restarts the existing container with its original arguments. To apply
edits to `lagunactl`, stop it, run `podman rm llama-laguna`, then start it again.
Removing this stopped container preserves the model weights.

## Pinned downloads

- Model: [poolside/Laguna-XS-2.1-GGUF](https://huggingface.co/poolside/Laguna-XS-2.1-GGUF)
- Revision: `1a37c0a5fb8c7a18e6106decb6be6327d1b63fa6`
- File: `models/laguna-xs-2.1-poolside/Laguna-XS-2.1-Q4_K_M.gguf`
- Size: 20,274,300,032 bytes
- SHA-256: `1ac7079101fca5a6df8c5a7523a3c30ea7d1c0e4b1258090e7d6d4039287f6cb`
- CUDA 13 image: `ghcr.io/ggml-org/llama.cpp@sha256:a77f3bea9d62f6187ebb6ca8deb1a03aebeeb1ed7a832ac94663ff5c7815da63`

To restore the pinned image and download the model again:

```bash
podman pull ghcr.io/ggml-org/llama.cpp@sha256:a77f3bea9d62f6187ebb6ca8deb1a03aebeeb1ed7a832ac94663ff5c7815da63
HF_XET_HIGH_PERFORMANCE=1 hf download poolside/Laguna-XS-2.1-GGUF \
  Laguna-XS-2.1-Q4_K_M.gguf \
  --revision 1a37c0a5fb8c7a18e6106decb6be6327d1b63fa6 \
  --local-dir /var/home/ali/vLLM/models/laguna-xs-2.1-poolside
```

References: [Poolside model card](https://huggingface.co/poolside/Laguna-XS-2.1),
[llama.cpp container documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md).

## Validation on this PC

Verified the model SHA-256, CUDA loading, plain chat, structured automatic tool
calls, and health/model discovery/chat/web UI through Tailscale HTTPS. Reasoning
text is extracted into `reasoning_content`; the reasoning test exhausted a
4,096-token output limit before giving a final answer, so ordinary chat uses
the template's thinking-off default. A separate remote client was not tested.

Use the pinned Poolside conversion above: the ggml-org automatic conversion
tested during setup produced invalid probabilities and empty output on CUDA,
although it generated text on CPU. Its unused weights were removed.
The temporary CPU diagnostic container, unused Vulkan image, failed-conversion
metadata directory, and temporary diagnostic files were also removed. Only the
working CUDA container/image and Poolside model are needed for this setup.
