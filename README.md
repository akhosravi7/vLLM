# Qwen3-32B-AWQ with vLLM

This Compose project serves a local Qwen3-32B-AWQ checkpoint through vLLM's OpenAI-compatible API. The API listens only on `127.0.0.1`; no API key is configured by default.

## Prerequisites

- Docker Engine with the Compose plugin (`docker compose`)
- An NVIDIA GPU with a compatible NVIDIA driver
- NVIDIA Container Toolkit configured for Docker
- Enough aggregate GPU memory for the model and its KV cache

Confirm Docker can see the GPUs before starting vLLM:

```sh
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

## Model files

Place one complete Qwen3-32B-AWQ Hugging Face checkpoint directly in `models/`. At minimum, this normally includes `config.json`, tokenizer files, and all files referenced by `model.safetensors.index.json`. The directory is mounted read-only at `/models` in the container and is intentionally excluded from Git.

## Run the server

The defaults serve the model as `Qwen3-32B-AWQ` at `http://127.0.0.1:8000/v1`, with an 8,192-token context window and 90% GPU-memory utilization.

On Bazzite with the Homebrew Docker packages, use the included launcher. It starts the transient Docker daemon after a reboot when needed, verifies the NVIDIA runtime, and starts vLLM:

```sh
./start-vllm.sh
```

To start the service and immediately follow its logs:

```sh
./start-vllm.sh --logs
```

The launcher expects Homebrew's `docker`, `docker-engine`, and `docker-compose` packages to already be installed. NVIDIA Container Toolkit must also have been configured once with `sudo nvidia-ctk runtime configure --runtime=docker`.

On a conventional Docker host, the standard Compose commands remain:

```sh
docker compose up -d
docker compose logs -f
```

Initial startup can take several minutes while weights load and kernels compile. Check container health and the API:

```sh
docker compose ps
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models
```

Send a minimal chat request:

```sh
curl --fail http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen3-32B-AWQ",
    "messages": [{"role": "user", "content": "Reply with: hello"}],
    "max_tokens": 32
  }'
```

Stop and remove the container and network with:

```sh
docker compose down
```

The named `vllm-cache` volume is retained so compiled artifacts can be reused. Run `docker compose down --volumes` only when you also want to remove that cache.

## Configuration

Copy the example file and edit local overrides as needed:

```sh
cp .env.example .env
```

Available settings are `VLLM_IMAGE`, `VLLM_PORT`, `SERVED_MODEL_NAME`, `TENSOR_PARALLEL_SIZE`, `MAX_MODEL_LEN`, and `GPU_MEMORY_UTILIZATION`.

For multiple GPUs, set `TENSOR_PARALLEL_SIZE` to the number of GPUs used for tensor parallelism. The value should generally divide the model's attention-head count. For example:

```sh
TENSOR_PARALLEL_SIZE=2 docker compose up -d
```

If startup fails with an out-of-memory error, first reduce `MAX_MODEL_LEN` to shrink the KV cache. If necessary, lower `GPU_MEMORY_UTILIZATION` to leave more GPU memory for other processes; if vLLM cannot allocate enough cache after lowering it, raise the value again or free GPU memory. Review the detailed failure with `docker compose logs vllm`.
