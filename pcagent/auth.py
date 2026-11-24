# -*- coding: utf-8 -*-
"""Вход по PIN-коду для доступа с телефона."""
from http.cookies import SimpleCookie

from . import state


def session_ok(cookie_header):
    try:
        c = SimpleCookie(cookie_header or "")
        return "pcsid" in c and c["pcsid"].value in state.SESSIONS
    except Exception:
        return False


LOGIN_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ПК-агент — вход</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1115;color:#e6e8ee;font:16px system-ui,sans-serif}
div{background:#161920;border:1px solid #262b36;border-radius:14px;padding:26px;width:min(340px,90vw);display:flex;flex-direction:column;gap:12px}
input{background:#0f1218;border:1px solid #262b36;color:#e6e8ee;border-radius:8px;padding:12px;font:22px monospace;letter-spacing:6px;text-align:center}
button{background:#2b5cc4;color:#fff;border:0;border-radius:8px;padding:12px;font:inherit;cursor:pointer}#e{color:#f87171;font-size:14px;min-height:18px}</style></head>
<body><div><b>🤖 ПК-агент</b><span style="color:#8b93a7;font-size:14px">Введи PIN-код из окна на компьютере</span>
<input id="p" inputmode="numeric" autocomplete="off" maxlength="12" autofocus><div id="e" style="all:unset;color:#f87171;font-size:14px;min-height:18px"></div><button id="b">Войти</button></div>
<script>async function go(){const r=await fetch('/login',{method:'POST',body:JSON.stringify({pin:document.getElementById('p').value})});
if(r.ok)location.reload();else{const j=await r.json().catch(()=>({}));document.getElementById('e').textContent=j.error||'Неверный PIN';}}
document.getElementById('b').onclick=go;document.getElementById('p').onkeydown=e=>{if(e.key==='Enter')go();};</script></body></html>"""
