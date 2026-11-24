# -*- coding: utf-8 -*-
"""Команды интерфейса: создание видео из файлов рабочей папки."""
from . import api_core, state, video


def api_media_list(b):
    return video.media_summary(), 200


def api_video_install(b):
    ok, msg = video.install_ffmpeg()
    return ({"ok": True, "msg": msg}, 200) if ok else ({"error": msg or "Не удалось установить ffmpeg."}, 400)


FORMAT_TEXT = {"landscape": "горизонтальное 16:9", "vertical": "вертикальное 9:16 (для Shorts и Reels)", "square": "квадратное 1:1"}


def api_make_video(b):
    if not video.find_ffmpeg():
        return {"error": video.FFMPEG_HELP}, 400
    idea = str(b.get("idea") or "").strip()[:1500]
    fmt = str(b.get("format") or "auto")
    secs = str(b.get("seconds") or "").strip()
    text = "Создай видео из файлов рабочей папки (фото, видеоклипы, музыка, тексты). "
    if idea:
        text += f"О чём ролик и какой стиль: {idea}. "
    text += (f"Формат: {FORMAT_TEXT[fmt]}. " if fmt in FORMAT_TEXT else "Формат выбери сам по файлам (format=auto). ")
    text += ("Добавь подписи на экране. " if b.get("captions", True) else "Подписи на экране не нужны. ")
    text += ("Добавь музыку из папки, если она там есть. " if b.get("music", True) else "Без музыки. ")
    if b.get("voice"):
        text += ("Озвучь ролик закадровым голосом: для каждой сцены напиши короткий текст озвучки по смыслу кадров "
                 "(или возьми из сценария в текстовом файле). ")
    if secs.isdigit() and 5 <= int(secs) <= 1200:
        text += f"Длительность около {secs} секунд. "
    text += ("Сначала изучи файлы (list_media) и текстовые файлы (read_file), затем собери ролик (make_video), "
             "проверь результат (check_video) и исправь недочёты.")
    state.AP["oneoff"] = True
    r, code = api_core.api_chat({"message": text})
    if code != 200:
        state.AP["oneoff"] = False
    return r, code
