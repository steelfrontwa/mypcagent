# -*- coding: utf-8 -*-
"""Команды интерфейса: история версий и публикация."""
import re

from . import config, events, fileops, gitops, state, util


def api_history(b):
    return gitops.history_info(), 200


def api_git_init(b):
    err = gitops.git_init()
    return ({"error": err}, 400) if err else (gitops.history_info(), 200)


def api_git_auto(b):
    state.CFG.setdefault("autocommit", {})[str(state.WS)] = bool(b.get("value"))
    config.save_cfg()
    return {"ok": True}, 200


def api_restore(b):
    h = str(b.get("hash", ""))
    if state.BUSY:
        return {"error": "Сначала останови агента."}, 409
    if not gitops.is_repo() or not re.fullmatch(r"[0-9a-f]{4,40}", h):
        return {"error": "Неверный запрос."}, 400
    gitops.git_commit("Перед откатом")
    code, out = gitops.git("diff", "--name-only", "-z", "--diff-filter=A", h, "HEAD")
    for name in [n for n in out.split("\0") if n]:
        f = (state.WS / name)
        try:
            f = f.resolve()
            if f.is_relative_to(state.WS) and f.is_file():
                fileops.trash_move(f)
        except Exception:
            pass
    code, out = gitops.git("checkout", h, "--", ".")
    if code != 0:
        return {"error": out[-300:]}, 400
    gitops.git_commit("Откат к " + h)
    events.add_item({"role": "note", "id": util.uid(), "text": f"↩ Проект возвращён к версии {h}"})
    events.emit({"type": "tree", "items": util.tree()})
    return gitops.history_info(), 200


def api_publish_save(b):
    state.CFG.setdefault("publish", {})[str(state.WS)] = {"url": str(b.get("url", "")).strip(), "branch": str(b.get("branch", "")).strip()}
    config.save_cfg()
    return {"ok": True}, 200


def api_publish(b):
    if state.BUSY:
        return {"error": "Сначала останови агента."}, 409
    api_publish_save(b)
    ok, msg = gitops.do_publish()
    events.add_item({"role": "note" if ok else "error", "id": util.uid(), "text": ("🚀 Опубликовано. " if ok else "Публикация не удалась: ") + msg[:300]})
    return ({"ok": True, "msg": msg}, 200) if ok else ({"error": msg}, 400)
