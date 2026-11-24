# -*- coding: utf-8 -*-
"""Скрытый браузер Chrome/Edge: автопроверка страниц и скриншоты."""
import base64
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from . import events, pagepreview, state, util


VISION_RE = re.compile(r"(vl\b|-vl|vision|llava|4o|gemini|claude|pixtral|minicpm-v|gemma3|qwen2\.5vl|qwen3-vl|llama3\.2-vision)", re.I)


def find_browser():
    env = os.environ.get("PC_AGENT_BROWSER")
    if env and os.path.exists(env):
        return env
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [base + r"\Google\Chrome\Application\chrome.exe",
                          base + r"\Microsoft\Edge\Application\msedge.exe"]
    elif sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for c in cands:
        if os.path.exists(c):
            return c
    for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        w = shutil.which(n)
        if w:
            return w
    return None


def run_headless(url, extra=(), timeout=45, budget=6000):
    exe = find_browser()
    if not exe:
        raise RuntimeError("не найден Chrome или Microsoft Edge (на Windows Edge есть всегда)")
    prof = tempfile.mkdtemp(prefix="pcagent_")
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
           f"--user-data-dir={prof}", "--enable-logging=stderr", "--v=0", f"--virtual-time-budget={budget}"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.append("--no-sandbox")
    try:
        return subprocess.run(cmd + list(extra) + [url], capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def t_check_page(path=""):
    try:
        url, rel, missing = pagepreview.make_preview(path)
    except ValueError as e:
        return "Ошибка: " + str(e)
    try:
        r = run_headless(url, ("--dump-dom",))
    except subprocess.TimeoutExpired:
        return "Страница не загрузилась за 45 секунд (возможно, бесконечный цикл или зависание)."
    except Exception as e:
        return f"Автопроверка недоступна: {e}. Используй open_preview и попроси пользователя открыть страницу."
    time.sleep(0.4)
    errs = list(state.PREVIEW_ERRORS)
    state.PREVIEW_ERRORS.clear()
    events.emit({"type": "preview_errors", "count": 0})
    for line in (r.stderr or "").splitlines():
        if "CONSOLE" in line and (":ERROR:" in line or "Uncaught" in line):
            m = re.search(r'CONSOLE\(\d+\)\]\s*"(.*)", source: (\S+)', line)
            msg = (m.group(1) + " @ " + m.group(2).split("/")[-1]) if m else line[-200:]
            if not any(msg[:40] in e for e in errs):
                errs.append("консоль: " + msg)
    dom = r.stdout or ""
    title = re.search(r"<title>(.*?)</title>", dom, re.S | re.I)
    body = re.search(r"<body[^>]*>(.*?)</body>", dom, re.S | re.I)
    out = [f"Страница {rel} открыта в скрытом браузере (DOM {len(dom)} симв., title: "
           f"{(title.group(1).strip() if title else 'нет')})."]
    if body is not None and not re.sub(r"<script.*?</script>|\s", "", body.group(1), flags=re.S | re.I):
        out.append("ВНИМАНИЕ: страница пустая (в <body> нет содержимого).")
    if missing:
        out.append("Ссылки на несуществующие файлы: " + ", ".join(missing[:15]))
    out.append(("ОШИБКИ:\n" + "\n".join(errs[:20])) if errs else "Ошибок JavaScript не найдено.")
    return "\n".join(out)


def profile_vision(p):
    v = p.get("vision")
    return bool(v) if isinstance(v, bool) else bool(VISION_RE.search(p.get("model", "")))


def t_screenshot_page(path=""):
    try:
        url, rel, _ = pagepreview.make_preview(path)
    except ValueError as e:
        return "Ошибка: " + str(e)
    d = state.WS / ".agent_shots"
    d.mkdir(exist_ok=True)
    name = f"{datetime.now():%Y%m%d-%H%M%S}-{util.uid()}.png"
    try:
        run_headless(url, (f"--screenshot={d / name}", "--window-size=1024,640"), budget=4000)
    except subprocess.TimeoutExpired:
        return "Скриншот не получился: страница не загрузилась за 45 секунд."
    except Exception as e:
        return f"Скриншот недоступен: {e}"
    if not (d / name).exists():
        return "Скриншот не получился (браузер не создал файл)."
    events.add_item({"role": "image", "id": util.uid(), "url": "/shots/" + name, "title": rel})
    if profile_vision(state.ACTIVE):
        state.PENDING_IMAGES.append(str(d / name))
        return "Скриншот сделан и показан пользователю; изображение сейчас придёт тебе следующим сообщением."
    return ("Скриншот сделан и показан пользователю. Текущая модель не умеет смотреть картинки, "
            "поэтому для проверки опирайся на check_page.")


def add_image_messages():
    path = state.PENDING_IMAGES[-1]
    state.PENDING_IMAGES.clear()
    for m in state.MESSAGES:  # старые картинки не храним, чтобы не раздувать контекст
        if isinstance(m.get("content"), list):
            m["content"] = "[старый скриншот удалён]"
    b64 = base64.b64encode(pathlib.Path(path).read_bytes()).decode()
    state.MESSAGES.append({"role": "user", "content": [
        {"type": "text", "text": "Скриншот страницы (результат screenshot_page). Оцени, соответствует ли он заданию, "
                                 "и исправь, если нет."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]})
