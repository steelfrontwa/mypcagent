# -*- coding: utf-8 -*-
"""Расписание заданий."""
import pathlib
import threading
import time
from datetime import datetime
from datetime import timedelta

from . import api_core, config, events, persist, state, telegram


def sched_due(t, now):
    last = datetime.fromisoformat(t["last_run"]) if t.get("last_run") else None
    if t["kind"] == "every":
        base = last or datetime.fromisoformat(t["created"])
        return (now - base).total_seconds() >= int(t["minutes"]) * 60
    hh, mm = (int(x) for x in t["time"].split(":"))
    due_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t["kind"] == "weekdays" and now.weekday() >= 5:
        return False
    return due_at <= now <= due_at + timedelta(hours=2) and (last is None or last < due_at)


def run_scheduled(t):
    """Запускает задание по расписанию. Возвращает True, если агент принял его."""
    if state.BUSY:
        return False
    ws = pathlib.Path(t["workspace"])
    if not ws.is_dir():
        return False
    if ws.resolve() != state.WS:
        persist.save_chat()
        state.WS = ws.resolve()
        state.CFG["workspace"] = str(state.WS)
        persist.load_chat()
        events.emit(events.snapshot())
    prev_auto, prev_plan = state.AUTO, state.PLAN
    state.AUTO = bool(t.get("auto"))
    state.PLAN = False
    events.emit({"type": "auto", "value": state.AUTO})
    if telegram.tg_conf().get("chats"):
        state.TG.update({"chat": "*", "tools": [], "texts": {}, "last": ""})
    state.SCHED["active"] = t["id"]
    r, code = api_core.api_chat({"message": "[Задание по расписанию] " + t["text"]})
    if code != 200:
        state.AUTO, state.PLAN, state.SCHED["active"] = prev_auto, prev_plan, None
        events.emit({"type": "auto", "value": state.AUTO})
        state.TG["chat"] = None
        return False
    t["last_run"] = datetime.now().isoformat(timespec="seconds")
    config.save_cfg()

    def watch():
        while state.BUSY:
            time.sleep(1)
        state.AUTO, state.PLAN, state.SCHED["active"] = prev_auto, prev_plan, None
        events.emit({"type": "auto", "value": state.AUTO})
    threading.Thread(target=watch, daemon=True).start()
    return True


def sched_loop():
    while True:
        time.sleep(20)
        try:
            now = datetime.now()
            for t in list(state.CFG.get("schedules", [])):
                if t.get("enabled", True) and not state.BUSY and sched_due(t, now):
                    run_scheduled(t)
                    break
        except Exception:
            pass
