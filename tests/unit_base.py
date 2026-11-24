# -*- coding: utf-8 -*-
"""Основа для тестов внутри одного процесса: чистое состояние и временные папки."""
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from pcagent import events, state


class UnitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="pca_unit_"))
        self.ws = self.tmp / "ws"
        self.ws.mkdir()
        state.CONF_DIR = self.tmp / ".pc_agent"
        state.CONF_FILE = state.CONF_DIR / "config.json"
        state.CHATS_DIR = state.CONF_DIR / "chats"
        state.WS = self.ws.resolve()
        state.CFG = {}
        state.ACTIVE = {}
        state.AUTO = state.PLAN = state.BUSY = False
        state.MESSAGES[:] = [{"role": "system", "content": "SYS"}]
        for coll in (state.TRANSCRIPT, state.UNDO, state.CHANGED, state.PREVIEW_ERRORS, state.PENDING_IMAGES):
            coll.clear()
        state.USAGE.update({"prompt": 0, "completion": 0, "cloud_prompt": 0, "cloud_completion": 0})
        state.CANCEL.clear()
        self.items = []
        patcher = mock.patch.object(events, "add_item", side_effect=lambda it: self.items.append(it))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def notes(self):
        return [i.get("text", "") for i in self.items if i.get("role") in ("note", "error")]
