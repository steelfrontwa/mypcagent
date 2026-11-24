# -*- coding: utf-8 -*-
"""Таблица команд интерфейса."""

from . import api_core, api_git, api_sched, api_tg, api_video, util


def _build_routes():
    return {"chat": api_core.api_chat, "stop": api_core.api_stop, "confirm": api_core.api_confirm, "auto": api_core.api_auto,
              "setup": api_core.api_setup, "model": api_core.api_model, "reset": api_core.api_reset,
              "workspace": api_core.api_workspace, "local_scan": api_core.api_local_scan,
              "local_setup": api_core.api_local_setup, "models": api_core.api_models, "mode": api_core.api_mode, "undo": api_core.api_undo, "preview": api_core.api_preview,
              "compact": api_core.api_compact, "ctx_set": api_core.api_ctx_set, "autopilot": api_core.api_autopilot, "make_game": api_core.api_make_game, "probe": api_core.api_probe, "force_text": api_core.api_force_text, "verify": api_core.api_verify, "docker_set": api_core.api_docker_set,
              "media_list": api_video.api_media_list, "make_video": api_video.api_make_video, "video_install": api_video.api_video_install,
              "sched_list": api_sched.api_sched_list, "sched_add": api_sched.api_sched_add, "sched_del": api_sched.api_sched_del,
              "sched_toggle": api_sched.api_sched_toggle, "sched_run": api_sched.api_sched_run, "tg_status": api_tg.api_tg_status, "tg_setup": api_tg.api_tg_setup, "tg_off": api_tg.api_tg_off,
              "history": api_git.api_history, "git_init": api_git.api_git_init, "git_auto": api_git.api_git_auto, "restore": api_git.api_restore,
              "publish_save": api_git.api_publish_save, "publish": api_git.api_publish, "plan": api_core.api_plan, "plan_mode": api_core.api_plan_mode, "prices": api_core.api_prices, "rules": api_core.api_rules, "pick": api_core.api_pick, "open": api_core.api_open}


ROUTES = util.Lazy(_build_routes)
