# -*- coding: utf-8 -*-
"""Реестр инструментов: описания для модели и вызов по имени."""

from . import browser, docs, fileops, gitops, pagepreview, planning, shell, util, video, webtools


def tool(name, desc, props, req):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": req}}}


S = {"type": "string"}


TOOLS = [
    tool("list_dir", "Показать содержимое папки", {"path": S}, []),
    tool("read_file", "Прочитать текстовый файл (можно диапазон строк)",
         {"path": S, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path"]),
    tool("write_file", "Создать или полностью перезаписать файл", {"path": S, "content": S}, ["path", "content"]),
    tool("edit_file", "Заменить точный фрагмент old на new в файле (old должен встречаться один раз)",
         {"path": S, "old": S, "new": S}, ["path", "old", "new"]),
    tool("make_dir", "Создать папку", {"path": S}, ["path"]),
    tool("move_file", "Переместить или переименовать файл/папку", {"src": S, "dst": S}, ["src", "dst"]),
    tool("delete_file", "Удалить файл/папку (в корзину агента)", {"path": S}, ["path"]),
    tool("search", "Поиск по тексту файлов (регулярное выражение)", {"pattern": S, "path": S}, ["pattern"]),
    tool("run_command", "Выполнить команду в терминале в рабочей папке", {"command": S}, ["command"]),
    tool("open_preview", "Показать пользователю html-страницу (сайт, игру) из рабочей папки в браузере; "
         "проверяет, что файлы, на которые она ссылается, существуют. Путь можно не указывать.", {"path": S}, []),
    tool("read_document", "Прочитать текст из Word (.docx), Excel (.xlsx), PowerPoint (.pptx) или PDF", {"path": S}, ["path"]),
    tool("create_docx", "Создать Word-документ. content — текст с разметкой: # Заголовок, ## Подзаголовок, - список, "
         "1. нумерация, **жирный**, таблицы в виде | a | b |. Чтобы изменить существующий документ, прочитай его "
         "read_document и создай заново.", {"path": S, "content": S}, ["path", "content"]),
    tool("create_xlsx", "Создать Excel-файл. sheets — объект {\"Имя листа\": [[ячейки первой строки], [вторая строка], ...]}; "
         "первая строка — заголовки; строка, начинающаяся с =, считается формулой.",
         {"path": S, "sheets": {"type": "object"}}, ["path", "sheets"]),
    tool("web_search", "Поиск в интернете. Возвращает заголовки, ссылки и описания", {"query": S}, ["query"]),
    tool("fetch_url", "Открыть веб-страницу по ссылке и получить её текст", {"url": S}, ["url"]),
    tool("check_page", "Автопроверка страницы: открывает html в скрытом браузере (Chrome/Edge), ловит ошибки "
         "JavaScript и пустой экран, проверяет ссылки на файлы. Путь можно не указывать.", {"path": S}, []),
    tool("screenshot_page", "Сделать скриншот страницы и показать его пользователю (если модель умеет видеть "
         "картинки — она тоже его увидит)", {"path": S}, []),
    tool("publish_project", "Опубликовать проект: отправить его в git-репозиторий публикации (например Amvera). "
         "Вызывай только если пользователь попросил опубликовать. Адрес задаёт пользователь в настройках.", {}, []),
    tool("preview_errors", "Получить ошибки JavaScript и загрузки ресурсов, пойманные на открытой странице предпросмотра",
         {}, []),
    tool("list_media", "Показать фото, видео, музыку и текстовые файлы рабочей папки: размер кадра, длительность, есть ли звук",
         {"path": S}, []),
    tool("make_video", "Собрать видео (mp4) из файлов рабочей папки. scenes — список сцен: {\"file\": \"photo.jpg\" или \"clip.mp4\", "
         "\"duration\": секунды, \"start\": с какой секунды брать клип, \"text\": подпись на экране, \"voice\": текст для озвучки, "
         "\"effect\": zoom|pan|fit|cover|none, \"keep_audio\": true} или титульный кадр {\"title\": \"Текст\", \"duration\": 3, "
         "\"bg\": \"#14181f\"}. Если scenes не указать, ролик соберётся автоматически из всех фото и видео папки. "
         "format: auto|landscape|vertical|square (auto выбирает по файлам); quality: hd|draft; music: файл музыки; "
         "transition: fade|cut; voiceover: озвучить text каждой сцены; результат — mp4 (и .srt, если есть подписи).",
         {"output": S, "scenes": {"type": "array", "items": {"type": "object"}}, "format": S, "fps": {"type": "integer"},
          "quality": S, "music": S, "music_volume": {"type": "number"}, "transition": S, "srt": {"type": "boolean"},
          "voiceover": {"type": "boolean"}, "voice_lang": S, "voice_gender": S}, []),
    tool("make_voice", "Озвучить текст голосом в аудиофайл (для закадрового голоса, обычно достаточно voiceover в make_video)",
         {"text": S, "output": S, "lang": S, "gender": S}, ["text"]),
    tool("check_video", "Проверить готовый видеофайл: длительность, размер кадра, звук; показать контрольные кадры",
         {"path": S}, ["path"]),
]


def _build_impl():
    return {
        "list_dir": fileops.t_list_dir, "read_file": fileops.t_read_file, "write_file": fileops.t_write_file,
        "edit_file": fileops.t_edit_file, "make_dir": fileops.t_make_dir, "move_file": fileops.t_move_file,
        "delete_file": fileops.t_delete_file, "search": fileops.t_search, "run_command": shell.t_run_command,
        "open_preview": pagepreview.t_open_preview, "preview_errors": pagepreview.t_preview_errors, "check_page": browser.t_check_page, "publish_project": gitops.t_publish_project,
        "screenshot_page": browser.t_screenshot_page,
        "propose_plan": planning.t_propose_plan, "read_document": docs.t_read_document, "create_docx": docs.t_create_docx,
        "create_xlsx": docs.t_create_xlsx, "web_search": webtools.t_web_search, "fetch_url": webtools.t_fetch_url,
        "list_media": video.t_list_media, "make_video": video.t_make_video, "make_voice": video.t_make_voice,
        "check_video": video.t_check_video,
    }


IMPL = util.Lazy(_build_impl)


def call_tool(name, args):
    try:
        if name not in IMPL:
            return "Неизвестный инструмент: " + name
        return str(IMPL[name](**args))
    except TypeError as e:
        return "Неверные аргументы: " + str(e)
    except Exception as e:
        return f"Ошибка: {e}"
