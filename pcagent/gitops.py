# -*- coding: utf-8 -*-
"""История заданий в git и публикация проекта."""
import os
import re
import shutil
import subprocess

from . import config, events, fileops, state, util


def git(*args, timeout=60):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    pre = ["-c", "core.quotepath=false"]
    if args and args[0] in ("commit", "merge", "pull"):
        who = subprocess.run(["git", "config", "user.name"], cwd=state.WS, capture_output=True, text=True, errors="replace")
        if not who.stdout.strip():
            pre += ["-c", "user.name=PC-Agent", "-c", "user.email=agent@local"]
    r = subprocess.run(["git"] + pre + list(args), cwd=state.WS, capture_output=True, text=True, errors="replace",
                       timeout=timeout, env=env)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def git_ok():
    return bool(shutil.which("git"))


def is_repo():
    return git_ok() and (state.WS / ".git").exists()


def autocommit_on():
    return bool(state.CFG.get("autocommit", {}).get(str(state.WS)))


def git_init():
    if not git_ok():
        return "Git не установлен (git-scm.com)."
    if not (state.WS / ".git").exists():
        code, out = git("init", "-b", "master")
        if code != 0:
            git("init")
    info = state.WS / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    ex = info / "exclude"
    cur = ex.read_text(encoding="utf-8") if ex.exists() else ""
    add = [l for l in (".agent_backup/", ".agent_trash/", ".agent_shots/") if l not in cur]
    if add:
        ex.write_text(cur + ("\n" if cur and not cur.endswith("\n") else "") + "\n".join(add) + "\n", encoding="utf-8")
    state.CFG.setdefault("autocommit", {})[str(state.WS)] = True
    config.save_cfg()
    git_commit("Начало истории")
    return None


def git_commit(msg):
    if not is_repo():
        return None
    git("add", "-A")
    code, out = git("status", "--porcelain")
    if not out.strip():
        return None
    code, out = git("commit", "-m", msg[:200])
    if code != 0:
        return None
    return git("rev-parse", "--short", "HEAD")[1]


def git_log(n=40):
    code, out = git("log", f"-n{n}", "--pretty=format:%h%x09%cI%x09%s")
    if code != 0:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append({"h": parts[0], "date": parts[1][:16].replace("T", " "), "subject": parts[2]})
    return rows


def post_task(text):
    """После задания: сохраняем результат в историю git (если включено)."""
    if autocommit_on() and is_repo():
        h = git_commit("Агент: " + text.strip().replace("\n", " ")[:70])
        if h:
            events.add_item({"role": "note", "id": util.uid(), "text": f"💾 Сохранено в историю: {h}"})
    state.CHANGED.clear()


def do_publish():
    cfgp = state.CFG.get("publish", {}).get(str(state.WS), {})
    url, branch = (cfgp.get("url") or "").strip(), (cfgp.get("branch") or "").strip()
    if not git_ok():
        return False, "Git не установлен (git-scm.com)."
    if not url:
        return False, "Не указан адрес репозитория для публикации."
    if not is_repo():
        err = git_init()
        if err:
            return False, err
    git_commit("Публикация")
    if not branch:
        branch = "master" if "amvera" in url.lower() else (git("rev-parse", "--abbrev-ref", "HEAD")[1] or "master")
    code, _ = git("remote", "get-url", "publish")
    git("remote", "set-url" if code == 0 else "add", "publish", url)
    code, out = git("push", "publish", f"HEAD:{branch}", timeout=180)
    if code != 0 and re.search(r"rejected|fetch first|non-fast-forward", out, re.I):
        code, pull = git("pull", "--no-rebase", "publish", branch, "--allow-unrelated-histories", "--no-edit", timeout=120)
        if code != 0:
            git("merge", "--abort")
            return False, "Удалённый репозиторий содержит другие изменения, и объединить автоматически не вышло:\n" + pull[-600:]
        code, out = git("push", "publish", f"HEAD:{branch}", timeout=180)
    if code != 0:
        hint = ""
        if re.search(r"auth|denied|403|401|credential|could not read", out, re.I):
            hint = "\nПохоже на проблему с доступом: один раз выполни `git push` вручную в этой папке, введи логин и пароль и сохрани их."
        return False, out[-700:] + hint
    return True, f"Отправлено в ветку {branch}.\n" + out[-300:]


def t_publish_project():
    url = state.CFG.get("publish", {}).get(str(state.WS), {}).get("url", "")
    if not url:
        return "Адрес публикации не задан. Попроси пользователя нажать «🕘 История и публикация» и указать адрес репозитория."
    if not fileops.confirm(f"Опубликовать проект: отправить все изменения на {url}", force=True):
        return "Пользователь отклонил."
    ok, msg = do_publish()
    return ("Опубликовано. " if ok else "Не удалось опубликовать: ") + msg


def history_info():
    return {"git": git_ok(), "repo": is_repo(), "auto": autocommit_on(),
            "commits": git_log() if is_repo() else [],
            "publish": state.CFG.get("publish", {}).get(str(state.WS), {})}
