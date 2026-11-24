# -*- coding: utf-8 -*-
"""Общее изменяемое состояние программы.

Все модули обращаются сюда как state.ИМЯ (так присвоение вроде state.WS = ... видят все сразу).
Тяжёлой логики здесь нет — только данные.
"""
import pathlib
import secrets
import threading


class Cancelled(BaseException):
    """Пользователь нажал «Стоп». Наследуется от BaseException, чтобы «except Exception» её не глотал."""


# --- пути и настройки ---
CONF_DIR = pathlib.Path.home() / ".pc_agent"
CONF_FILE = CONF_DIR / "config.json"
CHATS_DIR = CONF_DIR / "chats"
CFG = {}                    # настройки: профили моделей, режимы, расписание, Telegram, цены...
WS = pathlib.Path.home()    # рабочая папка (агент не выходит за её пределы)

# --- сервер и доступ ---
TOKEN = secrets.token_urlsafe(24)   # секрет страницы: без него команды не принимаются
PORT = 0
LAN = False                 # доступ с телефона по сети
PIN = ""
SESSIONS = set()
FAILS = {}                  # неудачные попытки входа по адресам

# --- события для интерфейса ---
LOCK = threading.RLock()
SUBS = []                   # подписчики на события (открытые страницы, Telegram)
TRANSCRIPT = []             # что показано в чате (сообщения, карточки действий)
PENDING = {}                # ожидающие ответа подтверждения и планы
CANCEL = threading.Event()  # «Стоп»

# --- ход работы агента ---
MESSAGES = []               # история для модели
ACTIVE = {}                 # профиль модели, который работает сейчас
BUSY = False
AUTO = False                # «всё разрешено» (без подтверждений)
PLAN = False                # сначала показывать план
CURRENT_TASK = [""]
CHANGED = set()             # файлы, изменённые за текущее задание
USAGE = {"prompt": 0, "completion": 0, "cloud_prompt": 0, "cloud_completion": 0}
CTX = {"req": 0}            # оценка размера последнего запроса

# --- откат, предпросмотр, картинки ---
UNDO = {}
LAST_UNDO = [None]
PREVIEW = {"server": None, "port": 0}
PREVIEW_ERRORS = []
PENDING_IMAGES = []

# --- режимы и службы ---
AP = {"on": False, "oneoff": False, "publish": False}         # автопилот
SCHED = {"active": None}                                       # расписание
TG = {"stop": threading.Event(), "poll": None, "events": None, "chat": None,
      "tools": [], "texts": {}, "last": "", "order": []}       # Telegram-бот
_DOCKER = {"t": 0, "ok": False}                                # кэш проверки Docker
