# -*- coding: utf-8 -*-
"""Запросы к модели: потоковый ответ, повторы, объяснение ошибок."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import config, context, events, planning, registry, state, textmode, util


def open_stream(cfg, body):
    if cfg.get("no_usage"):
        body.pop("stream_options", None)
    for attempt in (1, 2):
        req = urllib.request.Request(
            cfg["base_url"] + "/chat/completions", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["api_key"]})
        try:
            return urllib.request.urlopen(req, timeout=900 if cfg.get("local") else 300)
        except urllib.error.HTTPError as e:
            raw = ""
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if attempt == 1 and e.code in (400, 422) and "stream_options" in body and re.search(r"stream_options|include_usage|unknown|unrecognized|extra", raw, re.I):
                cfg["no_usage"] = True  # некоторые сервисы-посредники не знают этот параметр
                config.save_cfg()
                body.pop("stream_options", None)
                continue
            e.msg = (e.msg or "") + " " + raw[:300]
            raise


def chat_stream():
    cfg = state.ACTIVE
    body = {"model": cfg["model"], "messages": textmode.api_messages(),
            "stream": True, "temperature": 0.3, "stream_options": {"include_usage": True}}
    if textmode.tools_mode(cfg) != "text":
        body["tools"] = registry.TOOLS + ([planning.PLAN_TOOL] if state.PLAN else [])
    content, reasoning, calls, item = "", "", {}, None
    state.CTX["req"] = context.est_tokens()
    with open_stream(cfg, body) as resp:
        for raw in resp:
            if state.CANCEL.is_set():
                raise state.Cancelled()
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            u = chunk.get("usage")
            if u:
                pt, ct = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
                state.USAGE["prompt"] += pt
                state.USAGE["completion"] += ct
                if not cfg.get("local"):
                    state.USAGE["cloud_prompt"] += pt
                    state.USAGE["cloud_completion"] += ct
                events.emit(events.usage_event())
                if cfg.get("local") and pt >= 1000 and state.CTX["req"] > 3000 and pt < state.CTX["req"] * 0.6 \
                        and any(0.85 * c_ <= pt <= c_ for c_ in (2048, 4096, 8192, 16384, 32768, 65536)):
                    newctx = int(pt * 0.85)
                    if not cfg.get("ctx") or cfg["ctx"] > newctx:
                        cfg["ctx"] = newctx
                        config.save_cfg()
                        events.add_item({"role": "note", "id": util.uid(), "text":
                                  f"⚠ Ollama режет запрос до ~{pt} токенов: модель теряет инструкции и перестаёт создавать файлы. "
                                  "Увеличь окно: в PowerShell выполни  setx OLLAMA_CONTEXT_LENGTH 16384  и перезапусти Ollama "
                                  f"(полностью закрой её в трее и открой заново). Пока я автоматически сжимаю историю под ~{newctx} токенов."})
            if not chunk.get("choices"):
                continue
            delta = chunk["choices"][0].get("delta", {})
            if delta.get("reasoning_content"):
                reasoning += delta["reasoning_content"]
            if delta.get("content"):
                content += delta["content"]
                if item is None:
                    item = {"role": "assistant", "id": util.uid(), "text": ""}
                    events.add_item(item)
                events.append_text(item, delta["content"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index")
                if idx is None:
                    idx = len(calls) if (tc.get("id") or not calls) else len(calls) - 1
                c = calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    c["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    c["name"] += fn["name"]
                a = fn.get("arguments")
                if a:
                    c["args"] += a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
    text_calls = []
    if not calls and content:
        text_calls, cleaned = textmode.parse_text_calls(content)
        if text_calls:
            content = cleaned
            if item is not None:
                events.patch_item(item["id"], {"text": cleaned})
    msg = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    if text_calls:
        msg["tool_calls"] = text_calls
    elif calls:
        msg["tool_calls"] = [
            {"id": c["id"] or f"call_{i}", "type": "function",
             "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
            for i, c in sorted(calls.items())]
    return msg


def explain_http_error(e):
    hints = {401: "Ключ недействителен. Нажми «Сменить ключ» слева.",
             402: "На счёте DeepSeek нет баланса — пополни на platform.deepseek.com.",
             429: "Слишком много запросов, подожди немного.",
             500: "Ошибка на стороне сервера, попробуй ещё раз.",
             503: "Сервер перегружен, попробуй ещё раз."}
    try:
        body = e.read().decode("utf-8", errors="replace")[:300]
    except Exception:
        body = ""
    return f"Ошибка API {e.code}. {hints.get(e.code, '')} {body}".strip()
