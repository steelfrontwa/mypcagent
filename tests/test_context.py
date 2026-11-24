# -*- coding: utf-8 -*-
"""Управление контекстом: сжатие длинного чата, запасной конспект, обнаружение обрезки в Ollama."""
import json

from pcagent import context, llm, prompts, state
from tests.fakes import FakeLLM
from tests.unit_base import UnitCase


def long_history(n=40):
    ms = [{"role": "system", "content": "SYS"}]
    for i in range(n):
        ms.append({"role": "user", "content": f"задача {i}: сделай файл f{i}.js"})
        ms.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": f"f{i}.js", "content": "код " * 400})}}]})
        ms.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"Записано: f{i}.js"})
        ms.append({"role": "assistant", "content": f"Готово {i}. " + "текст " * 60})
    return ms


def pairs_valid(ms):
    """Каждый результат инструмента должен идти сразу после вызова с тем же id (иначе API откажет)."""
    ids = set()
    for m in ms:
        if m["role"] == "assistant" and m.get("tool_calls"):
            ids = {tc["id"] for tc in m["tool_calls"]}
        if m["role"] == "tool" and m["tool_call_id"] not in ids:
            return False
    return True


class Context(UnitCase):
    def setUp(self):
        super().setUp()
        self.llm = FakeLLM("t")
        self.addCleanup(self.llm.close)
        state.ACTIVE = {"model": "native", "base_url": f"http://127.0.0.1:{self.llm.port}", "api_key": "k",
                        "local": True, "ctx": 6000}
        (self.ws / "index.html").write_text("x")

    def test_compaction_keeps_structure_and_facts(self):
        state.MESSAGES[:] = long_history()
        before = context.est_tokens()
        self.assertGreater(before, 6000 * 0.7)
        context.manage_context()
        after = context.est_tokens()
        self.assertLess(after, 6000 * 0.7)
        self.assertTrue(pairs_valid(state.MESSAGES), "после сжатия остались осиротевшие результаты инструментов")
        summary = state.MESSAGES[1]
        self.assertEqual(summary["role"], "user")
        for fragment in ("змейка", "f0.js", "read_file", "index.html"):   # конспект модели, файлы, напоминание, дерево папки
            self.assertIn(fragment, summary["content"])
        self.assertEqual(state.MESSAGES[-1]["content"][:9], "Готово 39")   # свежее не потеряно
        roles = [m["role"] for m in state.MESSAGES]
        self.assertNotIn(("assistant", "assistant"), list(zip(roles, roles[1:]))[:2])
        self.assertTrue(any("История сжата" in n for n in self.notes()))

    def test_fallback_summary_when_model_is_down(self):
        state.ACTIVE["base_url"] = "http://127.0.0.1:9"          # никто не слушает
        state.MESSAGES[:] = long_history()
        context.manage_context()
        self.assertTrue(pairs_valid(state.MESSAGES))
        self.assertIn("подробный конспект составить не удалось", state.MESSAGES[1]["content"])
        self.assertLess(context.est_tokens(), 6000 * 0.7)

    def test_short_chat_is_left_alone(self):
        state.ACTIVE["ctx"] = 20000                      # реальное окно модели; 6000 слишком мало даже для инструкций
        state.MESSAGES[:] = long_history(2)
        n = len(state.MESSAGES)
        context.manage_context()
        self.assertEqual(len(state.MESSAGES), n)

    def test_old_file_contents_are_shrunk(self):
        state.MESSAGES[:] = long_history(10)
        context.shrink_old(keep=6)
        old_args = state.MESSAGES[2]["tool_calls"][0]["function"]["arguments"]
        self.assertLess(len(old_args), 600)
        self.assertIn("файл уже записан", old_args)

    def test_ollama_truncation_is_detected_and_budget_adjusted(self):
        state.ACTIVE = {"model": "trunc", "base_url": f"http://127.0.0.1:{self.llm.port}", "api_key": "k", "local": True}
        state.MESSAGES[:] = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "привет " * 5000}]
        llm.chat_stream()
        self.assertEqual(state.ACTIVE["ctx"], int(4090 * 0.85))
        self.assertTrue(any("OLLAMA_CONTEXT_LENGTH" in n for n in self.notes()))

    def test_project_map_is_in_system_prompt(self):
        self.assertIn("index.html", prompts.system_prompt())


if __name__ == "__main__":
    import unittest
    unittest.main()
