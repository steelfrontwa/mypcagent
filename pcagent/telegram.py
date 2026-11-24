# -*- coding: utf-8 -*-
"""Telegram-бот для управления агентом."""
import json
import os
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import api_core, config, gitops, prompts, state, util


def tg_conf():
    return state.CFG.get("telegram") or {}


def tg_call(method, params=None, timeout=35, token=None):
    base = os.environ.get("PC_AGENT_TG_BASE", "https://api.telegram.org")
    req = urllib.request.Request(f"{base}/bot{token or tg_conf().get('token')}/{method}",
                                 data=json.dumps(params or {}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def tg_targets():
    c = state.TG["chat"]
    return list(tg_conf().get("chats", [])) if c == "*" else ([c] if c else [])


def tg_send(chats, text, buttons=None):
    chats = chats if isinstance(chats, list) else [chats]
    text = text or "Готово."
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    for chat in chats:
        for i, ch in enumerate(chunks):
            params = {"chat_id": chat, "text": ch}
            if buttons and i == len(chunks) - 1:
                params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
            try:
                tg_call("sendMessage", params, timeout=20)
            except Exception:
                pass


def tg_send_file(chat, path):
    data = path.read_bytes()
    b = "----pcagent" + util.uid()
    body = (f'--{b}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'.encode() +
            f'--{b}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n'.encode() + data + f"\r\n--{b}--\r\n".encode())
    base = os.environ.get("PC_AGENT_TG_BASE", "https://api.telegram.org")
    req = urllib.request.Request(f"{base}/bot{tg_conf().get('token')}/sendDocument", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    urllib.request.urlopen(req, timeout=120).read()


def tg_flush_tools():
    if state.TG["tools"] and tg_targets():
        tg_send(tg_targets(), "\n".join(state.TG["tools"][-15:]))
    state.TG["tools"] = []


def tg_events_loop():
    q = queue.Queue()
    with state.LOCK:
        state.SUBS.append(q)
    try:
        while not state.TG["stop"].is_set():
            try:
                ev = q.get(timeout=1)
            except queue.Empty:
                continue
            if not state.TG["chat"]:
                continue
            t = ev.get("type")
            if t == "item":
                it = ev["item"]
                role = it["role"]
                if role == "tool":
                    arg = it["args"].get("path") or it["args"].get("command") or it["args"].get("query") or it["args"].get("url") or ""
                    state.TG["tools"].append(f"⚙ {prompts.TOOL_RU.get(it['name'], it['name'])} {str(arg)[:80]}".strip())
                elif role == "assistant":
                    state.TG["texts"][it["id"]] = ""
                    state.TG["last"] = it["id"]
                    state.TG["order"].append(it["id"])
                elif role == "confirm" and it.get("state") == "pending":
                    tg_flush_tools()
                    tg_send(tg_targets(), "❓ " + it["title"] + ("\n\n" + it["detail"][:800] if it.get("detail") else ""),
                            [[("✅ Разрешить", f"c:{it['id']}:yes"), ("♾ Всегда", f"c:{it['id']}:always"), ("⛔ Нет", f"c:{it['id']}:no")]])
                elif role == "plan" and it.get("state") == "pending":
                    tg_flush_tools()
                    tg_send(tg_targets(), "📋 План:\n" + it["steps"], [[("✅ Выполнять", f"p:{it['id']}:yes"), ("⛔ Отклонить", f"p:{it['id']}:no")]])
                elif role == "error":
                    tg_send(tg_targets(), "⚠ " + it["text"])
                elif role == "note":
                    tg_send(tg_targets(), it["text"])
            elif t == "delta" and ev["id"] in state.TG["texts"]:
                state.TG["texts"][ev["id"]] += ev["delta"]
            elif t == "busy" and not ev.get("value"):
                tg_flush_tools()
                got = [state.TG["texts"][i].strip() for i in state.TG["order"] if state.TG["texts"].get(i, "").strip()]
                tg_send(tg_targets(), "\n\n".join(got[-2:]) or "Готово.")
                state.TG.update({"chat": None, "texts": {}, "last": "", "tools": [], "order": []})
    finally:
        with state.LOCK:
            if q in state.SUBS:
                state.SUBS.remove(q)


def tg_handle_message(chat, text):
    t = text.strip()
    cmd = t.split()[0].lower().split("@")[0] if t.startswith("/") else ""
    arg = t[len(t.split()[0]):].strip() if cmd else ""
    if cmd in ("/start", "/help"):
        tg_send(chat, "Я ПК-агент. Пиши задание обычным текстом.\n/status — состояние\n/stop — остановить\n/new — новый чат\n"
                      "/files — файлы проекта\n/get путь — прислать файл\n/history — последние версии проекта")
    elif cmd == "/status":
        tg_send(chat, f"Папка: {state.WS}\n" + ("⏳ Агент работает" if state.BUSY else "Свободен") + f"\nТокены: ↑{state.USAGE['prompt']} ↓{state.USAGE['completion']}")
    elif cmd == "/stop":
        state.CANCEL.set()
        tg_send(chat, "Останавливаю…")
    elif cmd == "/new":
        r, code = api_core.api_reset({})
        tg_send(chat, "Новый чат." if code == 200 else r.get("error", "Ошибка"))
    elif cmd == "/files":
        items_ = [("📁 " if e["d"] else "📄 ") + e["p"] for e in util.tree(2, 40)]
        tg_send(chat, "\n".join(items_) or "Папка пуста.")
    elif cmd == "/get":
        try:
            f = util.safe(arg)
            if not f.is_file() or f.stat().st_size > 40_000_000:
                raise ValueError
            tg_send_file(chat, f)
        except Exception:
            tg_send(chat, "Не нашёл такой файл (или он больше 40 МБ). Посмотри список: /files")
    elif cmd == "/history":
        rows = gitops.git_log(8) if gitops.is_repo() else []
        tg_send(chat, "\n".join(f"{c['h']} · {c['date']} · {c['subject']}" for c in rows) or "История не включена.")
    elif cmd:
        tg_send(chat, "Неизвестная команда. /help")
    else:
        if state.BUSY:
            return tg_send(chat, "Агент ещё работает. Дождись ответа или /stop.")
        state.TG.update({"chat": chat, "tools": [], "texts": {}, "last": ""})
        r, code = api_core.api_chat({"message": t})
        if code != 200:
            state.TG["chat"] = None
            tg_send(chat, r.get("error", "Ошибка"))


def tg_poll_loop():
    offset = 0
    while not state.TG["stop"].is_set():
        try:
            res = tg_call("getUpdates", {"offset": offset, "timeout": 20}, timeout=35)
        except Exception:
            state.TG["stop"].wait(5)
            continue
        for u in res.get("result", []):
            offset = u["update_id"] + 1
            try:
                conf = tg_conf()
                if "callback_query" in u:
                    cq = u["callback_query"]
                    chat = cq["message"]["chat"]["id"]
                    if chat in conf.get("chats", []):
                        kind, iid, ans = (cq.get("data", "::").split(":") + ["", ""])[:3]
                        if kind == "c":
                            api_core.api_confirm({"id": iid, "answer": ans})
                        elif kind == "p":
                            api_core.api_plan({"id": iid, "answer": ans})
                    tg_call("answerCallbackQuery", {"callback_query_id": cq["id"]}, timeout=10)
                    continue
                msg = u.get("message") or {}
                chat, text = msg.get("chat", {}).get("id"), (msg.get("text") or "").strip()
                if chat is None or not text:
                    continue
                if chat in conf.get("chats", []):
                    tg_handle_message(chat, text)
                elif text.startswith("/pair") and text.split()[-1] == conf.get("pair"):
                    conf.setdefault("chats", []).append(chat)
                    config.save_cfg()
                    tg_send(chat, "✅ Подключено! Пиши задание. /help — команды.")
                else:
                    tg_send(chat, "Нет доступа. Отправь /pair КОД (код показан в окне Telegram на компьютере).")
            except Exception:
                pass


def tg_start():
    if not tg_conf().get("token") or (state.TG["poll"] and state.TG["poll"].is_alive()):
        return
    state.TG["stop"].clear()
    state.TG["poll"] = threading.Thread(target=tg_poll_loop, daemon=True)
    state.TG["events"] = threading.Thread(target=tg_events_loop, daemon=True)
    state.TG["poll"].start()
    state.TG["events"].start()


def tg_stop():
    state.TG["stop"].set()


def tg_info():
    c = tg_conf()
    return {"on": bool(c.get("token")), "pair": c.get("pair", ""), "chats": len(c.get("chats", [])), "bot": c.get("bot", "")}
