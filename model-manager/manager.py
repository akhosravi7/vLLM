#!/usr/bin/env python3
"""Local llama.cpp model manager.

Owns the one GPU-backed llama.cpp server that the chat app talks to on
127.0.0.1:8002. It reuses the container conventions already used by the
Japanese-mode and Laguna scripts, but never changes Tailscale routes.

API (loopback only, bearer token):
  GET  /health
  GET  /status
  GET  /models
  POST /switch             {"id": "<model id>"}
  POST /restore-japanese
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VLLM_ROOT = ROOT.parent
CATALOG_PATH = Path(os.environ.get("MODEL_CATALOG", str(ROOT / "models.json")))
PORT = int(os.environ.get("MODEL_MANAGER_PORT", "8010"))
BIND = os.environ.get("MODEL_MANAGER_BIND", "127.0.0.1")
TOKEN = os.environ.get("MODEL_MANAGER_TOKEN", "").strip()
PODMAN = os.environ.get("PODMAN", "podman")
IMAGE = os.environ.get(
    "LLAMA_IMAGE",
    "ghcr.io/ggml-org/llama.cpp@sha256:a77f3bea9d62f6187ebb6ca8deb1a03aebeeb1ed7a832ac94663ff5c7815da63",
)
LLM_PORT = int(os.environ.get("LLM_PORT", "8002"))
ASR_PORT = int(os.environ.get("ASR_PORT", "8001"))
ASR_SCRIPT = VLLM_ROOT / "kotoba" / "kotoba-asrctl"
CHAT_NAME = "llama-chat"
JAPANESE_NAME = "llama-translate"
LEGACY_NAMES = ("llama-laguna",)
AUTOSTART = os.environ.get("MODEL_MANAGER_AUTOSTART", "japanese").strip().lower()

LOGGER = logging.getLogger("model_manager")
SWITCH_LOCK = threading.Lock()
SWITCHING_TO: str | None = None


class ManagerError(RuntimeError):
    pass


def load_catalog() -> dict[str, Any]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ManagerError(f"Could not read {CATALOG_PATH}: {error}") from error
    models = data.get("models")
    if not isinstance(models, list) or not models:
        raise ManagerError("The model catalog is empty.")
    return data


def model_entries() -> list[dict[str, Any]]:
    data = load_catalog()
    entries = []
    for entry in data["models"]:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("file"):
            continue
        entries.append(entry)
    return entries


def entry_by_id(model_id: str) -> dict[str, Any]:
    for entry in model_entries():
        if entry["id"] == model_id:
            return entry
    raise ManagerError(f"Unknown model id: {model_id}")


def entry_by_file(path: str) -> dict[str, Any] | None:
    name = Path(path).name
    for entry in model_entries():
        if Path(entry["file"]).name == name:
            return entry
    return None


def run(command: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    LOGGER.debug("run: %s", " ".join(command))
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise ManagerError(f"Command not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise ManagerError(f"Timed out after {timeout:.0f}s: {' '.join(command)}") from error


def podman(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return run([PODMAN, *args], timeout=timeout)


def container_running(name: str) -> bool:
    result = podman(
        "container",
        "inspect",
        "-f",
        "{{.State.Running}}",
        name,
        timeout=20,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def container_exists(name: str) -> bool:
    result = podman("container", "exists", name, timeout=20)
    return result.returncode == 0


def running_workloads() -> set[str]:
    result = podman("ps", "--format", "{{.Names}}", timeout=20)
    if result.returncode != 0:
        raise ManagerError(
            "Could not query podman: " + (result.stderr or result.stdout).strip()
        )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def container_info(name: str) -> dict[str, Any]:
    result = podman(
        "container",
        "inspect",
        "-f",
        "{{json .Config.Cmd}}|{{json .Config.Labels}}",
        name,
        timeout=20,
    )
    if result.returncode != 0:
        return {"cmd": [], "labels": {}}
    try:
        cmd_text, labels_text = result.stdout.strip().split("|", 1)
        return {
            "cmd": json.loads(cmd_text or "[]"),
            "labels": json.loads(labels_text or "{}"),
        }
    except ValueError:
        return {"cmd": [], "labels": {}}


def container_model(name: str) -> str | None:
    info = container_info(name)
    for index, value in enumerate(info["cmd"]):
        if value == "--model" and index + 1 < len(info["cmd"]):
            return str(info["cmd"][index + 1])
    return None


def container_label(name: str, key: str) -> str | None:
    value = container_info(name)["labels"].get(key)
    return str(value) if value else None


def stop_container(name: str) -> None:
    if not container_exists(name):
        return
    if container_running(name):
        result = podman("stop", "--time", "30", name, timeout=60)
        if result.returncode != 0:
            LOGGER.warning("Could not stop %s: %s", name, result.stderr.strip())
    remove_container(name)


def remove_container(name: str) -> None:
    if container_exists(name):
        podman("rm", "-f", name, timeout=60)


def stop_asr() -> None:
    if container_exists("kotoba-asr"):
        podman("stop", "--time", "30", "kotoba-asr", timeout=60)
        remove_container("kotoba-asr")


def stop_vllm() -> None:
    result = run(["systemctl", "is-active", "--quiet", "vllm.service"], timeout=20)
    if result.returncode != 0:
        return
    LOGGER.info("Stopping vLLM to free the GPU")
    result = run(["sudo", "-n", "vllmctl", "stop"], timeout=240)
    if result.returncode != 0:
        LOGGER.warning("Could not stop vLLM: %s", result.stderr.strip())


def stop_all_gpu_workloads(include_chat: bool = True) -> None:
    names = [JAPANESE_NAME, *LEGACY_NAMES]
    if include_chat:
        names.insert(0, CHAT_NAME)
    for name in names:
        stop_container(name)
    stop_asr()
    stop_vllm()


def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_health(name: str, url: str, timeout: float = 900.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health(url):
            LOGGER.info("%s is healthy at %s", name, url)
            return
        if container_exists(name) and not container_running(name):
            logs = podman("logs", "--tail", "30", name, timeout=30)
            detail = (logs.stdout + logs.stderr).strip()
            raise ManagerError(f"{name} exited before becoming healthy. {detail[-1200:]}")
        time.sleep(3)
    logs = podman("logs", "--tail", "30", name, timeout=30)
    detail = (logs.stdout + logs.stderr).strip()
    raise ManagerError(f"{name} did not become healthy within {timeout:.0f}s. {detail[-1200:]}")


def llama_args(entry: dict[str, Any]) -> list[str]:
    args = [
        "--model",
        f"/models/{Path(entry['file']).name}",
        "--alias",
        str(entry["id"]),
        "--host",
        "0.0.0.0",
        "--port",
        str(LLM_PORT),
        "--n-gpu-layers",
        "99",
        "--ctx-size",
        str(int(entry.get("ctx", 8192))),
        "--parallel",
        "1",
        "--flash-attn",
        "on",
        "--jinja",
    ]
    for key, flag in (
        ("temp", "--temp"),
        ("top_p", "--top-p"),
        ("top_k", "--top-k"),
        ("min_p", "--min-p"),
        ("repeat_penalty", "--repeat-penalty"),
    ):
        if key in entry:
            args.extend([flag, str(entry[key])])
    return args


def start_llama(name: str, entry: dict[str, Any], profile: str) -> None:
    model_path = Path(entry["file"])
    if not model_path.is_file():
        raise ManagerError(f"Model file is missing: {model_path}")

    expected = f"/models/{model_path.name}"
    if container_running(name) and container_model(name) == expected:
        if container_label(name, "local-ai.model") in {None, entry["id"]}:
            return

    remove_container(name)
    command = [
        PODMAN,
        "run",
        "-d",
        "--name",
        name,
        "--pull=never",
        "--device",
        "nvidia.com/gpu=all",
        "--security-opt",
        "label=disable",
        "--cap-drop=all",
        "--security-opt",
        "no-new-privileges",
        "-e",
        "NVIDIA_VISIBLE_DEVICES=void",
        "--label",
        f"local-ai.model={entry['id']}",
        "--label",
        f"local-ai.profile={profile}",
        "-p",
        f"127.0.0.1:{LLM_PORT}:{LLM_PORT}",
        "-v",
        f"{model_path.parent}:/models:ro",
        IMAGE,
        *llama_args(entry),
    ]
    result = run(command, timeout=120)
    if result.returncode != 0:
        raise ManagerError(
            "Could not start the llama.cpp container: "
            + (result.stderr or result.stdout).strip()[-1200:]
        )
    wait_health(name, f"http://127.0.0.1:{LLM_PORT}/health")


def start_asr() -> None:
    if not ASR_SCRIPT.is_file():
        raise ManagerError(f"ASR control script not found: {ASR_SCRIPT}")
    result = run([str(ASR_SCRIPT), "start"], timeout=900)
    if result.returncode != 0:
        raise ManagerError(
            "Could not start the ASR container: "
            + (result.stderr or result.stdout).strip()[-1200:]
        )
    wait_health("kotoba-asr", f"http://127.0.0.1:{ASR_PORT}/health")


def current_state() -> dict[str, Any]:
    if container_running(CHAT_NAME):
        model_path = container_model(CHAT_NAME) or ""
        entry = entry_by_file(model_path)
        return {
            "profile": "chat",
            "model": entry["id"] if entry else None,
            "active": True,
        }
    if container_running(JAPANESE_NAME):
        model_path = container_model(JAPANESE_NAME) or ""
        entry = entry_by_file(model_path)
        asr = container_running("kotoba-asr")
        return {
            "profile": "japanese" if asr else "japanese-llm-only",
            "model": entry["id"] if entry else None,
            "active": asr,
        }
    for name in LEGACY_NAMES:
        if container_running(name):
            entry = entry_by_file(container_model(name) or "")
            return {
                "profile": "laguna",
                "model": entry["id"] if entry else None,
                "active": True,
            }
    result = run(["systemctl", "is-active", "--quiet", "vllm.service"], timeout=10)
    if result.returncode == 0:
        return {"profile": "vllm", "model": None, "active": True}
    return {"profile": None, "model": None, "active": False}


def switch_generic(entry: dict[str, Any]) -> dict[str, Any]:
    stop_all_gpu_workloads(include_chat=True)
    start_llama(CHAT_NAME, entry, "chat")
    return {
        "profile": "chat",
        "model": entry["id"],
        "active": True,
    }


def switch_japanese(entry: dict[str, Any]) -> dict[str, Any]:
    stop_container(CHAT_NAME)
    for name in LEGACY_NAMES:
        stop_container(name)
    stop_vllm()
    stop_container(JAPANESE_NAME)
    start_asr()
    start_llama(JAPANESE_NAME, entry, "japanese")
    return {
        "profile": "japanese",
        "model": entry["id"],
        "active": True,
    }


def switch_to(model_id: str) -> dict[str, Any]:
    entry = entry_by_id(model_id)
    if entry.get("profile") == "japanese":
        return restore_japanese()
    with SWITCH_LOCK:
        state = current_state()
        if state["profile"] == "chat" and state["model"] == model_id:
            return state
        LOGGER.info("Switching to %s", model_id)
        return switch_generic(entry)


def restore_japanese() -> dict[str, Any]:
    entry = entry_by_id(str(load_catalog().get("default_model", "qwen2.5-7b-instruct")))
    with SWITCH_LOCK:
        state = current_state()
        if state["profile"] == "japanese" and state["model"] == entry["id"]:
            return state
        LOGGER.info("Restoring Japanese mode (%s)", entry["id"])
        return switch_japanese(entry)


def models_payload() -> dict[str, Any]:
    state = current_state()
    switching = SWITCHING_TO
    data = []
    for entry in model_entries():
        model_state = "available"
        if switching == entry["id"]:
            model_state = "loading"
        elif state["model"] == entry["id"] and state["active"]:
            model_state = "loaded"
        data.append(
            {
                "id": entry["id"],
                "object": "model",
                "owned_by": "local",
                "created": 0,
                "meta": {
                    "n_ctx": int(entry.get("ctx", 8192)),
                    "size_bytes": int(entry.get("size_bytes", 0)),
                },
                "name": entry.get("name", entry["id"]),
                "description": entry.get("description", ""),
                "profile": entry.get("profile", "chat"),
                "state": model_state,
                "default": bool(entry.get("default", False)),
            }
        )
    return {
        "object": "list",
        "data": data,
        "active": state,
        "switchingTo": switching,
        "defaultModel": load_catalog().get("default_model", ""),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalModelManager/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        LOGGER.info("%s %s", self.command, self.path)

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        header = self.headers.get("authorization", "")
        supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not supplied:
            supplied = self.headers.get("x-model-manager-token", "").strip()
        return bool(supplied) and hmac.compare_digest(supplied, TOKEN)

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            raise ManagerError("Invalid Content-Length")
        if length <= 0 or length > 8192:
            raise ManagerError("Request body is missing or too large")
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError as error:
            raise ManagerError("Request body is not valid JSON") from error
        if not isinstance(data, dict):
            raise ManagerError("Request body must be a JSON object")
        return data

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write(200, {"status": "ok"})
            return
        if not self._authorized():
            self._write(401, {"detail": "Authentication required"})
            return
        try:
            if self.path == "/models":
                self._write(200, models_payload())
            elif self.path == "/status":
                self._write(200, {"ok": True, **current_state(), "switchingTo": SWITCHING_TO})
            else:
                self._write(404, {"detail": "Not found"})
        except ManagerError as error:
            self._write(500, {"detail": str(error)})

    def do_POST(self) -> None:  # noqa: N802
        global SWITCHING_TO
        if not self._authorized():
            self._write(401, {"detail": "Authentication required"})
            return
        try:
            if self.path == "/switch":
                body = self._read_json()
                model_id = str(body.get("id", "")).strip()
                if not model_id:
                    raise ManagerError("Missing model id")
                entry_by_id(model_id)
                if SWITCHING_TO:
                    self._write(409, {"detail": f"Already switching to {SWITCHING_TO}"})
                    return
                SWITCHING_TO = model_id
                try:
                    result = switch_to(model_id)
                finally:
                    SWITCHING_TO = None
                self._write(200, {"ok": True, **result})
            elif self.path == "/restore-japanese":
                if SWITCHING_TO:
                    self._write(409, {"detail": f"Already switching to {SWITCHING_TO}"})
                    return
                SWITCHING_TO = "japanese"
                try:
                    result = restore_japanese()
                finally:
                    SWITCHING_TO = None
                self._write(200, {"ok": True, **result})
            else:
                self._write(404, {"detail": "Not found"})
        except ManagerError as error:
            self._write(500, {"detail": str(error)})
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Unhandled error")
            self._write(500, {"detail": f"Internal error: {error}"})


def autostart_default() -> None:
    """Restore Japanese mode after boot when nothing else holds the GPU."""
    global SWITCHING_TO
    if AUTOSTART not in {"japanese", "1", "true", "yes"}:
        return
    time.sleep(5)
    workload_names = {CHAT_NAME, JAPANESE_NAME, "kotoba-asr", *LEGACY_NAMES}
    for attempt in range(20):
        try:
            running = running_workloads()
            if running & workload_names:
                LOGGER.info(
                    "Autostart skipped; workload already running: %s",
                    ", ".join(sorted(running & workload_names)),
                )
                return
            with SWITCH_LOCK:
                running = running_workloads()
                if running & workload_names:
                    return
                if current_state()["profile"] is not None:
                    return
                default_id = str(
                    load_catalog().get("default_model", "qwen2.5-7b-instruct")
                )
                entry = entry_by_id(default_id)
                LOGGER.info("Autostarting Japanese mode (%s)", default_id)
                SWITCHING_TO = "japanese"
                try:
                    switch_japanese(entry)
                finally:
                    SWITCHING_TO = None
            return
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("Autostart attempt %s failed: %s", attempt + 1, error)
            time.sleep(5)
    LOGGER.error("Could not autostart Japanese mode")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("MODEL_MANAGER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    catalog = load_catalog()
    LOGGER.info(
        "Model manager listening on %s:%s; catalog=%s default=%s models=%s token=%s",
        BIND,
        PORT,
        CATALOG_PATH,
        catalog.get("default_model"),
        len(catalog.get("models", [])),
        "enabled" if TOKEN else "disabled",
    )
    if not TOKEN:
        LOGGER.warning("MODEL_MANAGER_TOKEN is empty; only loopback access should be possible")
    threading.Thread(target=autostart_default, daemon=True).start()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
