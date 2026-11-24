# -*- coding: utf-8 -*-
"""Текстовый режим инструментов для моделей без вызова функций."""
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import config, events, planning, registry, state, util


def tools_mode(p):
    return "text" if state.CFG.get("force_text") else (p.get("tools_mode") or "native")


def text_tools_prompt():
    lines = []
    for t in registry.TOOLS + [planning.PLAN_TOOL]:
        fn = t["function"]
        params = ", ".join(fn["parameters"].get("properties", {}).keys())
        lines.append(f"- {fn['name']}({params}): {fn['description']}")
    return ("ВАЖНО: у тебя нет встроенного вызова функций, поэтому вызывай инструменты ТЕКСТОМ. Чтобы выполнить действие, "
            "напиши ровно один блок и остановись:\n```tool\n{\"name\": \"write_file\", \"args\": {\"path\": \"a.txt\", "
            "\"content\": \"текст файла\"}}\n```\nЯ выполню действие и пришлю результат следующим сообщением "
            "«[результат инструмента]». Дальше продолжай, пока задача не будет выполнена. Никогда не объясняй пользователю, "
            "какие команды вводить, и не показывай код вместо создания файла: делай сам через инструменты. "
            "Когда всё сделано — ответь обычным текстом без блока tool. Инструменты:\n" + "\n".join(lines))


def parse_text_calls(content):
    """Достаёт вызовы инструментов, написанные моделью обычным текстом. Возвращает (вызовы, очищенный текст)."""
    calls, spans = [], []
    pats = [r"```(?:tool|tool_call|json)?[ \t]*\n?(\{.*?\})\s*```", r"<tool_call>\s*(\{.*?\})\s*</tool_call>"]
    for pat in pats:
        for m in re.finditer(pat, content, re.S):
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            name = obj.get("name") or obj.get("tool")
            args = obj.get("args") if "args" in obj else obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue
            if name in registry.IMPL and isinstance(args, dict):
                calls.append({"id": "t" + util.uid(), "type": "function",
                              "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
                spans.append(m.span())
    clean = content
    for a, b in sorted(spans, reverse=True):
        clean = clean[:a] + clean[b:]
    return calls[:6], clean.strip()


def api_messages():
    if tools_mode(state.ACTIVE) != "text":
        return state.MESSAGES
    out = [{"role": "system", "content": state.MESSAGES[0]["content"] + "\n\n" + text_tools_prompt()}]
    for m in state.MESSAGES[1:]:
        if m["role"] == "tool":
            out.append({"role": "user", "content": "[результат инструмента]\n" + str(m["content"])})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            txt = m.get("content") or ""
            for tc in m["tool_calls"]:
                try:
                    a = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    a = {}
                txt += "\n```tool\n" + json.dumps({"name": tc["function"]["name"], "args": a}, ensure_ascii=False) + "\n```"
            out.append({"role": "assistant", "content": txt.strip()})
        else:
            out.append({k: v for k, v in m.items() if k != "reasoning_content"})
    return out


def probe_tools(prof):
    """True — модель умеет вызывать функции, False — нет, None — не удалось проверить."""
    body = {"model": prof["model"], "stream": False, "max_tokens": 400, "temperature": 0,
            "messages": [{"role": "user", "content": "Вызови инструмент list_dir с path \".\". Ничего не пиши, только вызови."}],
            "tools": [registry.TOOLS[0]]}
    req = urllib.request.Request(prof["base_url"] + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + prof["api_key"]})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8"))
        return bool(resp["choices"][0]["message"].get("tool_calls"))
    except urllib.error.HTTPError as e:
        return False if e.code in (400, 404, 422) else None
    except Exception:
        return None


def run_probe(names=None):
    for name in (names or list(config.profiles())):
        prof = config.profiles().get(name)
        if not prof:
            continue
        res = probe_tools(prof)
        label = f"{prof.get('provider', '')} · {prof.get('model', '')}"
        if res is None:
            events.add_item({"role": "note", "id": util.uid(), "text": f"🔧 {label}: проверить вызов инструментов не удалось (нет связи?)."})
            continue
        prof["tools_mode"] = "native" if res else "text"
        config.save_cfg()
        events.add_item({"role": "note", "id": util.uid(), "text": f"🔧 {label}: " + (
            "вызов инструментов поддерживается ✅" if res else
            "модель не вызывает инструменты сама — включён ТЕКСТОВЫЙ режим (агент всё равно будет создавать и читать файлы) ⚠")})
    events.emit(events.snapshot_light())


def start_probe(name):
    if not os.environ.get("PC_AGENT_NO_PROBE"):
        threading.Thread(target=run_probe, args=([name],), daemon=True).start()
