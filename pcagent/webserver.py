# -*- coding: utf-8 -*-
"""HTTP-сервер интерфейса: страница, события, вход по PIN."""
import json
import os
import pathlib
import queue
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

from . import auth, events, routes, state, util


def web_dir():
    p = pathlib.Path(__file__).resolve().parent / "web"
    if not p.exists() and hasattr(sys, "_MEIPASS"):  # запуск из собранного .exe
        p = pathlib.Path(sys._MEIPASS) / "pcagent" / "web"
    return p


def load_page():
    return (web_dir() / "index.html").read_text(encoding="utf-8")


STATIC_TYPES = {"app.js": "application/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def host_ok(self):
        if state.LAN:
            return True
        return self.headers.get("Host", "") in (f"127.0.0.1:{state.PORT}", f"localhost:{state.PORT}")

    def authed(self):
        return (not state.LAN) or auth.session_ok(self.headers.get("Cookie"))

    def start_session(self):
        sid = secrets.token_urlsafe(24)
        state.SESSIONS.add(sid)
        return f"pcsid={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"

    def login(self):
        ip = self.client_address[0]
        now = time.time()
        fails = [t for t in state.FAILS.get(ip, []) if now - t < 300]
        if len(fails) >= 5:
            return self.send_json({"error": "Слишком много попыток. Подожди 5 минут."}, 429)
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 500)))
        except Exception:
            body = {}
        if state.LAN and secrets.compare_digest(str(body.get("pin", "")).strip(), state.PIN):
            data = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Set-Cookie", self.start_session())
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        fails.append(now)
        state.FAILS[ip] = fails
        self.send_json({"error": "Неверный PIN"}, 403)

    def send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if not self.host_ok():
            return self.send_error(403)
        if u.path == "/":
            cookie = None
            if state.LAN and not self.authed():
                if self.client_address[0] in ("127.0.0.1", "::1") and q.get("pin", [""])[0] == state.PIN:
                    cookie = self.start_session()  # автоматический вход на самом ПК
                else:
                    page = auth.LOGIN_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    return self.wfile.write(page)
            data = load_page().replace("__TOKEN__", state.TOKEN).encode("utf-8")
            self.send_response(200)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif u.path == "/api/events" and q.get("t", [""])[0] == state.TOKEN and self.authed():
            self.sse()
        elif u.path.startswith("/static/") and self.authed():
            name = os.path.basename(u.path)
            f = web_dir() / name
            if name not in STATIC_TYPES or not f.is_file():
                return self.send_error(404)
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", STATIC_TYPES[name])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        elif u.path.startswith("/shots/") and q.get("t", [""])[0] == state.TOKEN and self.authed():
            f = state.WS / ".agent_shots" / os.path.basename(urllib.parse.unquote(u.path))
            if not f.is_file():
                return self.send_error(404)
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue()
        with state.LOCK:
            state.SUBS.append(q)
            q.put(events.snapshot())
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                    self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except Exception:
            pass
        finally:
            with state.LOCK:
                if q in state.SUBS:
                    state.SUBS.remove(q)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/login":
            return self.login()
        if not self.host_ok() or not self.authed() or self.headers.get("X-Token") != state.TOKEN:
            return self.send_error(403)
        length = int(self.headers.get("Content-Length") or 0)
        if u.path == "/api/upload":
            if length > 50 * 1024 * 1024:
                return self.send_json({"error": "Файл больше 50 МБ."}, 400)
            name = os.path.basename(urllib.parse.parse_qs(u.query).get("name", ["file"])[0]) or "file"
            d = state.WS / "uploads"
            d.mkdir(exist_ok=True)
            (d / name).write_bytes(self.rfile.read(length))
            events.emit({"type": "tree", "items": util.tree()})
            return self.send_json({"path": "uploads/" + name})
        fn = routes.ROUTES.get(u.path[len("/api/"):]) if u.path.startswith("/api/") else None
        if not fn:
            return self.send_error(404)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}
        obj, code = fn(body)
        self.send_json(obj, code)
