# -*- coding: utf-8 -*-
"""План перед действием: показ плана и ожидание утверждения."""
import threading

from . import events, state, util


# ---------- план перед действием ----------
PLAN_TOOL = {"type": "function", "function": {
    "name": "propose_plan",
    "description": "Показать пользователю план действий (нумерованный список шагов) и дождаться утверждения",
    "parameters": {"type": "object", "properties": {"steps": {"type": "string"}}, "required": ["steps"]}}}


def t_propose_plan(steps):
    pid = util.uid()
    ev = threading.Event()
    state.PENDING[pid] = {"ev": ev, "ans": "no", "text": steps}
    events.add_item({"role": "plan", "id": pid, "steps": steps, "state": "pending"})
    while not ev.wait(0.4):
        if state.CANCEL.is_set():
            state.PENDING.pop(pid, None)
            events.patch_item(pid, {"state": "no"})
            raise state.Cancelled()
    ans = state.PENDING.pop(pid)
    ok = ans["ans"] == "yes"
    events.patch_item(pid, {"state": "yes" if ok else "no", "steps": ans["text"]})
    if ok:
        return "Пользователь утвердил план (возможно, отредактировав). Выполняй строго по нему:\n" + ans["text"]
    return "Пользователь отклонил план. Ничего не меняй, спроси, что поправить."
