# -*- coding: utf-8 -*-
"""Модель, которая не умеет вызывать функции: агент всё равно должен создавать файлы."""
import os

from tests.fakes import FakeLLM
from tests.harness import AgentCase


class DumbModel(AgentCase):
    def _task(self, a):
        a.post("auto", {"value": True})
        a.clear()
        a.post("chat", {"message": "создай файл notes.txt с приветом"})
        self.assertTrue(a.wait_idle(15))

    def test_probe_switches_to_text_mode(self):
        llm = self.serve(FakeLLM())
        a = self.start()                              # проверка модели включена
        self.cloud(a, llm, "dumb")
        self.assertTrue(a.wait(lambda: any("ТЕКСТОВЫЙ" in n for n in a.notes())), a.notes())
        self._task(a)
        self.assertEqual(open(os.path.join(self.ws, "notes.txt"), encoding="utf-8").read(), "привет")
        self.assertEqual([i["name"] for i in a.items("tool")], ["write_file"])
        # служебный блок вызова не должен остаться в тексте ответа
        patched = [e["patch"]["text"] for e in a.events if e["type"] == "update" and "text" in e["patch"]]
        self.assertTrue(patched and "```tool" not in patched[0])

    def test_nudge_then_text_mode_when_model_writes_instructions(self):
        llm = self.serve(FakeLLM())
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})    # без проверки: ловим по поведению
        self.cloud(a, llm, "dumb")
        self._task(a)
        self.assertTrue(os.path.exists(os.path.join(self.ws, "notes.txt")))
        self.assertTrue(any("текстовый режим" in n for n in a.notes()), a.notes())
        status = [e["engine"] for e in a.events if e["type"] == "busy" and e.get("engine")]
        self.assertTrue(status)


if __name__ == "__main__":
    import unittest
    unittest.main()
