#!/usr/bin/env python3
"""Подставная озвучка для тестов: «произносит» текст тоном, длина зависит от длины текста.
Вызов: fake_tts.py ТЕКСТОВЫЙ_ФАЙЛ ВЫХОДНОЙ_WAV   (чистый Python, ffmpeg не нужен)."""
import math
import struct
import sys
import wave

text = open(sys.argv[1], encoding="utf-8").read()
if "СБОЙ" in text:
    sys.exit(2)
seconds = min(6.0, 0.5 + 0.05 * len(text))
rate = 44100
with wave.open(sys.argv[2], "w") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 300 * i / rate))) for i in range(int(seconds * rate))))
