#!/usr/bin/python3
"""Remove user-writable Homebrew paths from a copied ELF executable."""

import pathlib
import re
import stat
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch-runc-rpath.py RUNC_BINARY")

path = pathlib.Path(sys.argv[1])
data = path.read_bytes()
patched = data

interpreter = b"/home/linuxbrew/.linuxbrew/lib/ld.so"
system_interpreter = b"/lib64/ld-linux-x86-64.so.2"
interpreter_count = patched.count(interpreter)
if interpreter_count > 1:
    raise SystemExit(f"expected at most one Homebrew ELF interpreter, found {interpreter_count}")
if interpreter_count == 1:
    patched = patched.replace(interpreter, system_interpreter.ljust(len(interpreter), b"\x00"), 1)

rpath_pattern = re.compile(rb"/home/linuxbrew/\.linuxbrew/Cellar/(?:runc|docker-engine)/[^\x00]+")
rpath_matches = list(rpath_pattern.finditer(patched))
if len(rpath_matches) > 1:
    raise SystemExit(f"expected at most one Homebrew RPATH, found {len(rpath_matches)}")
if rpath_matches:
    match = rpath_matches[0]
    replacement = b"/usr/local/lib/vllm-runc" if path.name == "runc" else b"/usr/local/lib/vllm-runtime"
    if len(replacement) > len(match.group()):
        raise SystemExit("replacement RPATH is too long")
    patched = patched[: match.start()] + replacement.ljust(len(match.group()), b"\x00") + patched[match.end() :]

mode = path.stat().st_mode
path.chmod(mode | stat.S_IWUSR)
try:
    path.write_bytes(patched)
finally:
    path.chmod(mode)
