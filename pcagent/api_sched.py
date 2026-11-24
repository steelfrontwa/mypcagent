# -*- coding: utf-8 -*-
"""Команды интерфейса: расписание."""
import re
from datetime import datetime

from . import config, scheduler, state, util


def sched_public():
    return [{k: v for k, v in t.items()} for t in state.CFG.get("schedules", [])]


def api_sched_list(b):
    return {"tasks": sched_public(), "ws": str(state.WS)}, 200


def api_sched_add(b):
    text = str(b.get("text", "")).strip()[:2000]
    kind = b.get("kind")
    if not text or kind not in ("daily", "weekdays", "every"):
        return {"error": "Укажи задание и периодичность."}, 400
    t = {"id": util.uid(), "text": text, "workspace": str(state.WS), "kind": kind, "auto": bool(b.get("auto")),
         "enabled": True, "last_run": None, "created": datetime.now().isoformat(timespec="seconds")}
    if kind == "every":
        try:
            t["minutes"] = max(5, int(b.get("minutes")))
        except (TypeError, ValueError):
            return {"error": "Интервал — число минут (не меньше 5)."}, 400
    else:
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(b.get("time", ""))):
            return {"error": "Время в формате ЧЧ:ММ."}, 400
        t["time"] = b["time"].zfill(5)
    sch = state.CFG.setdefault("schedules", [])
    if len(sch) >= 20:
        return {"error": "Слишком много заданий (максимум 20)."}, 400
    sch.append(t)
    config.save_cfg()
    return api_sched_list(b)


def api_sched_del(b):
    state.CFG["schedules"] = [t for t in state.CFG.get("schedules", []) if t["id"] != b.get("id")]
    config.save_cfg()
    return api_sched_list(b)


def api_sched_toggle(b):
    for t in state.CFG.get("schedules", []):
        if t["id"] == b.get("id"):
            t["enabled"] = not t.get("enabled", True)
    config.save_cfg()
    return api_sched_list(b)


def api_sched_run(b):
    for t in state.CFG.get("schedules", []):
        if t["id"] == b.get("id"):
            return ({"ok": True}, 200) if scheduler.run_scheduled(t) else ({"error": "Агент занят или папка задания недоступна."}, 409)
    return {"error": "Не найдено."}, 404
