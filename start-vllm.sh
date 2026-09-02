#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly DOCKER_BIN="${DOCKER_BIN:-/home/linuxbrew/.linuxbrew/bin/docker}"
readonly DOCKERD_BIN="${DOCKERD_BIN:-/home/linuxbrew/.linuxbrew/opt/docker-engine/bin/dockerd}"
readonly COMPOSE_BIN="${COMPOSE_BIN:-/home/linuxbrew/.linuxbrew/bin/docker-compose}"
readonly DOCKER_UNIT="homebrew-docker-engine"
readonly DOCKER_PATH="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:/usr/sbin:/usr/bin"

FOLLOW_LOGS=false
if [[ "${1:-}" == "--logs" ]]; then
  FOLLOW_LOGS=true
elif [[ $# -gt 0 ]]; then
  printf 'Usage: %s [--logs]\n' "$0" >&2
  exit 2
fi

for executable in "$DOCKER_BIN" "$DOCKERD_BIN" "$COMPOSE_BIN"; do
  if [[ ! -x "$executable" ]]; then
    printf 'Required executable not found: %s\n' "$executable" >&2
    printf 'Install prerequisites with: brew install docker docker-engine docker-compose\n' >&2
    exit 1
  fi
done

if [[ ! -d "$PROJECT_DIR/models" || ! -f "$PROJECT_DIR/models/config.json" ]]; then
  printf 'A model checkpoint was not found in %s/models\n' "$PROJECT_DIR" >&2
  exit 1
fi

printf 'Authenticating for Docker service access...\n'
sudo -v

if ! sudo "$DOCKER_BIN" info >/dev/null 2>&1; then
  printf 'Starting the Homebrew Docker daemon...\n'

  sudo systemctl stop homebrew-docker.service >/dev/null 2>&1 || true
  sudo systemctl stop "${DOCKER_UNIT}.service" >/dev/null 2>&1 || true
  sudo systemctl reset-failed homebrew-docker.service >/dev/null 2>&1 || true
  sudo systemctl reset-failed "${DOCKER_UNIT}.service" >/dev/null 2>&1 || true

  sudo systemd-run \
    --unit="$DOCKER_UNIT" \
    --description='Homebrew Docker Engine' \
    --property=Restart=always \
    --property=RestartSec=5 \
    /usr/bin/env \
    "PATH=$DOCKER_PATH" \
    "$DOCKERD_BIN" >/dev/null

  printf 'Waiting for Docker to become ready...\n'
  for _ in {1..30}; do
    if sudo "$DOCKER_BIN" info >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  if ! sudo "$DOCKER_BIN" info >/dev/null 2>&1; then
    printf 'Docker did not become ready. Recent daemon logs:\n' >&2
    sudo journalctl -u "$DOCKER_UNIT" -n 100 --no-pager >&2
    exit 1
  fi
fi

if ! sudo "$DOCKER_BIN" info --format '{{json .Runtimes}}' | grep -q 'nvidia'; then
  printf 'Docker is running, but the NVIDIA runtime is not configured.\n' >&2
  printf 'Run: sudo nvidia-ctk runtime configure --runtime=docker\n' >&2
  exit 1
fi

printf 'Starting vLLM...\n'
sudo "$COMPOSE_BIN" --project-directory "$PROJECT_DIR" up -d
sudo "$COMPOSE_BIN" --project-directory "$PROJECT_DIR" ps

if [[ "$FOLLOW_LOGS" == true ]]; then
  sudo "$COMPOSE_BIN" --project-directory "$PROJECT_DIR" logs -f vllm
else
  printf '\nFollow startup logs with:\n  %s --logs\n' "$0"
fi
