# OpenAI-compatible client setup

## Endpoints

| Setting | Laguna | vLLM |
| --- | --- | --- |
| Local base URL | `http://127.0.0.1:8080/v1` | `http://127.0.0.1:8000/v1` |
| Model ID | `laguna-xs-2.1` | `Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| Context configured locally | 32,768 | 30,000 |

Both use `https://alibazz.tailf4ff3b.ts.net/v1` when selected by
`./tailscale-model laguna` or `./tailscale-model vllm`. The switcher checks health
but does not start or stop either backend. See [switching instructions](README.md).
Use a placeholder such as `local` if a client requires a nonempty API key.

## Laguna

The configured llama-server uses `--jinja` and the model's embedded template.
Plain chat and structured automatic tool calls passed on 2026-09-07. A test
returned `finish_reason: "tool_calls"`, a `get_weather` function call, and valid
JSON arguments. This validates the server API; a full OpenCode agent session
and a separate remote client have not been tested.

Thinking is off by default. Per-request
`"chat_template_kwargs":{"enable_thinking":true}` enables it, with extracted
text in `reasoning_content`. A reasoning test consumed 4,096 output tokens
without a final answer; keep thinking off for predictable short responses.
See [Laguna configuration](laguna/README.md).

## vLLM

The local checkpoint/configuration currently selects
`Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` and `TOOL_CALL_PARSER=qwen3_xml`.
The existing vLLM deployment was not changed or started during the Laguna
session. Do not infer that the current vLLM tool parser has been validated from
older Qwen2.5/Hermes or Qwen3 test results.

OpenCode sends tool definitions with `tool_choice: "auto"`. The server needs
`--enable-auto-tool-choice` and a parser compatible with the active checkpoint.
Verify that a request with a function definition produces a nonempty
`message.tool_calls` array, valid JSON `function.arguments`, and
`finish_reason: "tool_calls"`. Ordinary chat alone does not verify agent use.

The hardened installation workflow for live vLLM changes remains documented
in [deploy/README-install.md](deploy/README-install.md).

## Connectivity check

From a device connected to the tailnet, with Laguna selected:

```bash
curl --fail https://alibazz.tailf4ff3b.ts.net/v1/models
curl --fail https://alibazz.tailf4ff3b.ts.net/v1/chat/completions \
  -H 'Content-Type: application/json' \
  --data '{"model":"laguna-xs-2.1","messages":[{"role":"user","content":"Reply with exactly: READY"}],"max_tokens":128,"chat_template_kwargs":{"enable_thinking":false}}'
```

When vLLM is selected, use its model ID from `/v1/models`. The Tailscale route
is private to the tailnet.
