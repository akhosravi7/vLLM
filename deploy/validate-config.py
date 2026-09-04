#!/usr/bin/python3
"""Validate ali-owned vLLM settings and emit a root-owned Compose env file."""

import argparse
import os
import re
import stat
import tempfile

DEFAULTS = {
    "SERVED_MODEL_NAME": "Qwen2.5-Coder-32B-Instruct-AWQ",
    "MAX_MODEL_LEN": "30000",
    "GPU_MEMORY_UTILIZATION": "0.90",
    "TENSOR_PARALLEL_SIZE": "1",
    "PIPELINE_PARALLEL_SIZE": "1",
    "REASONING_PARSER": "none",
    "TOKENIZER_MODE": "auto",
    "DTYPE": "auto",
    "LOAD_FORMAT": "auto",
    "KV_CACHE_DTYPE": "auto",
    "SEED": "0",
    "RENDERER_NUM_WORKERS": "1",
    "MAX_NUM_SEQS": "256",
    "MAX_NUM_BATCHED_TOKENS": "8192",
    "CPU_OFFLOAD_GB": "0",
    "SCHEDULING_POLICY": "fcfs",
    "UVICORN_LOG_LEVEL": "info",
    "MAX_LOGPROBS": "20",
    "OPTIMIZATION_LEVEL": "2",
    "PERFORMANCE_MODE": "balanced",
}

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
UINT_RE = re.compile(r"[0-9]{1,9}")
DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,3})?")
ENUMS = {
    "REASONING_PARSER": {"none", "qwen3", "qwen3_next", "deepseek_r1", "granite"},
    "TOKENIZER_MODE": {"auto", "hf", "mistral", "slow"},
    "DTYPE": {"auto", "float16", "bfloat16", "float32"},
    "LOAD_FORMAT": {"auto", "safetensors"},
    "KV_CACHE_DTYPE": {"auto", "fp8", "fp8_e4m3", "fp8_e5m2"},
    "SCHEDULING_POLICY": {"fcfs", "priority"},
    "UVICORN_LOG_LEVEL": {"critical", "error", "warning", "info", "debug", "trace"},
    "PERFORMANCE_MODE": {"balanced", "interactivity", "throughput"},
}


def fail(message: str) -> None:
    raise SystemExit(f"vLLM configuration error: {message}")


def bounded_int(key: str, value: str, low: int, high: int) -> None:
    if not UINT_RE.fullmatch(value) or not low <= int(value) <= high:
        fail(f"{key} must be an integer from {low} through {high}")


def bounded_decimal(key: str, value: str, low: float, high: float) -> None:
    if not DECIMAL_RE.fullmatch(value) or not low <= float(value) <= high:
        fail(f"{key} must be a decimal from {low} through {high}")


def validate(values: dict[str, str]) -> None:
    if not NAME_RE.fullmatch(values["SERVED_MODEL_NAME"]):
        fail("SERVED_MODEL_NAME contains unsupported characters")
    bounded_int("MAX_MODEL_LEN", values["MAX_MODEL_LEN"], 128, 1048576)
    bounded_decimal("GPU_MEMORY_UTILIZATION", values["GPU_MEMORY_UTILIZATION"], 0.05, 0.99)
    bounded_int("TENSOR_PARALLEL_SIZE", values["TENSOR_PARALLEL_SIZE"], 1, 8)
    bounded_int("PIPELINE_PARALLEL_SIZE", values["PIPELINE_PARALLEL_SIZE"], 1, 8)
    bounded_int("SEED", values["SEED"], 0, 2147483647)
    bounded_int("RENDERER_NUM_WORKERS", values["RENDERER_NUM_WORKERS"], 1, 64)
    bounded_int("MAX_NUM_SEQS", values["MAX_NUM_SEQS"], 1, 4096)
    bounded_int("MAX_NUM_BATCHED_TOKENS", values["MAX_NUM_BATCHED_TOKENS"], 128, 1048576)
    bounded_decimal("CPU_OFFLOAD_GB", values["CPU_OFFLOAD_GB"], 0.0, 256.0)
    bounded_int("MAX_LOGPROBS", values["MAX_LOGPROBS"], 0, 100)
    bounded_int("OPTIMIZATION_LEVEL", values["OPTIMIZATION_LEVEL"], 0, 3)
    for key, choices in ENUMS.items():
        if values[key] not in choices:
            fail(f"{key} must be one of: {', '.join(sorted(choices))}")


def read_config(path: str, owner_uid: int) -> dict[str, str]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot open {path}: {exc}")
    with os.fdopen(fd, "r", encoding="ascii", errors="strict") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            fail("configuration is not a regular file")
        if info.st_uid != owner_uid:
            fail(f"configuration must be owned by uid {owner_uid}")
        if info.st_mode & 0o022:
            fail("configuration must not be writable by group or other")
        if info.st_size > 16384:
            fail("configuration is too large")
        lines = source.readlines()

    values = dict(DEFAULTS)
    seen: set[str] = set()
    for number, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"line {number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        if key not in DEFAULTS:
            fail(f"line {number} uses unsupported key {key!r}")
        if key in seen:
            fail(f"line {number} repeats {key}")
        if not value or any(ord(char) < 0x21 or ord(char) > 0x7e for char in value):
            fail(f"line {number} has an empty, non-ASCII, or whitespace-containing value")
        values[key] = value
        seen.add(key)
    validate(values)
    return values


def write_env(path: str, values: dict[str, str]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="vllm.env.", dir=directory, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as output:
            for key in DEFAULTS:
                output.write(f"{key}={values[key]}\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--owner-uid", required=True, type=int)
    args = parser.parse_args()
    write_env(args.output, read_config(args.input, args.owner_uid))


if __name__ == "__main__":
    main()
