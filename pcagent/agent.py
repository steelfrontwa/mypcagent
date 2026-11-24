# -*- coding: utf-8 -*-
"""Главный цикл агента: шаги модели, инструменты, обработка задания."""
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request

from . import autopilot, browser, config, context, events, gitops, llm, persist, prompts, registry, state, textmode, util


def run_turn(max_steps=40):
    bad = used = nudges = 0
    for _ in range(max_steps):
        context.manage_context()
        msg = llm.chat_stream()
        state.MESSAGES.append(msg)
        if not msg.get("tool_calls"):
            if (used == 0 and nudges < 2 and prompts.ACTION_RE.search(state.CURRENT_TASK[0]) and prompts.INSTR_RE.search(msg.get("content") or "")):
                nudges += 1
                if nudges == 2 and textmode.tools_mode(state.ACTIVE) != "text":
                    state.ACTIVE["tools_mode"] = "text"
                    config.save_cfg()
                    events.add_item({"role": "note", "id": util.uid(),
                              "text": "Модель пишет инструкции вместо действий — включаю текстовый режим инструментов."})
                    events.emit({"type": "engine", "label": config.engine_label()})
                state.MESSAGES.append({"role": "user", "content": prompts.NUDGE})
                continue
            return
        used += len(msg["tool_calls"])
        for tc in msg["tool_calls"]:
            if state.CANCEL.is_set():
                raise state.Cancelled()
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = None
            if args is None or name not in registry.IMPL:
                bad += 1
                if bad >= 2 and state.ACTIVE.get("local") and "cloud" in config.profiles() and state.CFG.get("mode") == "auto":
                    state.ACTIVE = config.profiles()["cloud"]
                    events.emit({"type": "engine", "label": config.engine_label()})
                    events.add_item({"role": "note", "id": util.uid(),
                              "text": "Локальная модель путается в инструментах — переключаюсь на облако."})
            item = {"role": "tool", "id": util.uid(), "name": name, "args": args or {}, "result": None}
            events.add_item(item)
            state.LAST_UNDO[0] = None
            result = registry.call_tool(name, args) if args is not None else "Ошибка: неверный JSON аргументов."
            rid = state.LAST_UNDO[0]
            if rid in state.UNDO:
                state.UNDO[rid]["item"] = item["id"]
            events.patch_item(item["id"], {"result": result[:4000], "undo": rid if rid in state.UNDO else None})
            state.MESSAGES.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            events.emit({"type": "tree", "items": util.tree()})
        if state.PENDING_IMAGES:
            browser.add_image_messages()
        persist.save_chat()
    events.add_item({"role": "note", "id": util.uid(), "text": "Достигнут лимит шагов. Напиши «продолжай», если нужно."})


def run_task(text):
    ap = bool(state.CFG.get("autopilot")) or state.AP["oneoff"]
    state.AP["oneoff"] = False
    state.AP["on"] = ap
    prev_auto, prev_plan = state.AUTO, state.PLAN
    if ap:
        state.AUTO, state.PLAN = True, False
        events.emit({"type": "auto", "value": True})
    events.add_item({"role": "user", "id": util.uid(), "text": text})
    state.MESSAGES[0] = {"role": "system", "content": prompts.system_prompt()}
    state.CURRENT_TASK[0] = text
    mark = len(state.MESSAGES)
    state.MESSAGES.append({"role": "user", "content": text})
    state.ACTIVE = config.choose_profile(text)
    events.emit({"type": "busy", "value": True, "engine": config.engine_label()})
    try:
        try:
            run_body(text)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            if state.ACTIVE.get("local") and "cloud" in config.profiles() and state.CFG.get("mode") == "auto":
                del state.MESSAGES[mark + 1:]
                state.ACTIVE = config.profiles()["cloud"]
                events.emit({"type": "engine", "label": config.engine_label()})
                events.add_item({"role": "note", "id": util.uid(), "text": "Локальный ИИ недоступен — продолжаю в облаке."})
                run_body(text)
            else:
                raise
    except state.Cancelled:
        del state.MESSAGES[mark:]
        events.add_item({"role": "note", "id": util.uid(), "text": "Остановлено."})
    except urllib.error.HTTPError as e:
        del state.MESSAGES[mark:]
        events.add_item({"role": "error", "id": util.uid(), "text": llm.explain_http_error(e)})
    except urllib.error.URLError as e:
        del state.MESSAGES[mark:]
        text = ("Не удаётся подключиться к локальному ИИ. Запущен ли Ollama / LM Studio и загружена ли модель?"
                if state.ACTIVE.get("local") else f"Нет соединения с сервером: {e.reason}")
        events.add_item({"role": "error", "id": util.uid(), "text": text})
    except Exception as e:
        del state.MESSAGES[mark:]
        events.add_item({"role": "error", "id": util.uid(), "text": f"Ошибка: {e}"})
    finally:
        try:
            gitops.post_task(text)
        except Exception:
            pass
        if ap:
            state.AUTO, state.PLAN = prev_auto, prev_plan
            events.emit({"type": "auto", "value": state.AUTO})
        state.AP["on"] = False
        persist.save_chat()
        with state.LOCK:
            state.BUSY = False
        events.emit({"type": "busy", "value": False})
        events.emit({"type": "tree", "items": util.tree()})


def review_pass(text):
    files = []
    for pth in sorted(state.CHANGED):
        try:
            rel = pathlib.Path(pth).resolve().relative_to(state.WS).as_posix()
        except Exception:
            continue
        if not rel.startswith(".agent_"):
            files.append(rel)
    if not files:
        return
    prev = state.ACTIVE
    if state.ACTIVE.get("local") and "cloud" in config.profiles():
        state.ACTIVE = config.profiles()["cloud"]  # локальную работу проверяет облачная модель
    events.emit({"type": "engine", "label": config.engine_label()})
    events.add_item({"role": "note", "id": util.uid(), "text": "🔎 Проверяющий проход: " + config.engine_label()})
    state.MESSAGES.append({"role": "user", "content": prompts.REVIEW_PROMPT.format(task=text.strip()[:500], files=", ".join(files[:30]))})
    try:
        run_turn()
    finally:
        state.ACTIVE = prev


def run_body(text):
    if state.AP["on"]:
        autopilot.autopilot_run(text)
    else:
        run_turn()
        if state.CFG.get("verify") and state.CHANGED and not state.CANCEL.is_set():
            review_pass(text)
