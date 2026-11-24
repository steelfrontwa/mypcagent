# -*- coding: utf-8 -*-
"""Управление контекстом: оценка размера, сжатие истории в конспект."""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import config, events, planning, prompts, registry, state, textmode, util


def _msg_size(m):
    c = m.get("content")
    n = 1000 if isinstance(c, list) else len(c or "")
    for tc in m.get("tool_calls") or []:
        n += len(tc["function"].get("arguments") or "")
    return n


def tools_tokens():
    if textmode.tools_mode(state.ACTIVE) == "text":
        return len(textmode.text_tools_prompt()) // 3
    return len(json.dumps(registry.TOOLS + ([planning.PLAN_TOOL] if state.PLAN else []), ensure_ascii=False)) // 3


def est_tokens():
    return int(sum(_msg_size(m) for m in state.MESSAGES) / 2.7) + tools_tokens() + 60


def ctx_budget(p):
    return int(p.get("ctx") or (14000 if p.get("local") else 60000))


def ctx_event():
    prof = state.ACTIVE or (next(iter(config.profiles().values())) if config.profiles() else {})
    b = ctx_budget(prof)
    t = est_tokens()
    return {"type": "ctx", "pct": min(999, int(t * 100 / b)), "tokens": t, "budget": b}


def shrink_old(keep=10):
    """Дёшево уменьшает старое: длинные результаты инструментов и содержимое записанных файлов."""
    for m in state.MESSAGES[1:-keep]:
        c = m.get("content")
        if m["role"] == "tool" and isinstance(c, str) and len(c) > 300:
            m["content"] = c[:300] + "\n...[обрезано для экономии контекста]"
        elif m["role"] == "assistant":
            if isinstance(c, str) and len(c) > 1500:
                m["content"] = c[:800] + "\n...[обрезано]"
            for tc in m.get("tool_calls") or []:
                if tc["function"]["name"] in ("write_file", "create_docx", "create_xlsx") and len(tc["function"].get("arguments") or "") > 800:
                    try:
                        a_ = json.loads(tc["function"]["arguments"])
                        key = "content" if "content" in a_ else ("sheets" if "sheets" in a_ else "")
                        if key:
                            c_ = json.dumps(a_[key], ensure_ascii=False) if not isinstance(a_[key], str) else a_[key]
                            a_[key] = c_[:150] + f"...[{len(c_)} символов; файл уже записан на диск — при необходимости прочитай его read_file]"
                            tc["function"]["arguments"] = json.dumps(a_, ensure_ascii=False)
                    except Exception:
                        pass
        elif m["role"] == "user" and isinstance(c, str) and len(c) > 6000 and not c.startswith("[КОНСПЕКТ"):
            m["content"] = c[:3000] + "\n...[обрезано]"


def _describe(m):
    c = m.get("content")
    if isinstance(c, list):
        c = "[скриншот]"
    if m["role"] == "user":
        return "ПОЛЬЗОВАТЕЛЬ: " + str(c or "")[:700]
    if m["role"] == "assistant":
        parts = [str(c or "")[:500]] if c else []
        for tc in m.get("tool_calls") or []:
            try:
                a_ = json.loads(tc["function"]["arguments"] or "{}")
            except Exception:
                a_ = {}
            arg = a_.get("path") or a_.get("command") or a_.get("query") or a_.get("url") or a_.get("src") or ""
            parts.append(f"[вызов {tc['function']['name']} {str(arg)[:100]}]")
        return "АГЕНТ: " + " ".join(parts)
    return "РЕЗУЛЬТАТ: " + str(c or "")[:250]


def summarize_text(text):
    cfg = state.ACTIVE
    body = {"model": cfg["model"], "stream": False, "temperature": 0.2, "max_tokens": 1200,
            "messages": [{"role": "system", "content": prompts.SUM_SYS}, {"role": "user", "content": text}]}
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["api_key"]})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=600 if cfg.get("local") else 150).read().decode("utf-8"))
        return (resp["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        return ""


def compact_history(budget, force=False):
    msgs = state.MESSAGES[1:]
    if len(msgs) < 4:
        return False
    acc, start = 0.0, len(msgs)
    for i in range(len(msgs) - 1, -1, -1):
        acc += _msg_size(msgs[i]) / 2.7
        if acc > budget * 0.30:
            break
        start = i
    while start < len(msgs) and msgs[start]["role"] == "tool":
        start += 1
    if start >= len(msgs) or start < 2:  # хвост слишком большой или голова пустая — режем пополам
        start = max(2, len(msgs) // 2)
        while start < len(msgs) and msgs[start]["role"] == "tool":
            start += 1
    head, tail = msgs[:start], msgs[start:]
    if not head:
        return False
    before = est_tokens()
    events.add_item({"role": "note", "id": util.uid(), "text": "🧹 Чат стал длинным — сжимаю историю в конспект, чтобы модель не теряла инструкции…"})
    lines = [_describe(m) for m in head]
    text = "\n".join(lines)
    if len(text) > 28000:
        text = lines[0][:6000] + "\n...\n" + text[-22000:]
    summary = summarize_text(text)
    if not summary:  # модель не справилась — механический конспект
        users = [l for l in lines if l.startswith("ПОЛЬЗОВАТЕЛЬ")][-6:]
        summary = "Задачи пользователя:\n" + "\n".join(users) + "\n(подробный конспект составить не удалось; используй список файлов ниже и read_file)"
    touched = []
    for m in head:
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] in ("write_file", "edit_file", "create_docx", "create_xlsx", "move_file", "delete_file", "make_dir"):
                try:
                    a_ = json.loads(tc["function"]["arguments"] or "{}")
                    pth = a_.get("path") or a_.get("dst") or ""
                    if pth and pth not in touched:
                        touched.append(pth)
                except Exception:
                    pass
    tree_txt = "\n".join(("📁 " if e["d"] else "📄 ") + e["p"] for e in util.tree(3, 60))
    note = ("[КОНСПЕКТ предыдущей работы — это уже сделано, повторять не нужно]\n" + summary +
            ("\n\nФайлы, которые создавались или менялись: " + ", ".join(touched[:60]) if touched else "") +
            ("\n\nФайлы в рабочей папке сейчас:\n" + tree_txt if tree_txt else "") +
            "\n\nНапоминание: все действия делай инструментами (write_file, edit_file, read_file, list_dir, run_command…). "
            "Не пиши код в чат вместо создания файлов и не объясняй пользователю, что вводить в терминале. "
            "Чтобы узнать содержимое файла — вызови read_file.")
    new = [{"role": "user", "content": note}]
    if tail and tail[0]["role"] == "user":
        new.append({"role": "assistant", "content": "Понял конспект, продолжаю."})
    state.MESSAGES[:] = [state.MESSAGES[0]] + new + tail
    after = est_tokens()
    events.add_item({"role": "note", "id": util.uid(), "text": f"🧹 История сжата: ~{before} → ~{after} токенов. Файлы и результаты работы на диске сохранены."})
    return True


def manage_context():
    b = ctx_budget(state.ACTIVE)
    t = est_tokens()
    if t > b * 0.45:
        shrink_old(10)
        t = est_tokens()
    if t > b * 0.70:
        compact_history(b)
        shrink_old(6)
    events.emit(ctx_event())
