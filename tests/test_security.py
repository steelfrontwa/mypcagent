# -*- coding: utf-8 -*-
"""Безопасность: границы рабочей папки, вход по PIN, доступ без токена."""
import json
import os
import re
import unittest
import urllib.error
import urllib.request

from pcagent import api_core, fileops, state, util
from tests.harness import AgentCase
from tests.unit_base import UnitCase


class Paths(UnitCase):
    def test_paths_outside_workspace_are_rejected(self):
        for bad in ("../x.txt", "../../etc/passwd", "/etc/passwd", "a/../../b"):
            with self.assertRaises(ValueError, msg=bad):
                util.safe(bad)
        self.assertEqual(util.safe("sub/ok.txt"), state.WS / "sub" / "ok.txt")

    def test_tools_never_touch_files_outside(self):
        outside = self.tmp / "secret.txt"
        outside.write_text("секрет")
        from pcagent import registry
        self.assertIn("Ошибка", registry.call_tool("list_dir", {"path": "../"}))
        self.assertIn("Ошибка", registry.call_tool("read_file", {"path": "../secret.txt"}))
        self.assertIn("Ошибка", registry.call_tool("write_file", {"path": "../hacked.txt", "content": "x"}))
        self.assertFalse((self.tmp / "hacked.txt").exists())
        self.assertEqual(outside.read_text(), "секрет")

    def test_open_refuses_executables(self):
        (self.ws / "run.bat").write_text("echo hi")
        r, code = api_core.api_open({"path": "run.bat"})
        self.assertEqual(code, 400)

    def test_undo_refuses_files_outside_workspace(self):
        state.UNDO["x"] = {"kind": "file", "path": str(self.tmp / "outside.txt"), "bak": None}
        self.assertIn("вне рабочей папки", fileops.do_undo("x"))

    def test_edit_requires_unique_match(self):
        state.AUTO = True
        (self.ws / "a.txt").write_text("a a")
        self.assertIn("2 раз", fileops.t_edit_file("a.txt", "a", "b"))
        self.assertEqual((self.ws / "a.txt").read_text(), "a a")


class LanMode(AgentCase):
    def _req(self, a, path, data=None, headers=None):
        r = urllib.request.Request(a.base + path, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
        try:
            resp = urllib.request.urlopen(r)
            return resp.status, resp.read().decode(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), e.headers

    def test_pin_login_cookie_and_lockout(self):
        a = self.start(args=("--lan",))
        pin = re.search(r"PIN-код: (\d{6})", "\n".join(a.lines)).group(1)
        code, body, _ = self._req(a, "/")
        self.assertEqual(code, 200)
        self.assertIn("PIN-код", body)
        self.assertNotIn("const TOKEN", body, "страница приложения не должна отдаваться без входа")
        self.assertEqual(self._req(a, "/api/chat", b"{}", {"X-Token": "x"})[0], 403)
        self.assertIn(self._req(a, "/static/app.js")[0], (403, 404), "файлы интерфейса не отдаются без входа")
        code, body, h = self._req(a, "/login", json.dumps({"pin": pin}).encode())
        self.assertEqual(code, 200)
        flags = h["Set-Cookie"]
        self.assertIn("HttpOnly", flags)
        self.assertIn("SameSite=Strict", flags)
        cookie = flags.split(";")[0]
        code, page, _ = self._req(a, "/", headers={"Cookie": cookie})
        self.assertIn("const TOKEN", page)
        token = re.search(r'const TOKEN="([^"]+)"', page).group(1)
        self.assertEqual(self._req(a, "/api/mode", b"{}", {"Cookie": cookie, "X-Token": token})[0], 200)
        self.assertEqual(self._req(a, "/api/mode", b"{}", {"X-Token": token})[0], 403, "токен без cookie не должен работать")
        self.assertEqual(self._req(a, "/api/mode", b"{}", {"Cookie": cookie})[0], 403, "cookie без токена не должен работать")
        # перебор PIN: после 5 ошибок вход блокируется, даже с верным кодом
        for _ in range(5):
            self._req(a, "/login", json.dumps({"pin": "000000" if pin != "000000" else "111111"}).encode())
        self.assertEqual(self._req(a, "/login", json.dumps({"pin": pin}).encode())[0], 429)

    def test_localhost_mode_rejects_foreign_host_header(self):
        a = self.start()
        code, _, _ = self._req(a, "/", headers={"Host": "evil.example.com"})
        self.assertEqual(code, 403, "защита от подмены адреса (DNS rebinding)")
        self.assertEqual(self._req(a, "/api/chat", b"{}", {})[0], 403, "без токена команды не принимаются")


if __name__ == "__main__":
    unittest.main()
