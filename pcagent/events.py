# -*- coding: utf-8 -*-
"""События для интерфейса: передача подписчикам, история отображения, снимок состояния."""
import pathlib

from . import config, context, state, textmode, util


# ---------- события и история ----------
def emit(ev):
    with state.LOCK:
        for q in state.SUBS:
            q.put(ev)


def add_item(item):
    with state.LOCK:
        state.TRANSCRIPT.append(item)
        emit({"type": "item", "item": item})


def patch_item(iid, patch):
    with state.LOCK:
        for it in state.TRANSCRIPT:
            if it["id"] == iid:
                it.update(patch)
        emit({"type": "update", "id": iid, "patch": patch})


def append_text(item, delta):
    with state.LOCK:
        item["text"] += delta
        emit({"type": "delta", "id": item["id"], "delta": delta})


def snapshot():
    return {"type": "snapshot", "configured": bool(config.profiles()), "workspace": str(state.WS),
            "profiles": {k: {"provider": v.get("provider", ""), "model": v.get("model", ""), "tools": textmode.tools_mode(v), "ctx": v.get("ctx")}
                         for k, v in config.profiles().items()}, "ctx": context.ctx_event(), "force_text": bool(state.CFG.get("force_text")),
            "mode": state.CFG.get("mode", "auto"), "verify": bool(state.CFG.get("verify")), "autopilot": bool(state.CFG.get("autopilot")), "docker": state.CFG.get("docker", {}), "recent": [x for x in state.CFG.get("recent", []) if pathlib.Path(x).is_dir()], "auto": state.AUTO, "busy": state.BUSY, "plan": state.PLAN,
            "usage": usage_event(), "prices": [state.CFG.get("price_in"), state.CFG.get("price_out")],
            "transcript": list(state.TRANSCRIPT), "tree": util.tree()}


def usage_event():
    cost = None
    pin, pout = state.CFG.get("price_in"), state.CFG.get("price_out")
    if pin is not None and pout is not None:
        cost = state.USAGE["cloud_prompt"] / 1e6 * float(pin) + state.USAGE["cloud_completion"] / 1e6 * float(pout)
    return {"type": "usage", "prompt": state.USAGE["prompt"], "completion": state.USAGE["completion"], "cost": cost}


def snapshot_light():
    return {"type": "profiles", "profiles": {k: {"provider": v.get("provider", ""), "model": v.get("model", ""),
                                                  "tools": textmode.tools_mode(v)} for k, v in config.profiles().items()},
            "mode": state.CFG.get("mode", "auto")}
