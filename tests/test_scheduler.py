# -*- coding: utf-8 -*-
"""Расписание: когда задание должно запускаться, и запуск «прямо сейчас» в нужной папке."""
import os
import tempfile
import unittest
from datetime import datetime

from pcagent import api_sched, scheduler, state
from tests.fakes import FakeLLM
from tests.harness import AgentCase
from tests.unit_base import UnitCase


def d(s):
    return datetime.fromisoformat(s)


class DueLogic(UnitCase):
    def test_daily_window(self):
        t = {"kind": "daily", "time": "09:00", "last_run": None, "created": "2026-11-20T08:00:00"}
        self.assertFalse(scheduler.sched_due(t, d("2026-11-22T08:59:00")))
        self.assertTrue(scheduler.sched_due(t, d("2026-11-22T09:01:00")))
        self.assertFalse(scheduler.sched_due(t, d("2026-11-22T11:30:00")), "запуск позже, чем через 2 часа, пропускается")
        t["last_run"] = "2026-11-22T09:01:10"
        self.assertFalse(scheduler.sched_due(t, d("2026-11-22T09:30:00")), "второй раз за день запускаться не должно")

    def test_weekdays_skip_weekend(self):
        t = {"kind": "weekdays", "time": "09:00", "last_run": None, "created": "x"}
        self.assertFalse(scheduler.sched_due(t, d("2026-11-21T09:10:00")))    # суббота
        self.assertTrue(scheduler.sched_due(t, d("2026-11-23T09:10:00")))     # понедельник

    def test_interval(self):
        t = {"kind": "every", "minutes": 30, "last_run": "2026-11-22T10:00:00", "created": "2026-11-22T08:00:00"}
        self.assertFalse(scheduler.sched_due(t, d("2026-11-22T10:20:00")))
        self.assertTrue(scheduler.sched_due(t, d("2026-11-22T10:31:00")))

    def test_validation(self):
        _, code = api_sched.api_sched_add({"text": "x", "kind": "daily", "time": "25:99"})
        self.assertEqual(code, 400)
        _, code = api_sched.api_sched_add({"text": "", "kind": "daily", "time": "09:00"})
        self.assertEqual(code, 400)
        r, code = api_sched.api_sched_add({"text": "x", "kind": "every", "minutes": 1})
        self.assertEqual(r["tasks"][0]["minutes"], 5, "интервал не может быть меньше 5 минут")


class RunNow(AgentCase):
    def test_task_runs_in_its_own_folder_without_questions(self):
        other = tempfile.mkdtemp(prefix="pca_other_")
        self.addCleanup(lambda: __import__("shutil").rmtree(other, ignore_errors=True))
        llm = self.serve(FakeLLM("x"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})
        self.cloud(a, llm)
        r = a.post("sched_add", {"text": "создай заметку", "kind": "every", "minutes": 5, "auto": True})
        task = r["tasks"][0]
        self.assertEqual(os.path.realpath(task["workspace"]), os.path.realpath(self.ws))
        self.assertTrue(a.post("workspace", {"path": other}).get("ok"))        # переключились на другую папку
        a.clear()
        self.assertTrue(a.post("sched_run", {"id": task["id"]}).get("ok"))
        self.assertTrue(a.wait_idle())
        self.assertTrue(os.path.exists(os.path.join(self.ws, "notes.txt")))
        self.assertFalse(os.path.exists(os.path.join(other, "notes.txt")))
        self.assertTrue(a.wait(lambda: [e["value"] for e in a.events if e["type"] == "auto"] == [True, False], 5),
                        "«всё разрешено» должно вернуться на место после задания")
        self.assertEqual(a.items("confirm"), [])
        listing = a.post("sched_list")
        self.assertTrue(listing["tasks"][0]["last_run"])
        self.assertFalse(a.post("sched_toggle", {"id": task["id"]})["tasks"][0]["enabled"])
        self.assertEqual(a.post("sched_del", {"id": task["id"]})["tasks"], [])


if __name__ == "__main__":
    unittest.main()
