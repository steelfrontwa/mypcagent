# -*- coding: utf-8 -*-
"""Предпросмотр страниц: локальный сервер и перехват ошибок JavaScript."""
import json
import mimetypes
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

from . import auth, events, state, util


# ---------- предпросмотр страниц ----------
PREVIEW_JS = """<script>(function(){function s(m){try{fetch('/__log',{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify({m:String(m).slice(0,500)})}).catch(function(){});}catch(e){}}
window.addEventListener('error',function(e){var t=e.target;if(t&&t!==window&&(t.src||t.href)){s('Не загрузился ресурс: '+(t.src||t.href));return;}
s((e.message||'Ошибка')+' ('+String(e.filename||'').split('/').pop()+':'+e.lineno+')');},true);
window.addEventListener('unhandledrejection',function(e){s('Promise: '+((e.reason&&e.reason.message)||e.reason));});
var ce=console.error;console.error=function(){s('console.error: '+Array.prototype.join.call(arguments,' '));ce.apply(console,arguments);};})();</script>"""


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def host_ok(self):
        if state.LAN:
            return auth.session_ok(self.headers.get("Cookie"))
        return self.headers.get("Host", "") in (f"127.0.0.1:{state.PREVIEW['port']}", f"localhost:{state.PREVIEW['port']}")

    def do_GET(self):
        if not self.host_ok():
            return self.send_error(403)
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        try:
            target = (state.WS / path.lstrip("/")).resolve()
            if not (target == state.WS or target.is_relative_to(state.WS)):
                return self.send_error(403)
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                return self.send_error(404)
            data = target.read_bytes()
        except Exception:
            return self.send_error(404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix.lower() in (".html", ".htm"):
            txt = data.decode("utf-8", errors="replace")
            m = re.search(r"<head[^>]*>", txt, re.I)
            txt = (txt[:m.end()] + PREVIEW_JS + txt[m.end():]) if m else (PREVIEW_JS + txt)
            data, ctype = txt.encode("utf-8"), "text/html; charset=utf-8"
        elif ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if not self.host_ok() or (origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host", "")):
            return self.send_error(403)
        if self.path != "/__log":
            return self.send_error(404)
        try:
            msg = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4000))).get("m", "")
        except Exception:
            msg = ""
        if msg and (not state.PREVIEW_ERRORS or state.PREVIEW_ERRORS[-1] != msg) and len(state.PREVIEW_ERRORS) < 30:
            state.PREVIEW_ERRORS.append(msg)
            events.emit({"type": "preview_errors", "count": len(state.PREVIEW_ERRORS)})
        self.send_response(204)
        self.end_headers()


def ensure_preview():
    if state.PREVIEW["server"]:
        return
    for port in range(8800, 8840):
        try:
            state.PREVIEW["port"] = port
            srv = ThreadingHTTPServer(("0.0.0.0" if state.LAN else "127.0.0.1", port), PreviewHandler)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("Нет свободного порта для предпросмотра.")
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state.PREVIEW["server"] = srv


def lint_html(f):
    txt, _ = util.read_text(f)
    missing = []
    for m in re.finditer(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", txt):
        ref = m.group(1).split("#")[0].split("?")[0]
        if not ref or re.match(r"^(https?:|//|data:|mailto:|javascript:|tel:)", ref):
            continue
        t = (state.WS / ref.lstrip("/")) if ref.startswith("/") else (f.parent / urllib.parse.unquote(ref))
        if not t.resolve().exists():
            missing.append(ref)
    return missing


def make_preview(path=""):
    if path:
        f = util.safe(path)
    else:
        f = state.WS / "index.html"
        if not f.exists():
            html = [e for e in util.tree(3) if not e["d"] and e["p"].lower().endswith((".html", ".htm"))]
            if not html:
                raise ValueError("В рабочей папке нет html-файлов.")
            f = util.safe(html[0]["p"])
    if not f.is_file():
        raise ValueError("Файл не найден: " + str(path))
    ensure_preview()
    state.PREVIEW_ERRORS.clear()
    events.emit({"type": "preview_errors", "count": 0})
    rel = f.relative_to(state.WS).as_posix()
    url = f"http://127.0.0.1:{state.PREVIEW['port']}/{urllib.parse.quote(rel)}"
    return url, rel, (lint_html(f) if f.suffix.lower() in (".html", ".htm") else [])


def t_open_preview(path=""):
    try:
        url, rel, missing = make_preview(path)
    except ValueError as e:
        return "Ошибка: " + str(e)
    events.add_item({"role": "link", "id": util.uid(), "url": url, "title": rel})
    out = f"Предпросмотр готов: {url} — пользователь откроет его кнопкой в чате."
    if missing:
        out += "\nВНИМАНИЕ, в html ссылки на несуществующие файлы: " + ", ".join(missing[:15])
    return out + "\nПосле открытия страницы ошибки консоли можно получить инструментом preview_errors."


def t_preview_errors():
    errs = list(state.PREVIEW_ERRORS)
    state.PREVIEW_ERRORS.clear()
    events.emit({"type": "preview_errors", "count": 0})
    return ("Ошибки со страницы предпросмотра:\n" + "\n".join(errs)) if errs else \
        "Ошибок не поймано (страница ещё не открыта пользователем или работает без ошибок)."
