# -*- coding: utf-8 -*-
"""Подключение облачных сервисов и локальных серверов (Ollama, LM Studio и др.)."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


# ---------- настройка ключа ----------
def pick_model(ids, prefer=""):
    if prefer:
        return prefer
    ids = [i for i in ids if not re.search(r"embed|whisper|tts|dall|image", i, re.I)]
    for pat in ("deepseek-chat", "deepseek-flash", "deepseek-v", "flash", "deepseek"):
        for i in ids:
            if pat in i.lower():
                return i
    return ids[0] if ids else ""


def probe_endpoint(base, key, model=""):
    """Возвращает (статус, список_моделей): ok / auth / nomodels / net."""
    hdr = {"Authorization": "Bearer " + key}
    try:
        req = urllib.request.Request(base + "/models", headers=hdr)
        data = json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8"))
        items = data.get("data", data) if isinstance(data, dict) else data
        ids = [m.get("id") if isinstance(m, dict) else str(m) for m in items]
        return "ok", [i for i in ids if i]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "auth", []
    except Exception as e:
        if not isinstance(e, (ValueError, AttributeError, TypeError)):
            return "net", []
    if model:  # /models не поддерживается — проверяем обычным запросом
        try:
            body = json.dumps({"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}).encode()
            req = urllib.request.Request(base + "/chat/completions", data=body,
                                         headers={**hdr, "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=40).read()
            return "ok", [model]
        except urllib.error.HTTPError as e:
            return ("auth" if e.code in (401, 403) else "nomodels"), []
        except Exception:
            return "net", []
    return "nomodels", []


def connect_cloud(key, base_url="", model=""):
    """Подключение облачного сервиса. Возвращает (профиль|None, текст_ошибки, список_моделей)."""
    env_base = os.environ.get("PC_AGENT_BASE_URL", "")
    base_url = (base_url or env_base or "").strip()
    model = (model or "").strip()
    if base_url:
        u = base_url.rstrip("/")
        if not u.startswith("http"):
            u = "https://" + u
        cands = [u] + ([u + "/v1"] if not re.search(r"/v\d+$", u) else [])
        from_env = bool(env_base) and base_url == env_base          # адрес задан переменной окружения (тесты)
        name = "Custom" if from_env else (urllib.parse.urlparse(u).hostname or "Custom")
        last = "net"
        for base in cands:
            st, ids = probe_endpoint(base, key, model)
            if st == "ok":
                m = pick_model(ids, model)
                if not m:
                    return None, "Адрес отвечает, но моделей не нашёл. Впиши название модели в поле «Модель».", ids
                return {"provider": name, "base_url": base, "model": m, "api_key": key, "custom": True}, "", ids
            if st == "auth":
                return None, f"Сервер {base} не принял ключ. Проверь ключ и адрес API.", []
            last = st
        if last == "nomodels":
            return None, "Адрес отвечает, но список моделей не отдаёт. Впиши название модели в поле «Модель» и нажми «Подключить» снова.", []
        return None, f"Адрес не отвечает: {u}. Проверь адрес (обычно он заканчивается на /v1) и интернет.", []
    if key.startswith("sk-or-"):
        name, base, default = "OpenRouter", "https://openrouter.ai/api/v1", "deepseek/deepseek-chat"
    else:
        name, base, default = "DeepSeek", "https://api.deepseek.com", "deepseek-chat"
    st, ids = probe_endpoint(base, key, model or default)
    if st == "auth":
        return None, ("Официальный DeepSeek не принял этот ключ. Если ключ от другого сервиса (например, sprutdock), "
                      "впиши его адрес API в поле «Адрес API» ниже — он указан в личном кабинете или в документации сервиса."), []
    if st == "net":
        return None, f"Нет связи с {urllib.parse.urlparse(base).hostname}. Проверь интернет. Если у тебя ключ от другого сервиса, впиши его адрес API.", []
    m = pick_model(ids, model) or default
    return {"provider": name, "base_url": base, "model": m, "api_key": key}, "", ids


def autodetect(key):
    cfg, _, _ = connect_cloud(key)
    return cfg


# ---------- локальный ИИ (Ollama, LM Studio, llama.cpp и любой OpenAI-совместимый сервер) ----------
LOCAL_CANDIDATES = [("Ollama", "http://127.0.0.1:11434/v1"),
                    ("LM Studio", "http://127.0.0.1:1234/v1"),
                    ("llama.cpp / другой", "http://127.0.0.1:8080/v1")]


def list_models(base, key="local", timeout=3):
    req = urllib.request.Request(base.rstrip("/") + "/models", headers={"Authorization": "Bearer " + key})
    data = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    return [m for m in ids if "embed" not in m.lower()]


def normalize_base(url):
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith("http"):
        url = "http://" + url
    if not re.search(r"/v1$", url):
        url += "/v1"
    return url
