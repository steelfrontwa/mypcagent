# -*- coding: utf-8 -*-
"""Подставные серверы для тестов: «модель» (OpenAI-совместимая) и Telegram. Реальные ключи и интернет не нужны."""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GAME_HTML = "<html><head><title>Игра</title></head><body><canvas id=c></canvas><script src='game.js'></script></body></html>"
MODELS = ["native", "dumb", "game", "game-ask", "script", "trunc", "video"]


class _Server:
    def __init__(self, handler_cls):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeLLM(_Server):
    """Поведение выбирается по имени модели: native, dumb, game, game-ask, script, trunc."""

    def __init__(self, tag=None):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                d = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(d)))
                self.end_headers()
                self.wfile.write(d)

            def do_GET(self):
                if self.path.endswith("/models"):
                    return self._json({"data": [{"id": m} for m in MODELS]})
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                if not self.path.endswith("/chat/completions"):
                    return self._json({"error": "not found"}, 404)
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer.handle(self, body)

        super().__init__(H)
        self.tag = tag or self.port

    # --- ответы ---
    def handle(self, h, body):
        model, msgs = body["model"], body["messages"]
        sysmsg = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        if not body.get("stream"):
            if sysmsg.startswith("Ты сжимаешь историю"):
                return h._json({"choices": [{"message": {"content": "ЦЕЛЬ: сделать игру змейка. СДЕЛАНО: index.html. ОСТАЛОСЬ: звук."}}]})
            if model == "dumb":
                return h._json({"choices": [{"message": {"role": "assistant", "content": "вот команда list_dir"}}]})
            call = {"id": "p1", "type": "function", "function": {"name": "list_dir", "arguments": "{\"path\": \".\"}"}}
            return h._json({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]})
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.end_headers()
        send = lambda d: (h.wfile.write(("data: " + json.dumps(d) + "\n\n").encode()), h.wfile.flush())
        say = lambda t: send({"choices": [{"delta": {"content": t}}]})
        last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
        lu = msgs[last_user]["content"] if isinstance(msgs[last_user]["content"], str) else ""
        n_tools = sum(1 for m in msgs[last_user:] if m["role"] == "tool")
        names = [t["function"]["name"] for t in body.get("tools", [])]

        def call(name, args):
            send({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"c{n_tools}",
                                                        "function": {"name": name, "arguments": json.dumps(args)}}]}}]})

        pt = 4090 if model == "trunc" else 1000
        if model == "dumb":
            last = msgs[-1]
            if "tools" in body:
                say("Откройте терминал и введите:\n```bash\nmkdir site\n```\nСохраните файл index.html.")
            elif last["role"] == "user" and last["content"].startswith("[результат инструмента]"):
                say("Готово, файл создан.")
            else:
                say("Создаю файл.\n```tool\n{\"name\":\"write_file\",\"args\":{\"path\":\"notes.txt\",\"content\":\"привет\"}}\n```")
        elif model.startswith("game"):
            if lu.startswith("Создай браузерную игру"):
                if n_tools == 0:
                    call("write_file", {"path": "game/index.html", "content": GAME_HTML})
                else:
                    say("Игра создана. Хотите, чтобы я добавил музыку?" if model == "game-ask" else "Игра создана.")
            elif lu.startswith("[АВТОПИЛОТ]"):
                if n_tools == 0:
                    call("write_file", {"path": "game/game.js", "content": "console.log('ok')"})
                else:
                    say("Готово: добавил game.js.")
            else:
                say("не знаю")
        elif model == "video":
            if lu.startswith("[ПРОВЕРКА]"):
                say("Проверка пройдена.")
            elif n_tools == 0:
                call("list_media", {})
            elif n_tools == 1:
                call("make_video", {"output": "result.mp4", "quality": "draft", "format": "auto", "scenes": [
                    {"title": "Мой ролик", "duration": 2},
                    {"file": "a.jpg", "duration": 2, "text": "Первая сцена"},
                    {"file": "b.jpg", "duration": 2, "text": "Вторая сцена"}]})
            elif n_tools == 2:
                call("check_video", {"path": "result.mp4"})
            else:
                say("Видео готово: result.mp4")
        elif model == "script":
            if n_tools == 0:
                call("write_file", {"path": "index.html", "content": GAME_HTML})
            elif n_tools == 1:
                call("open_preview", {})
            else:
                say("Готово.")
        elif lu.startswith("[ПРОВЕРКА]"):
            say(f"Проверка пройдена, замечаний нет (порт {self.tag}).")
        elif "заметку" in lu:
            plan = "propose_plan" in names
            if plan and n_tools == 0:
                call("propose_plan", {"steps": "1. создать notes.txt"})
            elif n_tools == (1 if plan else 0):
                call("write_file", {"path": "notes.txt", "content": "привет"})
            else:
                say(f"Заметка готова (порт {self.tag}, сообщений в истории: {len(msgs)}).")
        else:
            say(f"Ответ с порта {self.tag}, сообщений в истории: {len(msgs)}.")
        send({"choices": [], "usage": {"prompt_tokens": pt, "completion_tokens": 50}})
        h.wfile.write(b"data: [DONE]\n\n")


class FakeTelegram(_Server):
    def __init__(self):
        self.updates = queue.Queue()
        self.sent = []
        self.docs = []
        self._n = 100
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                method = self.path.split("/")[-1]
                res = {"ok": True, "result": True}
                if method == "getMe":
                    res = {"ok": True, "result": {"username": "testbot"}}
                elif method == "getUpdates":
                    try:
                        res = {"ok": True, "result": [outer.updates.get(timeout=1)]}
                    except queue.Empty:
                        res = {"ok": True, "result": []}
                elif method == "sendMessage":
                    outer.sent.append(json.loads(raw))
                elif method == "sendDocument":
                    outer.docs.append(raw[:600])
                d = json.dumps(res).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(d)))
                self.end_headers()
                self.wfile.write(d)

        super().__init__(H)

    def message(self, chat, text):
        self._n += 1
        self.updates.put({"update_id": self._n, "message": {"chat": {"id": chat}, "text": text}})

    def callback(self, chat, data):
        self._n += 1
        self.updates.put({"update_id": self._n, "callback_query": {"id": f"q{self._n}", "data": data,
                                                                    "message": {"chat": {"id": chat}}}})

    def texts(self):
        return [s["text"] for s in self.sent]
