# -*- coding: utf-8 -*-
"""Telegram-бот: привязка по коду, задания, кнопки подтверждения, файлы (сервер Telegram подставной)."""
import os
import unittest

from tests.fakes import FakeLLM, FakeTelegram
from tests.harness import AgentCase


class Telegram(AgentCase):
    def test_pairing_task_buttons_and_files(self):
        tg = self.serve(FakeTelegram())
        llm = self.serve(FakeLLM("x"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1", "PC_AGENT_TG_BASE": f"http://127.0.0.1:{tg.port}"})
        self.cloud(a, llm)
        self.assertEqual(a.post("tg_setup", {"token": ""}).get("_status"), 400)
        r = a.post("tg_setup", {"token": "123:ABC"})
        self.assertTrue(r["on"])
        self.assertEqual(r["bot"], "testbot")

        tg.message(222, "привет")                                  # чужой чат
        self.assertTrue(a.wait(lambda: any("Нет доступа" in t for t in tg.texts())))
        tg.message(222, "/pair 000000")                            # неверный код
        tg.message(111, "/pair " + r["pair"])                      # верный
        self.assertTrue(a.wait(lambda: any("Подключено" in t for t in tg.texts())))
        self.assertEqual(a.post("tg_status")["chats"], 1)
        self.assertFalse(any("Подключено" in t for t in tg.texts()[:2]), "чужой чат не должен подключиться")

        tg.sent.clear()
        tg.message(111, "создай заметку")
        self.assertTrue(a.wait(lambda: any("Записать файл" in s["text"] for s in tg.sent)))
        ask = [s for s in tg.sent if "Записать файл" in s["text"]][0]
        buttons = [b["text"] for b in ask["reply_markup"]["inline_keyboard"][0]]
        self.assertEqual(buttons, ["✅ Разрешить", "♾ Всегда", "⛔ Нет"])
        self.assertFalse(os.path.exists(os.path.join(self.ws, "notes.txt")))
        tg.callback(111, ask["reply_markup"]["inline_keyboard"][0][0]["callback_data"])
        self.assertTrue(a.wait(lambda: any("Заметка готова" in t for t in tg.texts())))
        self.assertTrue(os.path.exists(os.path.join(self.ws, "notes.txt")))
        self.assertTrue(any(t.startswith("⚙ Запись файла") for t in tg.texts()), "нет сводки действий")

        tg.sent.clear()
        tg.message(111, "/files")
        self.assertTrue(a.wait(lambda: tg.sent))
        self.assertIn("notes.txt", tg.sent[-1]["text"])
        tg.message(111, "/get notes.txt")
        self.assertTrue(a.wait(lambda: tg.docs))
        self.assertIn(b"notes.txt", tg.docs[0])
        tg.sent.clear()
        tg.message(111, "/get ../../etc/passwd")
        self.assertTrue(a.wait(lambda: tg.sent))
        self.assertIn("Не нашёл", tg.sent[-1]["text"])

    def test_denied_confirmation_creates_nothing(self):
        tg = self.serve(FakeTelegram())
        llm = self.serve(FakeLLM("x"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1", "PC_AGENT_TG_BASE": f"http://127.0.0.1:{tg.port}"})
        self.cloud(a, llm)
        pair = a.post("tg_setup", {"token": "1:A"})["pair"]
        tg.message(5, "/pair " + pair)
        a.wait(lambda: any("Подключено" in t for t in tg.texts()))
        tg.sent.clear()
        tg.message(5, "создай заметку")
        a.wait(lambda: any("Записать файл" in s["text"] for s in tg.sent))
        ask = [s for s in tg.sent if "Записать файл" in s["text"]][0]
        tg.callback(5, ask["reply_markup"]["inline_keyboard"][0][2]["callback_data"])       # «Нет»
        self.assertTrue(a.wait_idle())
        self.assertFalse(os.path.exists(os.path.join(self.ws, "notes.txt")))


if __name__ == "__main__":
    unittest.main()
