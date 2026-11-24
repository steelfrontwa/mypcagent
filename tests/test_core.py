# -*- coding: utf-8 -*-
"""Основной сценарий: подключение, выбор модели, план, подтверждение, история, откат."""
import os
import re

from tests.fakes import FakeLLM
from tests.harness import AgentCase, Agent


class CoreFlow(AgentCase):
    def test_hybrid_plan_usage_and_persistence(self):
        cloud, local = self.serve(FakeLLM("cloud")), self.serve(FakeLLM("local"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})
        self.cloud(a, cloud)
        self.assertTrue(a.post("local_setup", {"base_url": f"127.0.0.1:{local.port}", "model": "native"}).get("ok"))
        a.wait(lambda: any(e["type"] == "snapshot" and len(e["profiles"]) == 2 for e in a.events))
        snap = [e for e in a.events if e["type"] == "snapshot"][-1]
        self.assertEqual(snap["mode"], "auto")

        def say(text):
            a.clear()
            self.assertTrue(a.post("chat", {"message": text}).get("ok"))
            self.assertTrue(a.wait_idle(), "агент не закончил")
            return a.deltas()

        self.assertIn("порта local", say("привет, как дела?"))          # простое — на локальную
        self.assertIn("порта cloud", say("сделай мне сайт-визитку"))   # сложное — на облако
        self.assertTrue(a.post("mode", {"mode": "cloud"}).get("ok"))
        self.assertIn("порта cloud", say("привет ещё раз"))            # принудительно облако

        # токены и стоимость (считается только облако: 2 запроса по 1000/50)
        self.assertTrue(a.post("prices", {"inp": "0.28", "out": "0.42"}).get("ok"))
        self.assertTrue(a.wait(lambda: [e for e in a.events if e["type"] == "usage"][-1]["cost"] is not None))
        usage = [e for e in a.events if e["type"] == "usage"][-1]
        self.assertEqual((usage["prompt"], usage["completion"]), (3000, 150))
        self.assertAlmostEqual(usage["cost"], 2000 / 1e6 * 0.28 + 100 / 1e6 * 0.42, places=9)

        # режим плана + подтверждение записи
        a.post("plan_mode", {"value": True})
        a.clear()
        a.post("chat", {"message": "создай заметку"})
        self.assertTrue(a.wait(lambda: a.items("plan")))
        plan = a.items("plan")[0]
        self.assertEqual(plan["state"], "pending")
        a.post("plan", {"id": plan["id"], "answer": "yes", "text": "1. создать notes.txt\n2. ничего больше"})
        self.assertTrue(a.wait(lambda: a.items("confirm")))
        conf = a.items("confirm")[0]
        self.assertIn("notes.txt", conf["title"])
        self.assertFalse(os.path.exists(os.path.join(self.ws, "notes.txt")), "файл создан до разрешения")
        a.post("confirm", {"id": conf["id"], "answer": "yes"})
        self.assertTrue(a.wait_idle())
        self.assertEqual(open(os.path.join(self.ws, "notes.txt"), encoding="utf-8").read(), "привет")
        plan_result = [e["patch"]["result"] for e in a.events if e["type"] == "update" and "result" in e["patch"]][0]
        self.assertIn("ничего больше", plan_result, "правка плана не дошла до модели")

        # перезапуск: история и счётчики на месте, разговор продолжается
        home = a.home
        a.stop(keep_home=True)
        b = self.start(env={"PC_AGENT_NO_PROBE": "1"}, home=home)
        snap = b.events[0]
        self.assertEqual(snap["type"], "snapshot")
        roles = [i["role"] for i in snap["transcript"]]
        self.assertIn("plan", roles)
        self.assertEqual(snap["usage"]["prompt"], 6000)
        b.post("mode", {"mode": "local"})
        b.clear()
        b.post("chat", {"message": "ещё вопрос"})
        self.assertTrue(b.wait_idle())
        n = int(re.search(r"истории: (\d+)", b.deltas()).group(1))
        self.assertGreater(n, 10, "после перезапуска история не продолжилась")

    def test_files_undo_and_preview(self):
        llm = self.serve(FakeLLM("x"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})
        self.cloud(a, llm, "script")
        a.post("auto", {"value": True})
        a.clear()
        a.post("chat", {"message": "сделай страницу"})
        self.assertTrue(a.wait_idle())
        page = os.path.join(self.ws, "index.html")
        self.assertTrue(os.path.exists(page))
        results = [e["patch"] for e in a.events if e["type"] == "update" and "result" in e["patch"]]
        write_patch = results[0]
        self.assertTrue(write_patch["undo"], "у записи нет кнопки отмены")
        self.assertIn("game.js", results[1]["result"], "битая ссылка на файл не замечена")
        self.assertTrue(a.items("link"))
        # откат записи: файл уходит в корзину агента, не пропадает бесследно
        self.assertTrue(a.post("undo", {"id": write_patch["undo"]}).get("ok"))
        self.assertFalse(os.path.exists(page))
        self.assertTrue(os.listdir(os.path.join(self.ws, ".agent_trash")))

    def test_review_pass_uses_cloud_for_local_work(self):
        cloud, local = self.serve(FakeLLM("cloud")), self.serve(FakeLLM("local"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})
        self.cloud(a, cloud)
        a.post("local_setup", {"base_url": f"127.0.0.1:{local.port}", "model": "native"})
        a.post("auto", {"value": True})
        a.post("verify", {"value": True})
        a.clear()
        a.post("chat", {"message": "создай заметку"})
        self.assertTrue(a.wait_idle())
        self.assertTrue(any("Проверяющий проход" in n for n in a.notes()))
        text = a.deltas()
        self.assertIn("Заметка готова (порт local", text)
        self.assertIn("Проверка пройдена, замечаний нет (порт cloud", text)


if __name__ == "__main__":
    import unittest
    unittest.main()
