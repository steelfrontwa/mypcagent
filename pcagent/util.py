# -*- coding: utf-8 -*-
"""Мелкие общие функции: безопасные пути, чтение файлов, дерево папки, id."""
import socket
import uuid

from . import state


SKIP_DIRS = {".agent_shots", ".git", "node_modules", "__pycache__", ".venv", "venv",
             ".agent_backup", ".agent_trash", ".idea", ".vscode"}


BAD_OPEN = {".exe", ".bat", ".cmd", ".ps1", ".msi", ".scr", ".vbs", ".lnk", ".com", ".jar", ".sh"}


def lan_ip():
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.connect(("10.255.255.255", 1))
        ip = sk.getsockname()[0]
        sk.close()
        return ip
    except Exception:
        return "127.0.0.1"


def uid():
    return uuid.uuid4().hex[:8]


def tree(max_depth=3, limit=400):
    out = []

    def walk(d, depth):
        try:
            entries = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except Exception:
            return
        for e in entries:
            if e.name in SKIP_DIRS or e.name.startswith("."):
                continue
            if len(out) >= limit:
                return
            rel = e.relative_to(state.WS).as_posix()
            out.append({"p": rel, "d": e.is_dir(), "depth": depth})
            if e.is_dir() and depth < max_depth:
                walk(e, depth + 1)

    walk(state.WS, 0)
    return out


# ---------- инструменты ----------
def safe(p):
    full = (state.WS / p).resolve()
    if not (full == state.WS or full.is_relative_to(state.WS)):
        raise ValueError("Путь за пределами рабочей папки запрещён: " + str(p))
    return full


def read_text(path):
    raw = path.read_bytes()
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace"), "utf-8"


class Lazy(dict):
    """Словарь, который наполняется при первом обращении (чтобы модули могли ссылаться друг на друга по кругу)."""

    def __init__(self, builder):
        super().__init__()
        self._builder = builder
        self._ready = False

    def _load(self):
        if not self._ready:
            self._ready = True
            self.update(self._builder())

    def __getitem__(self, k):
        self._load()
        return super().__getitem__(k)

    def __contains__(self, k):
        self._load()
        return super().__contains__(k)

    def get(self, k, default=None):
        self._load()
        return super().get(k, default)

    def __iter__(self):
        self._load()
        return super().__iter__()

    def __len__(self):
        self._load()
        return super().__len__()

    def keys(self):
        self._load()
        return super().keys()
