# -*- coding: utf-8 -*-
"""Автопилот: агент работает сам, без вопросов к пользователю."""
import pathlib

from . import agent, browser, config, events, gitops, pagepreview, state, util


def autopilot_main_page():
    htmls = []
    for pth in sorted(state.CHANGED):
        try:
            rel = pathlib.Path(pth).resolve().relative_to(state.WS).as_posix()
        except Exception:
            continue
        if rel.lower().endswith((".html", ".htm")) and not rel.startswith(".agent_"):
            htmls.append(rel)
    return next((h for h in htmls if h.lower().endswith("index.html")), htmls[0] if htmls else "")


def autopilot_check():
    main = autopilot_main_page()
    if not main:
        return ""
    res = browser.t_check_page(main)
    if "Автопроверка недоступна" in res:
        return ""
    if any(k in res for k in ("ОШИБКИ", "пустая", "несуществующие", "не загрузилась")):
        return res
    return ""


def last_assistant():
    return next((m for m in reversed(state.MESSAGES) if m["role"] == "assistant"), {})


def autopilot_run(text):
    if state.ACTIVE.get("local") and "cloud" not in config.profiles():
        events.add_item({"role": "note", "id": util.uid(),
                  "text": "ℹ Большие задачи (игры целиком) лучше всего получаются у облачной модели; маленькие локальные модели могут не справиться."})
    agent.run_turn(max_steps=150)
    asks = 0
    for rnd in range(6):
        if state.CANCEL.is_set():
            return
        last = last_assistant()
        if asks < 2 and not last.get("tool_calls") and (last.get("content") or "").rstrip().endswith("?"):
            asks += 1
            state.MESSAGES.append({"role": "user", "content": "[АВТОПИЛОТ] Пользователя нет рядом, ответов не будет. Прими решение сам, "
                                                         "доведи работу до конца и проверь её."})
            agent.run_turn(max_steps=100)
            continue
        problems = autopilot_check()
        if not problems:
            break
        events.add_item({"role": "note", "id": util.uid(), "text": f"🔁 Автопилот: проверка нашла проблемы, исправляю (попытка {rnd + 1}/6)"})
        state.MESSAGES.append({"role": "user", "content": "[АВТОПИЛОТ] Автопроверка нашла проблемы:\n" + problems +
                         "\nИсправь их, затем снова проверь страницу (check_page)."})
        agent.run_turn(max_steps=80)
    if state.CFG.get("verify") and state.CHANGED and not state.CANCEL.is_set():
        agent.review_pass(text)
    main = autopilot_main_page()
    if main and not state.CANCEL.is_set():
        pagepreview.t_open_preview(main)
    if state.AP["publish"] and not state.CANCEL.is_set():
        url = state.CFG.get("publish", {}).get(str(state.WS), {}).get("url")
        if url:
            ok, msg = gitops.do_publish()
            events.add_item({"role": "note" if ok else "error", "id": util.uid(),
                      "text": ("🚀 Опубликовано. " if ok else "Публикация не удалась: ") + msg[:300]})
        else:
            events.add_item({"role": "note", "id": util.uid(), "text": "Публикация пропущена: не указан адрес репозитория (кнопка «🕘 История и публикация»)."})
    state.AP["publish"] = False
