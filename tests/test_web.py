# -*- coding: utf-8 -*-
"""Веб-интерфейс: файлы страницы, синтаксис скриптов, предпросмотр и его защита."""
import json
import pathlib
import re
import shutil
import subprocess
import unittest
import urllib.error
import urllib.request

from tests.fakes import FakeLLM
from tests.harness import AgentCase, ROOT

WEB = ROOT / "pcagent" / "web"


class StaticFiles(unittest.TestCase):
    def test_all_elements_used_by_script_exist_in_page(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        js = (WEB / "app.js").read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([\w-]+)"', page))
        used = set(re.findall(r"\$\('#([\w-]+)'\)", js)) | {u.lstrip("#") for u in re.findall(r"\['(#[\w-]+)'", js)}
        self.assertEqual(sorted(used - ids), [], "скрипт обращается к несуществующим элементам")
        dups = [i for i in ids if page.count(f'id="{i}"') > 1]
        self.assertEqual(dups, [], "повторяющиеся id")
        self.assertIn("__TOKEN__", page)
        self.assertIn("/static/app.js", page)

    @unittest.skipUnless(shutil.which("node"), "node не установлен")
    def test_javascript_syntax(self):
        r = subprocess.run(["node", "--check", str(WEB / "app.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_module_imports_on_its_own(self):
        """Модули ссылаются друг на друга по кругу: каждый должен загружаться и в одиночку."""
        for f in sorted((ROOT / "pcagent").glob("*.py")):
            if f.stem == "__init__":
                continue
            r = subprocess.run([__import__("sys").executable, "-c", f"import pcagent.{f.stem}"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{f.stem}: {r.stderr[-300:]}")

    def test_registry_is_consistent(self):
        from pcagent import registry, routes
        tools = {t["function"]["name"] for t in registry.TOOLS}
        self.assertTrue(tools <= set(registry.IMPL), "у инструмента нет реализации: " + str(tools - set(registry.IMPL)))
        for name, fn in routes.ROUTES.items():
            self.assertTrue(callable(fn), name)
        self.assertGreaterEqual(len(routes.ROUTES), 40)


class Server(AgentCase):
    def test_static_serving_and_traversal(self):
        a = self.start()
        for name, ctype in (("app.js", "javascript"), ("style.css", "text/css")):
            r = urllib.request.urlopen(f"{a.base}/static/{name}")
            self.assertEqual(r.status, 200)
            self.assertIn(ctype, r.headers["Content-Type"])
        for bad in ("../state.py", "other.py", "..%2fstate.py"):
            with self.assertRaises(urllib.error.HTTPError, msg=bad) as ctx:
                urllib.request.urlopen(f"{a.base}/static/{bad}")
            self.assertEqual(ctx.exception.code, 404)
        page = urllib.request.urlopen(a.base + "/").read().decode()
        self.assertNotIn("__TOKEN__", page)

    def test_preview_injects_error_catcher_and_blocks_traversal(self):
        llm = self.serve(FakeLLM("x"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})
        self.cloud(a, llm, "script")
        a.post("auto", {"value": True})
        a.clear()
        a.post("chat", {"message": "сделай страницу"})
        self.assertTrue(a.wait_idle())
        url = a.items("link")[0]["url"]
        page = urllib.request.urlopen(url).read().decode()
        self.assertIn("/__log", page, "перехватчик ошибок не вставлен")
        base = "/".join(url.split("/")[:3])
        req = urllib.request.Request(base + "/__log", data=json.dumps({"m": "TypeError: x"}).encode(), method="POST")
        self.assertEqual(urllib.request.urlopen(req).status, 204)
        self.assertTrue(a.wait(lambda: any(e["type"] == "preview_errors" and e["count"] == 1 for e in a.events)))
        for bad in ("/..%2f..%2fetc/passwd", "/%2e%2e/%2e%2e/etc/passwd"):
            with self.assertRaises(urllib.error.HTTPError, msg=bad) as ctx:
                urllib.request.urlopen(base + bad)
            self.assertIn(ctx.exception.code, (403, 404))
        # чужой сайт не может слать «ошибки» с другого адреса
        req = urllib.request.Request(base + "/__log", data=b'{"m":"x"}', method="POST", headers={"Origin": "http://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
