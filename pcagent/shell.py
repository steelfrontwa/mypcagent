# -*- coding: utf-8 -*-
"""Выполнение команд (в системе или в Docker-песочнице)."""
import os
import re
import shutil
import subprocess
import time

from . import fileops, state


DANGEROUS = re.compile(
    r"\b(rm\s+-\w*r|rmdir\s+/s|del\s+/[sq]|format\s|shutdown|mkfs|diskpart|reg\s+delete|Remove-Item)\b", re.I)


def docker_available():
    if time.time() - state._DOCKER["t"] < 30:
        return state._DOCKER["ok"]
    ok = False
    if shutil.which("docker"):
        try:
            ok = subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
        except Exception:
            ok = False
    state._DOCKER.update({"t": time.time(), "ok": ok})
    return ok


def docker_on():
    return bool(state.CFG.get("docker", {}).get("on"))


def docker_cmd(command):
    d = state.CFG.get("docker", {})
    cmd = ["docker", "run", "--rm", "-v", f"{state.WS}:/work", "-w", "/work", "--memory", "2g", "--cpus", "2"]
    if not d.get("net", True):
        cmd += ["--network", "none"]
    if os.name != "nt" and hasattr(os, "getuid"):
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    return cmd + [d.get("image") or "python:3.12-slim", "sh", "-c", command]


def t_run_command(command):
    sandbox = docker_on()
    if not fileops.confirm("Выполнить команду" + (" (в Docker)" if sandbox else "") + ": " + command,
                   force=bool(DANGEROUS.search(command)) and not sandbox):
        return "Пользователь отклонил."
    try:
        if sandbox:
            if not docker_available():
                return "Docker сейчас недоступен (не запущен?). Попроси пользователя запустить Docker Desktop."
            r = subprocess.run(docker_cmd(command), capture_output=True, text=True, errors="replace", timeout=300)
        else:
            r = subprocess.run(command, shell=True, cwd=state.WS, capture_output=True,
                               text=True, errors="replace", timeout=180)
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        return f"[код {r.returncode}]\n{out[-8000:]}"
    except subprocess.TimeoutExpired:
        return "Команда прервана по таймауту (180 с)."
