# -*- coding: utf-8 -*-
"""Подключение облачных сервисов по своему адресу (например, посредники вроде sprutdock)."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pcagent import llm, providers, state
from tests.unit_base import UnitCase


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj, ctype="application/json"):
        d = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        if self.path == "/agg1/v1/models":
            self.send(200, {"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3"}, {"id": "claude-x"},
                                     {"id": "deepseek-chat-v3"}, {"id": "deepseek-reasoner"}]})
        elif self.path == "/agg3/v1/models":
            self.send(401, {"error": "bad key"})
        else:
            self.send(404, {"error": "nope"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/agg2/v1/chat/completions" and body.get("model") == "my-model":
            self.send(200, {"choices": [{"message": {"content": "pong"}}]})
        elif self.path == "/agg1/v1/chat/completions":
            if "stream_options" in body:
                self.send(400, {"error": {"message": "Unknown parameter: stream_options"}})
            else:
                self.send(200, b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n', "text/event-stream")
        else:
            self.send(404, {"error": "nope"})


class Providers(UnitCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("PC_AGENT_BASE_URL", None)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_adds_v1_and_prefers_deepseek(self):
        cfg, err, ids = providers.connect_cloud("k", self.base + "/agg1")
        self.assertEqual(err, "")
        self.assertEqual(cfg["base_url"], self.base + "/agg1/v1")
        self.assertEqual(cfg["model"], "deepseek-chat-v3")
        self.assertEqual(len(ids), 5)

    def test_explicit_model_wins(self):
        cfg, _, _ = providers.connect_cloud("k", self.base + "/agg1/v1", "claude-x")
        self.assertEqual(cfg["model"], "claude-x")

    def test_service_without_models_list(self):
        cfg, err, _ = providers.connect_cloud("k", self.base + "/agg2")
        self.assertIsNone(cfg)
        self.assertIn("название модели", err)
        cfg, err, _ = providers.connect_cloud("k", self.base + "/agg2", "my-model")
        self.assertEqual((cfg["base_url"], cfg["model"]), (self.base + "/agg2/v1", "my-model"))

    def test_bad_key_and_unreachable_address_have_clear_messages(self):
        cfg, err, _ = providers.connect_cloud("k", self.base + "/agg3")
        self.assertIsNone(cfg)
        self.assertIn("не принял ключ", err)
        cfg, err, _ = providers.connect_cloud("k", "http://127.0.0.1:9/x")
        self.assertIsNone(cfg)
        self.assertIn("не отвечает", err)

    def test_stream_options_are_dropped_when_service_rejects_them(self):
        cfg = {"base_url": self.base + "/agg1/v1", "api_key": "k", "model": "m"}
        body = {"model": "m", "messages": [], "stream": True, "stream_options": {"include_usage": True}}
        resp = llm.open_stream(cfg, body)
        self.assertEqual(resp.status, 200)
        resp.close()
        self.assertTrue(cfg.get("no_usage"))
        self.assertNotIn("stream_options", body)

    def test_pick_model(self):
        self.assertEqual(providers.pick_model(["gpt-4o", "text-embedding-3", "DeepSeek-V3.2"]), "DeepSeek-V3.2")
        self.assertEqual(providers.pick_model(["a", "b"]), "a")
        self.assertEqual(providers.pick_model([]), "")


if __name__ == "__main__":
    unittest.main()
