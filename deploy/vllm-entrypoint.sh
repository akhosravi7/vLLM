#!/bin/bash
set -Eeuo pipefail

case "${REASONING_PARSER:-none}" in
  none)
    exec /usr/local/bin/vllm serve "$@"
    ;;
  qwen3|qwen3_next|deepseek_r1|granite)
    exec /usr/local/bin/vllm serve "$@" --reasoning-parser "$REASONING_PARSER"
    ;;
  *)
    printf 'Unsupported REASONING_PARSER: %s\n' "$REASONING_PARSER" >&2
    exit 2
    ;;
esac
