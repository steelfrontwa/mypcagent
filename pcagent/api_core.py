# -*- coding: utf-8 -*-
"""Основные команды интерфейса (чат, настройки, подключение ИИ, папки)."""
import os
import pathlib
import subprocess
import sys
import threading

from . import agent, config, context, events, fileops, pagepreview, persist, providers, shell, state, textmode, util


def api_chat(b):
    if not config.profiles():
        return {"error": "Сначала подключи ИИ (облако или локальный)."}, 400
    text = (b.get("message") or "").strip()
    if not text:
        return {"error": "Пустое сообщение."}, 400
    with state.LOCK:
        if state.BUSY:
            return {"error": "Агент ещё работает. Дождись ответа или нажми «Стоп»."}, 409
        state.BUSY = True
    state.CANCEL.clear()
    threading.Thread(target=agent.run_task, args=(text,), daemon=True).start()
    return {"ok": True}, 200


def api_stop(b):
    state.CANCEL.set()
    return {"ok": True}, 200


def api_confirm(b):
    p = state.PENDING.get(b.get("id"))
    if p:
        p["ans"] = b.get("answer", "no")
        p["ev"].set()
    return {"ok": True}, 200


def api_auto(b):
    state.AUTO = bool(b.get("value"))
    events.emit({"type": "auto", "value": state.AUTO})
    return {"ok": True}, 200


def api_setup(b):
    key = (b.get("api_key") or "").strip()
    if not key:
        return {"error": "Вставь ключ."}, 400
    cfg, err, ids = providers.connect_cloud(key, b.get("base_url") or "", b.get("model") or "")
    if not cfg:
        return {"error": err or "Не удалось подключиться."}, 400
    cfg["name"] = "cloud"
    config.profiles()["cloud"] = cfg
    config.fix_mode("cloud")
    config.save_cfg()
    events.emit(events.snapshot())
    events.add_item({"role": "note", "id": util.uid(), "text": f"☁ Подключено: {cfg['provider']} · {cfg['model']}"
              + (f" (доступно моделей: {len(ids)}; сменить можно слева в поле «Модель»)" if len(ids) > 1 else "")})
    textmode.start_probe("cloud")
    return {"ok": True, "models": len(ids)}, 200


def api_local_scan(b):
    found = []
    cands = list(providers.LOCAL_CANDIDATES)
    custom = providers.normalize_base(b.get("base_url"))
    if custom:
        cands.insert(0, ("Свой адрес", custom))
    for name, base in cands:
        try:
            models = providers.list_models(base)
            found.append({"name": name, "base_url": base, "models": models})
        except Exception:
            continue
    return {"servers": found}, 200


def api_local_setup(b):
    base = providers.normalize_base(b.get("base_url"))
    if not base:
        return {"error": "Укажи адрес сервера."}, 400
    try:
        models = providers.list_models(base, timeout=8)
    except Exception:
        return {"error": f"Сервер не отвечает: {base}"}, 400
    model = (b.get("model") or "").strip() or (models[0] if models else "")
    if not model:
        return {"error": "На сервере нет загруженных моделей. Скачай модель (например: ollama pull qwen2.5:7b)."}, 400
    name = next((n for n, u in providers.LOCAL_CANDIDATES if u == base), "Локальный ИИ")
    config.profiles()["local"] = {"name": "local", "provider": name, "base_url": base, "model": model,
                           "api_key": "local", "local": True}
    config.fix_mode("local")
    config.save_cfg()
    events.emit(events.snapshot())
    textmode.start_probe("local")
    return {"ok": True}, 200


def api_undo(b):
    if state.BUSY:
        return {"error": "Сначала останови агента."}, 409
    rid = b.get("id")
    if rid == "last":
        rid = list(state.UNDO)[-1] if state.UNDO else None
    err = fileops.do_undo(rid)
    return ({"error": err}, 400) if err else ({"ok": True}, 200)


def api_preview(b):
    try:
        url, rel, missing = pagepreview.make_preview(b.get("path") or "")
    except Exception as e:
        return {"error": str(e)}, 400
    return {"url": url, "missing": missing}, 200


def api_plan(b):
    pend = state.PENDING.get(b.get("id"))
    if pend:
        pend["ans"] = "yes" if b.get("answer") == "yes" else "no"
        pend["text"] = str(b.get("text") or pend["text"])[:6000]
        pend["ev"].set()
    return {"ok": True}, 200


def api_plan_mode(b):
    state.PLAN = bool(b.get("value"))
    return {"ok": True}, 200


def api_prices(b):
    try:
        state.CFG["price_in"] = float(b.get("inp")) if str(b.get("inp", "")).strip() else None
        state.CFG["price_out"] = float(b.get("out")) if str(b.get("out", "")).strip() else None
    except ValueError:
        return {"error": "Цена должна быть числом, например 0.28"}, 400
    config.save_cfg()
    events.emit(events.usage_event())
    return {"ok": True}, 200


