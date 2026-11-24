# -*- coding: utf-8 -*-
"""Команды интерфейса: Telegram."""
import secrets
import time

from . import config, state, telegram


def api_tg_status(b):
    return telegram.tg_info(), 200


def api_tg_setup(b):
    token = str(b.get("token", "")).strip()
    if not token:
        return {"error": "Вставь токен бота."}, 400
    try:
        me = telegram.tg_call("getMe", token=token, timeout=15)
        if not me.get("ok"):
            raise ValueError
    except Exception:
        return {"error": "Токен не подошёл или нет связи с Telegram."}, 400
    old = telegram.tg_conf()
    same = old.get("token") == token
    telegram.tg_stop()
    state.CFG["telegram"] = {"token": token, "bot": me["result"].get("username", ""),
                       "chats": old.get("chats", []) if same else [],
                       "pair": old.get("pair") if same and old.get("pair") else "".join(secrets.choice("0123456789") for _ in range(6))}
    config.save_cfg()
    time.sleep(0.3)
    telegram.tg_start()
    return telegram.tg_info(), 200


def api_tg_off(b):
    telegram.tg_stop()
    state.CFG.pop("telegram", None)
    config.save_cfg()
    return telegram.tg_info(), 200
