# -*- coding: utf-8 -*-
"""Автопилот: игра создаётся без вопросов к пользователю, ошибки находятся и исправляются."""
import os

from tests.fakes import FakeLLM
from tests.harness import AgentCase, FAKE_BROWSER


class Autopilot(AgentCase):
    def _run(self, model):
        llm = self.serve(FakeLLM())
        a = self.start(env={"PC_AGENT_NO_PROBE": "1", "PC_AGENT_BROWSER": FAKE_BROWSER})
        self.cloud(a, llm, model)
        a.clear()
        self.assertTrue(a.post("make_game", {"idea": "змейка", "genre": "Аркада"}).get("ok"))
        self.assertTrue(a.wait_idle(25), "автопилот не закончил")
        return a

    def _assert_done(self, a):
        tools = [(i["name"], i["args"].get("path")) for i in a.items("tool")]
        self.assertEqual(tools, [("write_file", "game/index.html"), ("write_file", "game/game.js")])
        self.assertEqual(a.items("confirm"), [], "автопилот не должен спрашивать разрешений")
        self.assertTrue(a.items("link"), "нет ссылки на предпросмотр")
        self.assertEqual(sorted(os.listdir(os.path.join(self.ws, "game"))), ["game.js", "index.html"])
        autos = [e["value"] for e in a.events if e["type"] == "auto"]
        self.assertEqual(autos, [True, False], "настройка «всё разрешено» должна вернуться на место")
        task = a.items("user")[0]["text"]
        self.assertIn("змейка", task)
        self.assertIn("Аркада", task)

    def test_answers_its_own_question_and_fixes_missing_file(self):
        a = self._run("game-ask")
        self._assert_done(a)
        self.assertIn("Хотите, чтобы я добавил музыку?", a.deltas())      # модель задала вопрос, а ответа не будет
        snapshot_auto = [e for e in a.events if e["type"] == "snapshot"]
        self.assertFalse(snapshot_auto and snapshot_auto[-1]["auto"])

    def test_check_finds_broken_page_and_loops(self):
        a = self._run("game")
        self._assert_done(a)
        self.assertTrue(any("проверка нашла проблемы" in n for n in a.notes()), a.notes())


if __name__ == "__main__":
    import unittest
    unittest.main()