def api_rules(b):
    f = state.WS / "AGENTS.md"
    if not f.exists():
        f.write_text("# Правила для агента\n\n- Отвечай по-русски.\n- Не удаляй файлы без моего разрешения.\n"
                     "- Стиль кода: простой, с короткими комментариями.\n- Сайты и игры делай в отдельной папке проекта.\n",
                     encoding="utf-8")
    return api_open({"path": "AGENTS.md"})


def api_verify(b):
    state.CFG["verify"] = bool(b.get("value"))
    config.save_cfg()
    return {"ok": True}, 200


def api_docker_set(b):
    on = bool(b.get("on"))
    if on and not shell.docker_available():
        state.CFG["docker"] = {**state.CFG.get("docker", {}), "on": False}
        config.save_cfg()
        return {"error": "Docker не найден или не запущен. Установи Docker Desktop и запусти его."}, 400
    state.CFG["docker"] = {"on": on, "image": str(b.get("image") or "python:3.12-slim").strip()[:100],
                     "net": not bool(b.get("nonet"))}
    config.save_cfg()
    return {"ok": True}, 200


def api_probe(b):
    if state.BUSY:
        return {"error": "Сначала останови агента."}, 409
    threading.Thread(target=textmode.run_probe, daemon=True).start()
    return {"ok": True}, 200


def api_force_text(b):
    state.CFG["force_text"] = bool(b.get("value"))
    config.save_cfg()
    events.emit(events.snapshot_light())
    return {"ok": True}, 200


def api_autopilot(b):
    state.CFG["autopilot"] = bool(b.get("value"))
    config.save_cfg()
    return {"ok": True}, 200


def api_make_game(b):
    idea = str(b.get("idea") or "").strip()[:1500]
    genre = str(b.get("genre") or "").strip()[:60]
    text = ("Создай браузерную игру. " + (f"Идея: {idea}. " if idea else "Придумай оригинальную увлекательную игру сам. ") +
            (f"Жанр: {genre}. " if genre else "") + "Доведи её до играбельного состояния и проверь.")
    state.AP["oneoff"] = True
    state.AP["publish"] = bool(b.get("publish"))
    r, code = api_chat({"message": text})
    if code != 200:
        state.AP["oneoff"] = state.AP["publish"] = False
    return r, code


def api_compact(b):
    if state.BUSY:
        return {"error": "Сначала останови агента."}, 409
    if not state.ACTIVE and config.profiles():
        state.ACTIVE = config.choose_profile("")
    if not context.compact_history(context.ctx_budget(state.ACTIVE), force=True):
        return {"error": "Чат ещё короткий — сжимать нечего."}, 400
    persist.save_chat()
    events.emit(context.ctx_event())
    return {"ok": True}, 200


def api_ctx_set(b):
    for name in ("local", "cloud"):
        prof = config.profiles().get(name)
        if not prof:
            continue
        v = str(b.get(name, "")).strip()
        if v.isdigit() and 2000 <= int(v) <= 2_000_000:
            prof["ctx"] = int(v)
        elif v == "":
            prof.pop("ctx", None)
    config.save_cfg()
    events.emit(context.ctx_event())
    return {"ok": True}, 200


def api_models(b):
    prof = config.profiles().get(b.get("profile"))
    try:
        return {"models": providers.list_models(prof["base_url"], prof.get("api_key", "local"), timeout=8)}, 200
    except Exception:
        return {"models": []}, 200


def api_model(b):
    prof = config.profiles().get(b.get("profile"))
    m = (b.get("model") or "").strip()
    if prof and m:
        prof["model"] = m
        config.save_cfg()
    return {"ok": True}, 200


def api_mode(b):
    m = b.get("mode")
    if (m == "auto" and len(config.profiles()) > 1) or m in config.profiles():
        state.CFG["mode"] = m
        config.save_cfg()
        events.emit({"type": "mode", "value": m})
    return {"ok": True}, 200


def api_reset(b):
    if state.BUSY:
        return {"error": "Сначала останови агента."}, 409
    persist.reset_chat()
    persist.save_chat()
    events.emit(events.snapshot())
    return {"ok": True}, 200


def api_workspace(b):
    if state.BUSY:
        return {"error": "Сначала останови агента."}, 409
    p = pathlib.Path(str(b.get("path", "")).strip().strip('"')).expanduser()
    if not p.is_dir():
        return {"error": "Такой папки нет."}, 400
    persist.save_chat()
    state.WS = p.resolve()
    state.CFG["workspace"] = str(state.WS)
    config.add_recent(state.WS)
    persist.load_chat()
    events.emit(events.snapshot())
    return {"ok": True}, 200


def api_pick(b):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askdirectory(initialdir=str(state.WS), title="Выбери рабочую папку")
        root.destroy()
        return {"path": p or ""}, 200
    except Exception:
        return {"error": "no_tk"}, 200


def api_open(b):
    try:
        p = util.safe(b.get("path") or ".")
        if p.is_file() and p.suffix.lower() in util.BAD_OPEN:
            return {"error": "Такие файлы не открываю автоматически."}, 400
        if os.name == "nt":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True}, 200
    except Exception as e:
        return {"error": str(e)}, 400
