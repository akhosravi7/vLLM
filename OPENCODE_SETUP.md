# vLLM setup for OpenCode

OpenCode uses the OpenAI-compatible Chat Completions API and sends tool definitions with `tool_choice: "auto"`. The vLLM server must therefore have automatic tool calling enabled.

## Required vLLM arguments

Keep the existing vLLM launch configuration and add:

```bash
--enable-auto-tool-choice \
--tool-call-parser hermes
```

For example:

```bash
vllm serve /models \
  --served-model-name Qwen3-32B-AWQ \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

The actual model path and all existing networking, TLS, context-length, GPU, and Tailscale settings should remain unchanged. The served model name must remain:

```text
Qwen3-32B-AWQ
```

After changing the launch arguments, restart the vLLM service using its existing service manager or deployment process.

## Why this is required

Without these options, ordinary `/v1/chat/completions` calls work, but OpenCode agent requests fail with HTTP 400:

```text
"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set
```

Tool calling is required for OpenCode to inspect files, edit files, and run shell commands or tests.

## Connectivity checks

These commands should be run from a machine connected to the same Tailscale network.

List models:

```bash
curl https://alibazz.tailf4ff3b.ts.net/v1/models
```

Test chat completions:

```bash
curl https://alibazz.tailf4ff3b.ts.net/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer dummy' \
  --data '{
    "model": "Qwen3-32B-AWQ",
    "messages": [{"role": "user", "content": "Reply with exactly: VLLM_OK"}],
    "temperature": 0,
    "max_tokens": 512
  }'
```

The larger output allowance is intentional: Qwen3 can consume a substantial number of completion tokens in its reasoning field before emitting visible content.

## Tool-calling check

After restarting vLLM, retry OpenCode. If tool calls are still malformed, confirm that `hermes` is a supported tool-call parser in the installed vLLM version and that the active Qwen3 chat template supports Hermes-style tool calls.

Enabling tool parsing does not make the API public. Continue exposing the endpoint only through the existing Tailscale network and do not add public ingress or firewall rules for OpenCode.
