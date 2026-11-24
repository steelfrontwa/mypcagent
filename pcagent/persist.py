# -*- coding: utf-8 -*-
"""Сохранение и загрузка чата для каждой рабочей папки."""
import hashlib
import json

from . import prompts, state


# ---------- API ----------
def chat_path():
    return state.CHATS_DIR / (hashlib.md5(str(state.WS).lower().encode("utf-8")).hexdigest()[:12] + ".json")


def save_chat():
    try:
        state.CHATS_DIR.mkdir(parents=True, exist_ok=True)
        with state.LOCK:
            data = {"messages": [({"role": m["role"], "content": "[скриншот]"} if isinstance(m.get("content"), list) else m)
                                 for m in state.MESSAGES[1:]], "transcript": state.TRANSCRIPT, "undo": state.UNDO, "usage": state.USAGE}
            text = json.dumps(data, ensure_ascii=False)
        tmp = chat_path().with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(chat_path())
    except Exception:
        pass


def load_chat():
    reset_chat()
    try:
        data = json.loads(chat_path().read_text(encoding="utf-8"))
    except Exception:
        return
    msgs = data.get("messages", [])
    # отрезаем «оборванный» конец: вызов инструментов без ответов
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            need = len(m["tool_calls"])
            got = 0
            while i + 1 + got < len(msgs) and msgs[i + 1 + got].get("role") == "tool":
                got += 1
            if got < need:
                msgs = msgs[:i]
                break
    state.MESSAGES.extend(msgs)
    state.TRANSCRIPT.extend(data.get("transcript", []))
    state.UNDO.update(data.get("undo", {}))
    state.USAGE.update(data.get("usage", {}))
    for it in state.TRANSCRIPT:
        if it.get("role") in ("confirm", "plan") and it.get("state") == "pending":
            it["state"] = "no"
        if it.get("role") == "tool" and it.get("result") is None:
            it["result"] = "(прервано)"


def reset_chat():
    state.MESSAGES[:] = [{"role": "system", "content": prompts.system_prompt()}]
    state.TRANSCRIPT.clear()
    state.UNDO.clear()
    state.PREVIEW_ERRORS.clear()
    state.USAGE.update({"prompt": 0, "completion": 0, "cloud_prompt": 0, "cloud_completion": 0})
