# -*- coding: utf-8 -*-
"""Файловые инструменты агента: чтение, запись, правка, перемещение, удаление, откат."""
import os
import pathlib
import re
import shutil
import threading
import time
from datetime import datetime

from . import docs, events, state, util


def backup(path):
    if path.exists() and path.is_file():
        d = state.WS / ".agent_backup"
        d.mkdir(exist_ok=True)
        dst = d / f"{path.name}.{datetime.now():%Y%m%d-%H%M%S-%f}.bak"
        shutil.copy2(path, dst)
        return dst
    return None


def set_undo(rec):
    for k in ("path", "dst", "src", "orig"):
        if k in rec:
            state.CHANGED.add(rec[k])
    rid = util.uid()
    state.UNDO[rid] = rec
    state.LAST_UNDO[0] = rid


def trash_move(f):
    trash = state.WS / ".agent_trash"
    trash.mkdir(exist_ok=True)
    dst = trash / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{f.name}"
    shutil.move(str(f), str(dst))
    return dst


def confirm(title, detail="", force=False):
    if state.AUTO and not force:
        return True
    cid = util.uid()
    ev = threading.Event()
    state.PENDING[cid] = {"ev": ev, "ans": "no"}
    events.add_item({"role": "confirm", "id": cid, "title": title, "detail": detail[:1500], "state": "pending"})
    started = time.time()
    while not ev.wait(0.4):
        if state.CANCEL.is_set():
            state.PENDING.pop(cid, None)
            events.patch_item(cid, {"state": "no"})
            raise state.Cancelled()
        if state.SCHED["active"] and time.time() - started > 600:  # без присмотра: через 10 минут отказ
            state.PENDING[cid]["ans"] = "no"
            break
    ans = state.PENDING.pop(cid)["ans"]
    if ans == "always" and not force:
        state.AUTO = True
        events.emit({"type": "auto", "value": True})
    ok = ans in ("yes", "always")
    events.patch_item(cid, {"state": "yes" if ok else "no"})
    return ok


def t_list_dir(path="."):
    d = util.safe(path)
    if not d.is_dir():
        return "Это не папка: " + path
    out = []
    for e in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:300]:
        if e.name in util.SKIP_DIRS:
            continue
        out.append(f"[папка] {e.name}" if e.is_dir() else f"{e.name}  ({e.stat().st_size} байт)")
    return "\n".join(out) or "(пусто)"


def t_read_file(path, start_line=None, end_line=None):
    f = util.safe(path)
    if not f.is_file():
        return "Файл не найден: " + path
    if f.suffix.lower() in docs.DOC_EXT:
        return docs.t_read_document(path)
    text, _ = util.read_text(f)
    if start_line or end_line:
        lines = text.splitlines()
        s, e = (start_line or 1) - 1, end_line or len(lines)
        text = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines[s:e], start=s))
    if len(text) > 30000:
        text = text[:30000] + "\n...[обрезано, используй start_line/end_line]"
    return text


def t_write_file(path, content):
    f = util.safe(path)
    if not confirm(f"Записать файл {path} ({len(content)} символов)", content[:800]):
        return "Пользователь отклонил."
    bak = backup(f)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    set_undo({"kind": "file", "path": str(f), "bak": str(bak) if bak else None})
    return f"Записано: {path}"


def t_edit_file(path, old, new):
    f = util.safe(path)
    if not f.is_file():
        return "Файл не найден: " + path
    text, enc = util.read_text(f)
    n = text.count(old)
    if n != 1:
        return f"Ошибка: фрагмент найден {n} раз(а), нужно ровно 1. Уточни old."
    if not confirm(f"Изменить {path}", f"- {old[:500]}\n+ {new[:500]}"):
        return "Пользователь отклонил."
    bak = backup(f)
    f.write_text(text.replace(old, new), encoding=enc)
    set_undo({"kind": "file", "path": str(f), "bak": str(bak) if bak else None})
    return "Изменено: " + path


def t_make_dir(path):
    util.safe(path).mkdir(parents=True, exist_ok=True)
    return "Папка создана: " + path


def t_move_file(src, dst):
    s, d = util.safe(src), util.safe(dst)
    if not confirm(f"Переместить {src} → {dst}"):
        return "Пользователь отклонил."
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    set_undo({"kind": "move", "src": str(s), "dst": str(d)})
    return f"Перемещено: {src} → {dst}"


def t_delete_file(path):
    f = util.safe(path)
    if not f.exists():
        return "Не найдено: " + path
    if not confirm(f"Удалить {path} (уйдёт в .agent_trash)", force=True):
        return "Пользователь отклонил."
    tp = trash_move(f)
    set_undo({"kind": "trash", "orig": str(f), "trash": str(tp)})
    return "Удалено в корзину агента: " + path


def t_search(pattern, path="."):
    rx = re.compile(pattern, re.I)
    out = []
    for root, dirs, files in os.walk(util.safe(path)):
        dirs[:] = [d for d in dirs if d not in util.SKIP_DIRS]
        for name in files:
            p = pathlib.Path(root) / name
            try:
                if p.stat().st_size > 1_000_000:
                    continue
                text, _ = util.read_text(p)
                if "\0" in text:
                    continue
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    out.append(f"{p.relative_to(state.WS)}:{i}: {line.strip()[:200]}")
                    if len(out) >= 100:
                        return "\n".join(out) + "\n...[первые 100 совпадений]"
    return "\n".join(out) or "Ничего не найдено."


def do_undo(rid):
    rec = state.UNDO.get(rid)
    if not rec:
        return "Нечего отменять."
    for key in ("path", "src", "dst", "orig"):
        if key in rec:
            pp = pathlib.Path(rec[key]).resolve()
            if not (pp == state.WS or pp.is_relative_to(state.WS)):
                return "Файл вне рабочей папки."
    k = rec["kind"]
    if k == "file":
        f = pathlib.Path(rec["path"])
        if rec["bak"]:
            shutil.copy2(rec["bak"], f)
        elif f.exists():
            trash_move(f)
    elif k == "move":
        a, b_ = pathlib.Path(rec["src"]), pathlib.Path(rec["dst"])
        if not b_.exists() or a.exists():
            return "Не получилось: исходное место занято или файл уже перемещён."
        a.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(b_), str(a))
    elif k == "trash":
        o, t = pathlib.Path(rec["orig"]), pathlib.Path(rec["trash"])
        if not t.exists() or o.exists():
            return "Не получилось: файл уже восстановлен или место занято."
        o.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(t), str(o))
    state.UNDO.pop(rid, None)
    if rec.get("item"):
        events.patch_item(rec["item"], {"undo": None, "undone": True})
    events.emit({"type": "tree", "items": util.tree()})
    return None
