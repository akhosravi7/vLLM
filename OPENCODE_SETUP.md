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
  --served-model-name Qwen2.5-Coder-32B-Instruct-AWQ \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

The actual model path and all existing networking, TLS, context-length, GPU, and Tailscale settings should remain unchanged. The served model name must remain:

```text
Qwen2.5-Coder-32B-Instruct-AWQ
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
    "model": "Qwen2.5-Coder-32B-Instruct-AWQ",
    "messages": [{"role": "user", "content": "Reply with exactly: VLLM_OK"}],
    "temperature": 0,
    "max_tokens": 512
  }'
```

The larger output allowance leaves room for a complete answer. The current
Qwen2.5 configuration uses `REASONING_PARSER=none`, so ordinary output appears
in `message.content` rather than the separate reasoning field.

## Tool-calling check

Do not treat an ordinary chat completion as a tool-calling test. Send at least
one function definition with `tool_choice: "auto"` and request use of that
function. A successful response has a nonempty `message.tool_calls` array,
valid JSON in `function.arguments`, and `finish_reason: "tool_calls"`.

The former Qwen3 checkpoint passed this structured tool-call test on 2026-09-04.
The current Qwen2.5-Coder-32B-Instruct-AWQ checkpoint does not: with the Hermes
parser it emits a textual `<tools>` block in `message.content`, leaves
`message.tool_calls` empty, and finishes with `stop`. Ordinary chat completion
is verified, but do not consider OpenCode agent operation verified until the
tool parser and chat template are made compatible.

If tool calls are malformed, confirm that the selected parser matches the
active checkpoint's chat-template tool format. Parser support alone is not
enough; a successful test must return a structured `message.tool_calls` array.

When copying command blocks, do not paste prose headings such as `Test chat
completion:` into Bash; `bash: Test: command not found` is harmless and does
not indicate a vLLM failure.

Enabling tool parsing does not make the API public. Continue exposing the endpoint only through the existing Tailscale network and do not add public ingress or firewall rules for OpenCode.
