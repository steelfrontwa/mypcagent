# -*- coding: utf-8 -*-
"""Запуск программы."""
import json
import os
import pathlib
import secrets
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from . import config, persist, providers, scheduler, state, telegram, util, webserver


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if state.CONF_FILE.exists():
        try:
            raw = json.loads(state.CONF_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if "profiles" in raw:
            state.CFG = raw
        elif raw.get("api_key"):  # старый формат конфига
            name = "local" if raw.get("local") else "cloud"
            prof = {k: v for k, v in raw.items() if k != "workspace"}
            prof["name"] = name
            state.CFG = {"profiles": {name: prof}, "mode": name, "workspace": raw.get("workspace")}
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key and "cloud" not in config.profiles():
        cfg = providers.autodetect(env_key)
        if cfg:
            cfg["name"] = "cloud"
            config.profiles()["cloud"] = cfg
            config.fix_mode("cloud")

    args = [a for a in sys.argv[1:] if a != "--lan"]
    state.LAN = "--lan" in sys.argv[1:]
    if state.LAN:
        state.PIN = "".join(secrets.choice("0123456789") for _ in range(6))
    if args and pathlib.Path(" ".join(args)).expanduser().is_dir():
        state.WS = pathlib.Path(" ".join(args)).expanduser().resolve()
    elif state.CFG.get("workspace") and pathlib.Path(state.CFG["workspace"]).is_dir():
        state.WS = pathlib.Path(state.CFG["workspace"]).resolve()
    else:
        state.WS = (pathlib.Path.home() / "Documents" / "PC-Agent")
        state.WS.mkdir(parents=True, exist_ok=True)
        state.WS = state.WS.resolve()
    persist.load_chat()
    config.add_recent(state.WS)

    server = None
    for port in range(8765, 8790):
        try:
            state.PORT = port
            server = ThreadingHTTPServer(("0.0.0.0" if state.LAN else "127.0.0.1", port), webserver.Handler)
            break
        except OSError:
            continue
    if not server:
        print("Не нашёл свободный порт 8765–8789.")
        return
    server.daemon_threads = True
    telegram.tg_start()
    threading.Thread(target=scheduler.sched_loop, daemon=True).start()
    url = f"http://127.0.0.1:{state.PORT}/" + (f"?pin={state.PIN}" if state.LAN else "")
    print(f"ПК-агент запущен: http://127.0.0.1:{state.PORT}/")
    print(f"Рабочая папка: {state.WS}")
    if state.LAN:
        print("\n📱 ДОСТУП С ТЕЛЕФОНА (телефон и ПК в одной сети Wi-Fi):")
        print(f"   Адрес: http://{util.lan_ip()}:{state.PORT}/")
        print(f"   PIN-код: {state.PIN}")
        print("   Если не открывается — разреши Python в брандмауэре Windows (частная сеть).\n")
    print("Не закрывай это окно, пока работаешь. Остановить: Ctrl+C.")
    if not os.environ.get("PC_AGENT_NO_BROWSER"):
        threading.Timer(0.8, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
