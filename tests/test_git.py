# -*- coding: utf-8 -*-
"""История версий и публикация на настоящем git (тест пропускается, если git не установлен)."""
import shutil
import subprocess
import unittest

from pcagent import api_git, gitops, state
from tests.unit_base import UnitCase


@unittest.skipUnless(shutil.which("git"), "git не установлен")
class Git(UnitCase):
    def test_history_restore_and_publish(self):
        (self.ws / "a.txt").write_text("v1")
        (self.ws / ".agent_backup").mkdir()
        (self.ws / ".agent_backup" / "x.bak").write_text("мусор")
        self.assertIsNone(gitops.git_init())
        self.assertTrue(gitops.is_repo() and gitops.autocommit_on())
        self.assertEqual(gitops.git("ls-files")[1].split(), ["a.txt"], "служебные папки агента попали в историю")

        (self.ws / "a.txt").write_text("v2")
        (self.ws / "b.txt").write_text("новый")
        gitops.post_task("сделай второй файл")
        log = gitops.git_log()
        self.assertEqual([c["subject"] for c in log], ["Агент: сделай второй файл", "Начало истории"])
        self.assertTrue(any("Сохранено в историю" in n for n in self.notes()))

        result, code = api_git.api_restore({"hash": log[-1]["h"]})
        self.assertEqual(code, 200)
        self.assertEqual((self.ws / "a.txt").read_text(), "v1")
        self.assertFalse((self.ws / "b.txt").exists())
        self.assertTrue(list((self.ws / ".agent_trash").iterdir()), "лишний файл должен уйти в корзину, а не пропасть")
        self.assertEqual(gitops.git_log()[0]["subject"], "Откат к " + log[-1]["h"], "откат должен быть новой версией")
        _, code = api_git.api_restore({"hash": "zz; rm -rf /"})
        self.assertEqual(code, 400)

        remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "master", str(remote)], capture_output=True)
        api_git.api_publish_save({"url": str(remote), "branch": "master"})
        ok, msg = gitops.do_publish()
        self.assertTrue(ok, msg)
        # в удалённом репозитории появился чужой файл (как amvera.yml) — публикация должна объединить, а не упасть
        clone = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], capture_output=True)
        (clone / "amvera.yml").write_text("meta: x\n")
        subprocess.run(["git", "-C", str(clone), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "r"], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "master"], capture_output=True)
        (self.ws / "c.txt").write_text("c")
        ok, msg = gitops.do_publish()
        self.assertTrue(ok, msg)
        self.assertTrue((self.ws / "amvera.yml").exists())

    def test_publish_requires_address(self):
        ok, msg = gitops.do_publish()
        self.assertFalse(ok)
        self.assertIn("адрес", msg.lower())


if __name__ == "__main__":
    unittest.main()
