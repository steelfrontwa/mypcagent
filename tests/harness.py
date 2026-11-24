# -*- coding: utf-8 -*-
"""Запуск настоящего агента в отдельном процессе и общение с ним по HTTP — как это делает браузер."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _make_fake_browser():
    """Подставной браузер должен запускаться как программа: на Windows через .bat, на Linux/macOS с правом запуска."""
    script = pathlib.Path(__file__).resolve().parent / "fakebrowser.py"
    if os.name == "nt":
        bat = pathlib.Path(tempfile.gettempdir()) / "pca_fake_browser.bat"
        bat.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return str(bat)
    os.chmod(script, 0o755)
    return str(script)


FAKE_BROWSER = _make_fake_browser()


class Agent:
    def __init__(self, ws, env=None, args=(), home=None):
        self.owns_home = home is None
        self.home = home or tempfile.mkdtemp(prefix="pca_home_")
        e = {**os.environ, "HOME": self.home, "USERPROFILE": self.home, "PC_AGENT_NO_BROWSER": "1",
             "PYTHONIOENCODING": "utf-8"}
        e.update(env or {})
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "agent_chat.py"), *args, str(ws)], env=e,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        self.lines = []
        self.port = None
        threading.Thread(target=self._read, daemon=True).start()
        end = time.time() + 15
        while self.port is None and time.time() < end:
            time.sleep(0.05)
        if self.port is None:
            self.stop()
            raise RuntimeError("агент не запустился:\n" + "\n".join(self.lines))
        self.base = f"http://127.0.0.1:{self.port}"
        self.events = []
        self.token = None
        if "--lan" not in args:
            self.connect()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())
            m = re.search(r"запущен: http://127\.0\.0\.1:(\d+)/", line)
            if m:
                self.port = int(m.group(1))

    def connect(self, cookie=None):
        req = urllib.request.Request(self.base + "/", headers={"Cookie": cookie} if cookie else {})
        page = urllib.request.urlopen(req).read().decode()
        self.token = re.search(r'const TOKEN="([^"]+)"', page).group(1)
        self.cookie = cookie
        threading.Thread(target=self._listen, daemon=True).start()
        self.wait(lambda: any(e["type"] == "snapshot" for e in self.events), 5)

    def _listen(self):
        try:
            req = urllib.request.Request(f"{self.base}/api/events?t={self.token}",
                                         headers={"Cookie": self.cookie} if self.cookie else {})
            for line in urllib.request.urlopen(req):
                line = line.decode().strip()
                if line.startswith("data:"):
                    self.events.append(json.loads(line[5:]))
        except Exception:
            pass

    def post(self, path, body=None):
        headers = {"X-Token": self.token or "", "Content-Type": "application/json"}
        if getattr(self, "cookie", None):
            headers["Cookie"] = self.cookie
        req = urllib.request.Request(f"{self.base}/api/{path}", data=json.dumps(body or {}).encode(), headers=headers)
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read())
            except Exception:
                out = {}
            out["_status"] = e.code
            return out

    def wait(self, pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.05)
        return False

    # --- удобные выборки по событиям ---
    def items(self, role):
        return [e["item"] for e in self.events if e["type"] == "item" and e["item"]["role"] == role]

    def notes(self):
        return [i["text"] for i in self.items("note")]

    def deltas(self):
        return "".join(e["delta"] for e in self.events if e["type"] == "delta")

    def idle(self):
        busy = [e for e in self.events if e["type"] == "busy"]
        return bool(busy) and busy[-1]["value"] is False

    def wait_idle(self, timeout=15):
        return self.wait(self.idle, timeout)

    def clear(self):
        self.events.clear()

    def stop(self, keep_home=False):
        if keep_home:
            self.owns_home = False
        try:
            self.proc.terminate()
            self.proc.wait(5)
        except Exception:
            self.proc.kill()
        if self.owns_home:
            shutil.rmtree(self.home, ignore_errors=True)


class AgentCase(unittest.TestCase):
    """Базовый класс: временная рабочая папка и вспомогательное завершение процессов."""

    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="pca_ws_")
        self._agents = []
        self._servers = []

    def tearDown(self):
        for a in self._agents:
            a.stop()
        for s in self._servers:
            s.close()
        shutil.rmtree(self.ws, ignore_errors=True)

    def start(self, **kw):
        a = Agent(kw.pop("ws", self.ws), **kw)
        self._agents.append(a)
        return a

    def serve(self, srv):
        self._servers.append(srv)
        return srv

    def cloud(self, agent, llm, model="native"):
        r = agent.post("setup", {"api_key": "sk-test", "base_url": f"http://127.0.0.1:{llm.port}", "model": model})
        self.assertTrue(r.get("ok"), r)
