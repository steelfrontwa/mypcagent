# -*- coding: utf-8 -*-
"""Автопроверка страниц и скриншоты (скрытый браузер заменён тестовым скриптом)."""
import os
import unittest
from unittest import mock

from pcagent import browser, state
from tests.harness import FAKE_BROWSER
from tests.unit_base import UnitCase


class Browser(UnitCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"PC_AGENT_BROWSER": FAKE_BROWSER})
        p.start()
        self.addCleanup(p.stop)
        (self.ws / "index.html").write_text("<html><head><title>Игра</title></head><body><canvas></canvas><script src='game.js'></script></body></html>", encoding="utf-8")
        (self.ws / "boom.html").write_text("<html><head><title>B</title></head><body><p>x</p></body></html>", encoding="utf-8")
        (self.ws / "empty.html").write_text("<html><head><title>X</title></head><body></body></html>", encoding="utf-8")

    def test_missing_script_is_reported(self):
        out = browser.t_check_page("index.html")
        self.assertIn("title: Игра", out)
        self.assertIn("game.js", out)
        self.assertIn("ОШИБКИ", out)

    def test_javascript_errors_from_page_and_console_are_collected(self):
        out = browser.t_check_page("boom.html")
        self.assertIn("ReferenceError: foo is not defined", out)
        self.assertIn("Uncaught TypeError: bar is null", out)

    def test_empty_page_is_flagged(self):
        out = browser.t_check_page("empty.html")
        self.assertIn("пустая", out)

    def test_no_browser_gives_a_clear_message(self):
        with mock.patch.dict(os.environ, {"PC_AGENT_BROWSER": ""}), mock.patch.object(browser, "find_browser", return_value=None):
            self.assertIn("недоступна", browser.t_check_page("index.html"))

    def test_screenshot_with_and_without_vision(self):
        state.ACTIVE = {"model": "qwen2.5vl:7b"}
        self.assertIn("придёт тебе следующим сообщением", browser.t_screenshot_page("index.html"))
        self.assertEqual(len(state.PENDING_IMAGES), 1)
        browser.add_image_messages()
        msg = state.MESSAGES[-1]
        self.assertEqual([p["type"] for p in msg["content"]], ["text", "image_url"])
        state.ACTIVE = {"model": "deepseek-chat"}
        self.assertIn("не умеет смотреть картинки", browser.t_screenshot_page("index.html"))
        self.assertEqual(len(os.listdir(self.ws / ".agent_shots")), 2)

    def test_vision_guess_and_override(self):
        self.assertFalse(browser.profile_vision({"model": "deepseek-chat"}))
        self.assertTrue(browser.profile_vision({"model": "llava:7b"}))
        self.assertTrue(browser.profile_vision({"model": "x", "vision": True}))
        self.assertFalse(browser.profile_vision({"model": "llava:7b", "vision": False}))


if __name__ == "__main__":
    unittest.main()
