# -*- coding: utf-8 -*-
"""Профили моделей (облако и локальная), режимы и сохранение настроек."""
import json
import re

from . import state, textmode


COMPLEX = re.compile(r"(сайт|игр|проект|приложен|рефактор|перепиш|архитектур|несколько файл|все файлы|исправь ошибк|бот|парс|скрипт|docx|xlsx|excel|word|pdf|презентац|отч[её]т)", re.I)


def profiles():
    return state.CFG.setdefault("profiles", {})


def fix_mode(added=None):
    p = profiles()
    if len(p) == 1:
        state.CFG["mode"] = next(iter(p))
    elif len(p) > 1 and (added or state.CFG.get("mode") not in ("auto", "cloud", "local")):
        state.CFG["mode"] = "auto"


def engine_label():
    return f"{state.ACTIVE.get('provider', '')} · {state.ACTIVE.get('model', '')}" + (" · текстовый режим" if textmode.tools_mode(state.ACTIVE) == "text" else "")


def choose_profile(text):
    p = profiles()
    if len(p) == 1:
        return next(iter(p.values()))
    mode = state.CFG.get("mode", "auto")
    if mode in p:
        return p[mode]
    complex_ = len(text) > 400 or bool(COMPLEX.search(text)) or len(state.MESSAGES) > 40 or state.AP["on"]
    return p["cloud"] if complex_ else p["local"]


def add_recent(path):
    r = [x for x in state.CFG.get("recent", []) if x != str(path)]
    r.insert(0, str(path))
    state.CFG["recent"] = r[:8]
    save_cfg()


def save_cfg():
    state.CONF_DIR.mkdir(exist_ok=True)
    state.CONF_FILE.write_text(json.dumps(state.CFG, indent=2, ensure_ascii=False), encoding="utf-8")
