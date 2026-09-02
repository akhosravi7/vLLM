#!/usr/bin/bash
set -Eeuo pipefail

printf '%s\n' 'start-vllm.sh is retained only as a compatibility wrapper.' >&2
printf '%s\n' 'Use vllmctl directly for hardened day-to-day operation.' >&2

case "${1:-}" in
  "")
    exec /usr/local/bin/vllmctl start
    ;;
  --logs)
    /usr/local/bin/vllmctl start
    exec /usr/local/bin/vllmctl logs
    ;;
  *)
    printf 'Usage: %s [--logs]\n' "$0" >&2
    exit 2
    ;;
esac
