#!/usr/bin/env python3
"""Подставной «браузер» для тестов: открывает страницу через сервер предпросмотра и, как настоящий,
сообщает об ошибках загрузки скриптов (так срабатывает перехватчик в предпросмотре)."""
import json
import re
import sys
import urllib.error
import urllib.request

args = sys.argv[1:]
url = args[-1]
html = urllib.request.urlopen(url).read().decode()
base = "/".join(url.split("/")[:3])
folder = url.rsplit("/", 1)[0]
for a in args:
    if a.startswith("--screenshot="):
        open(a.split("=", 1)[1], "wb").write(b"\x89PNG\r\n\x1a\nFAKE")
for ref in re.findall(r"src=['\"]([^'\"]+)['\"]", html):
    try:
        urllib.request.urlopen(folder + "/" + ref)
    except urllib.error.HTTPError:
        urllib.request.urlopen(urllib.request.Request(
            base + "/__log", data=json.dumps({"m": "Не загрузился ресурс: " + ref}).encode(), method="POST"))
if "boom" in url:
    urllib.request.urlopen(urllib.request.Request(
        base + "/__log", data=json.dumps({"m": "ReferenceError: foo is not defined (game.js:3)"}).encode(), method="POST"))
    print('[0101/000000.000:ERROR:CONSOLE(7)] "Uncaught TypeError: bar is null", source: http://127.0.0.1/game.js (7)', file=sys.stderr)
if "--dump-dom" in args:
    print(html)
