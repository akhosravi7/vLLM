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

On this hardened host, `ali` may edit the reviewed staging sources but cannot
replace the live root-owned Compose file. An authenticated `guardian` must copy
`deploy/` to a root-owned staging directory, review it, and run the staged
installer. After installation, either account may use the existing service
workflow; `ali` is specifically allowed to run `vllmctl restart`.

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

Do not treat an ordinary chat completion as a tool-calling test. Send at least
one function definition with `tool_choice: "auto"` and request use of that
function. A successful response has a nonempty `message.tool_calls` array,
valid JSON in `function.arguments`, and `finish_reason: "tool_calls"`.

This configuration was verified on 2026-09-04 with vLLM 0.28.0 and
Qwen3-32B-AWQ. A test request selected `get_weather`, emitted
`{"city": "Chicago"}`, and finished with `tool_calls`. The ordinary completion
test also returned visible `VLLM_OK` while placing Qwen3's hidden work in the
separate `reasoning` field.

If tool calls are malformed, confirm that `hermes` remains a supported parser
and that the active Qwen3 chat template supports Hermes-style tool calls.

When copying command blocks, do not paste prose headings such as `Test chat
completion:` into Bash; `bash: Test: command not found` is harmless and does
not indicate a vLLM failure.

Enabling tool parsing does not make the API public. Continue exposing the endpoint only through the existing Tailscale network and do not add public ingress or firewall rules for OpenCode.
