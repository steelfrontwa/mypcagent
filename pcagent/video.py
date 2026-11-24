# -*- coding: utf-8 -*-
"""Видео из файлов рабочей папки: фото, видеоклипы, музыка, тексты.

Работает через ffmpeg. Модуль отвечает за четыре вещи:
  * list_media     — что лежит в папке (тип, длительность, размер кадра);
  * make_voice     — озвучка текста (Edge TTS, голос системы или своя команда);
  * make_video     — сборка ролика по сценам (или полностью автоматически);
  * check_video    — проверка готового файла и контрольные кадры.
"""
import importlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time

from . import events, fileops, state, util

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VID_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUD_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
TXT_EXT = {".txt", ".md"}
SIZES = {"hd": {"landscape": (1920, 1080), "vertical": (1080, 1920), "square": (1080, 1080)},
         "draft": {"landscape": (1280, 720), "vertical": (720, 1280), "square": (720, 720)}}
FORMAT_ALIASES = {"горизонтальное": "landscape", "горизонтальный": "landscape", "16:9": "landscape", "wide": "landscape",
                  "вертикальное": "vertical", "вертикальный": "vertical", "9:16": "vertical", "shorts": "vertical",
                  "квадрат": "square", "квадратное": "square", "1:1": "square"}
FFMPEG_HELP = ("ffmpeg не найден. Установи один из способов: в PowerShell `winget install Gyan.FFmpeg` "
               "(потом перезапусти агента) либо `pip install imageio-ffmpeg` (ffmpeg скачается вместе с пакетом).")
MAX_TOTAL_SECONDS = 1800

_PROBE_CACHE = {}


# ---------- поиск программ ----------
def find_ffmpeg():
    env = os.environ.get("PC_AGENT_FFMPEG") or state.CFG.get("ffmpeg")
    if env and os.path.exists(env):
        return env
    w = shutil.which("ffmpeg")
    if w:
        return w
    importlib.invalidate_caches()
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    cands = []
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA", "")
        cands = [r"C:\ffmpeg\bin\ffmpeg.exe", os.path.join(os.environ.get("ProgramFiles", ""), r"ffmpeg\bin\ffmpeg.exe"),
                 os.path.join(la, r"Microsoft\WinGet\Links\ffmpeg.exe")]
    elif sys.platform == "darwin":
        cands = ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    return next((c for c in cands if c and os.path.exists(c)), None)


def _run(cmd, cwd=None, timeout=1800):
    """Запуск внешней программы с возможностью остановить кнопкой «Стоп»."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", creationflags=flags)
    out = []
    import threading
    t = threading.Thread(target=lambda: out.append(p.communicate()), daemon=True)
    t.start()
    end = time.time() + timeout
    while t.is_alive():
        t.join(0.25)
        if state.CANCEL.is_set():
            p.kill()
            t.join(2)
            raise state.Cancelled()
        if time.time() > end:
            p.kill()
            raise RuntimeError("программа работала слишком долго и была остановлена")
    for stream in (p.stdout, p.stderr):
        try:
            stream.close()
        except Exception:
            pass
    o, e = out[0] if out else ("", "")
    return p.returncode, o, e


def _status(text):
    events.emit({"type": "status", "text": text})


# ---------- сведения о файлах ----------
def probe(path):
    ff = find_ffmpeg()
    p = pathlib.Path(path)
    key = (str(p), p.stat().st_mtime, p.stat().st_size)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    info = {"duration": None, "width": None, "height": None, "has_video": False, "has_audio": False, "fps": None}
    if ff:
        try:
            r = subprocess.run([ff, "-hide_banner", "-i", str(p)], capture_output=True, text=True, errors="replace",
                               timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            txt = r.stderr
            m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", txt)
            if m:
                info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            v = re.search(r"Video:[^\n]*?[ ,](\d{2,5})x(\d{2,5})[ ,\[]", txt)
            if v:
                info.update(has_video=True, width=int(v.group(1)), height=int(v.group(2)))
                rot = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", txt)
                if rot and abs(float(rot.group(1))) in (90.0, 270.0):
                    info["width"], info["height"] = info["height"], info["width"]
            f = re.search(r"(\d+(?:\.\d+)?) fps", txt)
            if f:
                info["fps"] = float(f.group(1))
            info["has_audio"] = bool(re.search(r"Stream #[^\n]*Audio:", txt))
        except Exception:
            pass
    _PROBE_CACHE[key] = info
    return info


def _natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _kind(ext):
    ext = ext.lower()
    return ("image" if ext in IMG_EXT else "video" if ext in VID_EXT else "audio" if ext in AUD_EXT
            else "text" if ext in TXT_EXT else None)


def scan_media(limit=200):
    out = []
    for root, dirs, files in os.walk(state.WS):
        dirs[:] = sorted((d for d in dirs if d not in util.SKIP_DIRS and not d.startswith(".")), key=_natural_key)
        for name in sorted(files, key=_natural_key):
            p = pathlib.Path(root) / name
            kind = _kind(p.suffix)
            if not kind:
                continue
            st = p.stat()
            row = {"path": p.relative_to(state.WS).as_posix(), "kind": kind, "size": st.st_size, "mtime": st.st_mtime}
            if kind in ("image", "video", "audio") and find_ffmpeg():
                row.update({k: v for k, v in probe(p).items() if v not in (None, False)})
            out.append(row)
            if len(out) >= limit:
                return out
    return out


def media_summary():
    m = scan_media()
    counts = {k: sum(1 for x in m if x["kind"] == k) for k in ("image", "video", "audio", "text")}
    return {"ffmpeg": bool(find_ffmpeg()), "counts": counts, "files": [x["path"] for x in m][:60]}


def t_list_media(path="."):
    base = util.safe(path)
    if not base.is_dir():
        return "Это не папка: " + path
    rows = [r for r in scan_media() if (state.WS / r["path"]).resolve().is_relative_to(base)]
    if not rows:
        return "Медиафайлов (фото, видео, музыки, текстов) не найдено."
    lines = []
    for r in rows:
        extra = []
        if r.get("width"):
            extra.append(f"{r['width']}x{r['height']}" + (" портрет" if r["height"] > r["width"] else " альбом" if r["width"] > r["height"] else " квадрат"))
        if r.get("duration") and r["kind"] != "image":
            extra.append(f"{r['duration']:.1f} с")
        if r["kind"] == "video":
            extra.append("со звуком" if r.get("has_audio") else "без звука")
        date = time.strftime("%Y-%m-%d", time.localtime(r["mtime"]))
        lines.append(f"{r['kind']:5s} {r['path']}  ({', '.join(extra) or '-'}; {r['size'] // 1024} КБ; {date})")
    head = "" if find_ffmpeg() else "ВНИМАНИЕ: " + FFMPEG_HELP + "\n"
    return head + "\n".join(lines)[:8000]


# ---------- озвучка ----------
def _voice_name(lang, gender):
    table = {"ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"), "en": ("en-US-AriaNeural", "en-US-GuyNeural"),
             "uk": ("uk-UA-PolinaNeural", "uk-UA-OstapNeural"), "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural")}
    f, m = table.get((lang or "ru")[:2], table["en"])
    return m if (gender or "").lower().startswith("m") else f


def tts(text, out_wav, lang="ru", gender="female"):
    """Озвучивает текст в файл. Порядок: своя команда, Edge TTS, голос системы."""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("пустой текст для озвучки")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pca_tts_"))
    try:
        txt = tmp / "t.txt"
        txt.write_text(text, encoding="utf-8")
        out = pathlib.Path(out_wav)
        custom = os.environ.get("PC_AGENT_TTS_CMD") or state.CFG.get("tts_cmd")
        if custom:                                   # шаблон: программа {text_file} {out} (список JSON или строка)
            parts = custom if isinstance(custom, list) else (json.loads(custom) if custom.lstrip().startswith("[") else custom.split())
            cmd = [c.replace("{text_file}", str(txt)).replace("{out}", str(out)) for c in parts]
            code, o, e = _run(cmd, timeout=300)
            if code == 0 and out.exists():
                return out
            raise RuntimeError("своя команда озвучки не сработала: " + (e or o)[-200:])
        if importlib.util.find_spec("edge_tts"):
            mp3 = tmp / "v.mp3"
            code, o, e = _run([sys.executable, "-m", "edge_tts", "--voice", _voice_name(lang, gender), "--file", str(txt),
                               "--write-media", str(mp3)], timeout=180)
            if code == 0 and mp3.exists():
                _convert_audio(mp3, out)
                return out
        if os.name == "nt":
            ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"$v=$s.GetInstalledVoices()|Where-Object {{$_.VoiceInfo.Culture.Name -like '{(lang or 'ru')[:2]}*'}}|Select-Object -First 1; "
                  "if($v){$s.SelectVoice($v.VoiceInfo.Name)}else{Write-Error 'no voice'; exit 3}; "
                  "$s.SetOutputToWaveFile($env:PCA_OUT); $s.Speak([IO.File]::ReadAllText($env:PCA_TXT,[Text.Encoding]::UTF8)); $s.Dispose()")
            env = {**os.environ, "PCA_OUT": str(out), "PCA_TXT": str(txt)}
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, env=env,
                               timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0 and out.exists():
                return out
            raise RuntimeError("в Windows не установлен голос для языка «%s» (Параметры → Время и язык → Речь) "
                               "или установи качественный голос: pip install edge-tts" % lang)
        if sys.platform == "darwin" and shutil.which("say"):
            aiff = tmp / "v.aiff"
            subprocess.run(["say", "-v", "Milena" if (lang or "ru").startswith("ru") else "Samantha", "-o", str(aiff), "-f", str(txt)],
                           timeout=300, check=True)
            _convert_audio(aiff, out)
            return out
        for exe in ("espeak-ng", "espeak"):
            if shutil.which(exe):
                subprocess.run([exe, "-v", (lang or "ru")[:2], "-w", str(out), "-f", str(txt)], timeout=300, check=True)
                return out
        raise RuntimeError("нет программы озвучки. Установи качественный голос: pip install edge-tts (нужен интернет)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _convert_audio(src, dst):
    ff = find_ffmpeg()
    code, o, e = _run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ar", "44100", "-ac", "2", str(dst)], timeout=300)
    if code != 0:
        raise RuntimeError("не удалось преобразовать звук: " + e[-200:])


def t_make_voice(text, output="voice.wav", lang="ru", gender="female"):
    out = util.safe(output)
    if out.suffix.lower() not in (".wav", ".mp3"):
        out = out.with_suffix(".wav")
    if not fileops.confirm(f"Озвучить текст в файл {out.relative_to(state.WS).as_posix()}", text[:300]):
        return "Пользователь отклонил."
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        tts(text, out, lang, gender)
    except state.Cancelled:
        raise
    except Exception as e:
        return f"Озвучка не удалась: {e}"
    return f"Озвучка сохранена: {out.relative_to(state.WS).as_posix()} ({probe(out).get('duration') or 0:.1f} с)"


# ---------- шрифты и текст ----------
def find_font():
    env = state.CFG.get("video_font")
    cands = [env] if env else []
    if os.name == "nt":
        d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        cands += [os.path.join(d, n) for n in ("segoeui.ttf", "arial.ttf", "calibri.ttf", "tahoma.ttf")]
    elif sys.platform == "darwin":
        cands += ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"]
    cands += ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/noto/NotoSans-Regular.ttf"]
    return next((c for c in cands if c and os.path.exists(c)), None)


def _drawtext(textfile, W, H, big, font):
    fs = int(min(W, H) * (0.085 if big else 0.052))
    pos = "y=(h-text_h)/2" if big else f"y=h-text_h-{int(H * 0.08)}"
    return (f"drawtext=fontfile={font}:textfile={textfile}:fontsize={fs}:fontcolor=white:line_spacing={fs // 4}:"
            f"box=1:boxcolor=black@0.55:boxborderw={fs // 3}:x=(w-text_w)/2:{pos}:alpha='min(1,t/0.4)'"), fs


def _wrap(text, W, fs):
    width = max(12, int(W * 0.86 / (fs * 0.62)))
    return "\n".join(textwrap.fill(line, width) for line in text.split("\n"))


# ---------- сцены ----------
def _hex_color(c):
    c = (c or "#14181f").strip()
    return "0x" + c.lstrip("#") if re.fullmatch(r"#?[0-9a-fA-F]{6}", c) else c


def auto_scenes():
    """Сценарий «по умолчанию»: титул, все фото и видео по порядку имён, музыка, подписи из текстового файла."""
    media = scan_media()
    visuals = [m for m in media if m["kind"] in ("image", "video")]
    if not visuals:
        return [], ""
    texts = [m for m in media if m["kind"] == "text" and m["path"].lower() not in ("readme.md", "agents.md")]
    lines = []
    if texts:
        raw = (state.WS / texts[0]["path"]).read_text(encoding="utf-8", errors="replace")
        lines = [re.sub(r"^[#>*\-\s]+", "", l).strip() for l in raw.splitlines() if l.strip()]
    scenes = []
    if len(visuals) > 2:
        scenes.append({"title": state.WS.name.replace("_", " ").replace("-", " ").strip() or "Видео", "duration": 3})
    for i, v in enumerate(visuals):
        sc = {"file": v["path"]}
        if v["kind"] == "image":
            sc["duration"] = 4
        else:
            sc["duration"] = min(8, v.get("duration") or 8)
        if i < len(lines):
            sc["text"] = lines[i]
        scenes.append(sc)
    music = next((m["path"] for m in media if m["kind"] == "audio"), "")
    return scenes, music


def _normalize(scenes, errors):
    out = []
    for i, sc in enumerate(scenes, 1):
        if isinstance(sc, str):
            sc = {"file": sc}
        if not isinstance(sc, dict):
            errors.append(f"Сцена {i}: ожидался объект, получено {type(sc).__name__}")
            continue
        s = dict(sc)
        f = s.get("file")
        if f:
            try:
                p = util.safe(str(f))
            except ValueError as e:
                errors.append(f"Сцена {i}: {e}")
                continue
            if not p.is_file():
                near = ", ".join(r["path"] for r in scan_media()[:12])
                errors.append(f"Сцена {i}: файл не найден: {f}. Есть: {near}")
                continue
            kind = _kind(p.suffix)
            if kind not in ("image", "video"):
                errors.append(f"Сцена {i}: {f} — не фото и не видео")
                continue
            s.update(kind=kind, path=p, info=probe(p))
            if not s["info"]["width"]:
                errors.append(f"Сцена {i}: не удалось прочитать файл {f} (повреждён?)")
                continue
        elif s.get("title") or s.get("text"):
            s.update(kind="title")
            s["text"] = str(s.get("title") or s.get("text"))
        else:
            errors.append(f"Сцена {i}: нужно поле file (фото/видео) или title (титульный кадр)")
            continue
        out.append(s)
    return out


def _fmt_choice(scenes, requested):
    req = FORMAT_ALIASES.get((requested or "auto").lower(), (requested or "auto").lower())
    if req in ("landscape", "vertical", "square"):
        return req
    portrait = sum(1 for s in scenes if s.get("info") and s["info"]["height"] > s["info"]["width"] * 1.1)
    land = sum(1 for s in scenes if s.get("info") and s["info"]["width"] > s["info"]["height"] * 1.1)
    return "vertical" if portrait > land else "landscape"


def _prep_image(src, tmp, idx):
    """Поворот по EXIF и уменьшение огромных фото (если установлен Pillow)."""
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        im.thumbnail((3000, 3000))
        dst = tmp / f"img{idx}.jpg"
        im.save(dst, quality=92)
        return dst
    except Exception:
        return src


def _visual_filter(kind, sw, sh, W, H, fps, dur, effect):
    mismatch = abs((sw / sh) / (W / H) - 1) > 0.35
    if effect in ("auto", "", None):
        effect = "fit" if mismatch else ("zoom" if kind == "image" else "cover")
    n = max(2, int(dur * fps))
    if effect == "fit":
        return (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:6[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    if effect in ("zoom", "pan") and kind == "image":
        z = (f"z='min(1+0.12*on/{n},1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'" if effect == "zoom"
             else f"z=1.12:x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'")
        return (f"scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,crop={2 * W}:{2 * H},"
                f"zoompan={z}:d=1:s={W}x{H}:fps={fps},setsar=1")
    if effect in ("contain", "none"):
        return f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"


def _srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ---------- главный инструмент ----------
def t_make_video(output="video.mp4", scenes=None, format="auto", fps=30, quality="hd", music="", music_volume=None,
                 transition="fade", srt=True, voiceover=False, voice_lang="ru", voice_gender="female"):
    ff = find_ffmpeg()
    if not ff:
        return FFMPEG_HELP
    warnings, errors = [], []
    if isinstance(scenes, str):
        try:
            scenes = json.loads(scenes)
        except json.JSONDecodeError:
            return "Ошибка: scenes должен быть списком сцен [{\"file\": \"a.jpg\", \"duration\": 4}, ...]."
    auto = False
    if not scenes:
        scenes, auto_music = auto_scenes()
        auto = True
        music = music or auto_music
        if not scenes:
            return "В рабочей папке нет фото и видео для ролика. Добавь файлы и повтори."
    if not isinstance(scenes, list):
        return "Ошибка: scenes должен быть списком."
    items = _normalize(scenes, errors)
    if errors:
        return "Не могу собрать видео:\n" + "\n".join(errors[:12])
    if not items:
        return "Нет ни одной сцены."
    try:
        fps = max(10, min(60, int(fps)))
    except (TypeError, ValueError):
        fps = 30
    fmt = _fmt_choice(items, format)
    W, H = SIZES["draft" if str(quality).lower() in ("draft", "fast", "720", "черновик") else "hd"][fmt]
    out = util.safe(output)
    if out.suffix.lower() != ".mp4":
        out = out.with_suffix(".mp4")
    rel_out = out.relative_to(state.WS).as_posix()
    music_path = None
    if music:
        try:
            music_path = util.safe(str(music))
            if not music_path.is_file() or _kind(music_path.suffix) != "audio":
                return f"Музыка не найдена или это не аудиофайл: {music}"
        except ValueError as e:
            return "Ошибка: " + str(e)
    font = find_font()
    if not font:
        warnings.append("шрифт не найден — подписи не добавлены (укажи путь в настройке video_font)")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pca_video_"))
    try:
        if font:
            shutil.copy(font, tmp / "font.ttf")
        # --- озвучка и длительности ---
        for i, s in enumerate(items):
            speak = s.get("voice") or (s.get("text") if voiceover else None)
            s["voice_file"] = None
            if speak:
                _status(f"🎙 Озвучиваю сцену {i + 1}/{len(items)}…")
                try:
                    wav = tmp / f"voice{i}.wav"
                    tts(str(speak), wav, voice_lang, voice_gender)
                    s["voice_file"] = wav
                    s["voice_len"] = probe(wav).get("duration") or 0
                except state.Cancelled:
                    raise
                except Exception as e:
                    warnings.append(f"озвучка сцены {i + 1} не удалась: {e}")
                    if not any("озвучка" in w and "недоступна" in w for w in warnings):
                        warnings.append("озвучка недоступна — ролик собран без голоса")
                    voiceover = False
            if s["kind"] == "video":
                dur_src = s["info"].get("duration") or 8
                start = float(s.get("start") or 0)
                end = float(s["end"]) if s.get("end") else None
                dur = float(s["duration"]) if s.get("duration") else (min((end or dur_src) - start, 10))
                s["start"], s["dur"] = start, max(0.5, min(dur, dur_src - start))
            else:
                s["dur"] = float(s.get("duration") or (3 if s["kind"] == "title" else 4))
            if s.get("voice_file"):
                s["dur"] = max(s["dur"], s["voice_len"] + 0.6)       # сцена не короче озвучки
            if not s.get("text") and s.get("voice"):
                s["text"] = str(s["voice"])
        total = sum(s["dur"] for s in items)
        if total > MAX_TOTAL_SECONDS:
            return f"Ролик получается {total / 60:.0f} мин — слишком длинно. Сократи сцены (максимум {MAX_TOTAL_SECONDS // 60} мин)."
        has_voice = any(s.get("voice_file") for s in items)
        mv = float(music_volume) if music_volume is not None else (0.18 if has_voice else 0.45)

        detail = "\n".join(f"{i + 1}. {s.get('file') or 'титул'} — {s['dur']:.1f} с" + (f" «{s['text'][:40]}»" if s.get("text") else "")
                           for i, s in enumerate(items[:25]))
        if not fileops.confirm(f"Создать видео {rel_out}: {len(items)} сцен, {W}x{H}, ~{total:.0f} с"
                               + (", музыка" if music_path else "") + (", озвучка" if has_voice else ""), detail):
            return "Пользователь отклонил."

        # --- рендер сцен ---
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps),
               "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]
        clips, text_failed = [], False
        for i, s in enumerate(items):
            _status(f"🎬 Сцена {i + 1}/{len(items)}…")
            dur = s["dur"]
            clip = tmp / f"clip{i:04d}.mp4"
            vf_parts = []
            use_text = bool(s.get("text")) and font
            if s["kind"] == "image":
                src = _prep_image(s["path"], tmp, i)
                vin = ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(src)]
                vf_parts.append(_visual_filter("image", s["info"]["width"], s["info"]["height"], W, H, fps, dur, s.get("effect", "auto")))
            elif s["kind"] == "video":
                vin = ["-ss", f"{s['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(s["path"])]
                vf_parts.append(_visual_filter("video", s["info"]["width"], s["info"]["height"], W, H, fps, dur, s.get("effect", "auto")) + f",fps={fps}")
            else:
                vin = ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"color=c={_hex_color(s.get('bg'))}:s={W}x{H}:r={fps}"]
                vf_parts.append("setsar=1")
            textfile = None
            if use_text:
                big = s["kind"] == "title" or s.get("text_style") == "title"
                _, fs = _drawtext("x", W, H, big, "font.ttf")
                (tmp / f"t{i}.txt").write_text(_wrap(str(s["text"]), W, fs), encoding="utf-8")
                vf_parts.append(_drawtext(f"t{i}.txt", W, H, big, "font.ttf")[0])
                textfile = True
            if transition != "cut":
                f = min(0.35, dur / 3)
                vf_parts.append(f"fade=t=in:st=0:d={f:.2f},fade=t=out:st={dur - f:.2f}:d={f:.2f}")
            vf = ",".join(vf_parts)
            af = f"aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=0:{dur:.3f}"
            keep = s["kind"] == "video" and s.get("keep_audio") and s["info"].get("has_audio") and not s.get("voice_file")
            if s.get("voice_file"):
                ain, amap = ["-i", str(s["voice_file"])], ["-map", "0:v", "-map", "1:a"]
            elif keep:
                ain, amap = [], ["-map", "0:v:0", "-map", "0:a:0"]
            else:
                ain, amap = ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo"], ["-map", "0:v", "-map", "1:a"]
            cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"] + vin + ain + amap + ["-vf", vf, "-af", af] + enc + ["-t", f"{dur:.3f}", str(clip)]
            code, o, e = _run(cmd, cwd=str(tmp))
            if code != 0 and textfile:                      # частая причина — ffmpeg без шрифтов: пробуем без подписи
                text_failed = True
                vf2 = ",".join(p for p in vf_parts if not p.startswith("drawtext"))
                cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"] + vin + ain + amap + ["-vf", vf2, "-af", af] + enc + ["-t", f"{dur:.3f}", str(clip)]
                code, o, e = _run(cmd, cwd=str(tmp))
            if code != 0:
                return f"Рендер сцены {i + 1} ({s.get('file') or 'титул'}) не удался:\n{e[-600:]}"
            clips.append(clip)
        if text_failed:
            warnings.append("подписи не добавлены: ваш ffmpeg не смог нарисовать текст")

        # --- склейка и звук ---
        _status("🎞 Склеиваю ролик…")
        (tmp / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
        joined = tmp / "joined.mp4"
        code, o, e = _run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", str(joined)], cwd=str(tmp))
        if code != 0:
            return "Склейка не удалась:\n" + e[-600:]
        final = tmp / "final.mp4"
        if music_path:
            fade_at = max(0.0, total - 2.0)
            fc = (f"[0:a]volume=1[v];[1:a]volume={mv},afade=t=out:st={fade_at:.2f}:d=2[m];"
                  f"[v][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]")
            cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-stream_loop", "-1", "-i", str(music_path),
                   "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                   "-t", f"{total:.3f}", "-movflags", "+faststart", str(final)]
        else:
            cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(final)]
        code, o, e = _run(cmd, cwd=str(tmp))
        if code != 0:
            return "Не удалось добавить музыку:\n" + e[-600:]

        # --- сохранение с возможностью отката ---
        out.parent.mkdir(parents=True, exist_ok=True)
        bak = fileops.backup(out)
        shutil.move(str(final), str(out))
        fileops.set_undo({"kind": "file", "path": str(out), "bak": str(bak) if bak else None})
        srt_note = ""
        if srt and any(s.get("text") for s in items):
            t0, blocks, n = 0.0, [], 0
            for s in items:
                if s.get("text") and s["kind"] != "title":
                    n += 1
                    blocks.append(f"{n}\n{_srt_time(t0 + 0.2)} --> {_srt_time(t0 + s['dur'] - 0.2)}\n{s['text']}\n")
                t0 += s["dur"]
            if blocks:
                out.with_suffix(".srt").write_text("\n".join(blocks), encoding="utf-8")
                srt_note = f", субтитры {out.with_suffix('.srt').relative_to(state.WS).as_posix()}"
        info = probe(out)
        res = (f"Видео создано: {rel_out} ({info.get('duration') or total:.1f} с, {info.get('width')}x{info.get('height')}, "
               f"{out.stat().st_size / 1e6:.1f} МБ{srt_note}).")
        if auto:
            res += " Сценарий собран автоматически: " + json.dumps(
                [{k: v for k, v in sc.items()} for sc in scenes], ensure_ascii=False)[:1500]
        if warnings:
            res += "\nПредупреждения: " + "; ".join(warnings)
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _status("")


def t_check_video(path):
    ff = find_ffmpeg()
    if not ff:
        return FFMPEG_HELP
    f = util.safe(path)
    if not f.is_file():
        return "Файл не найден: " + path
    info = probe(f)
    if not info["has_video"]:
        return "В файле нет видео (повреждён или это не видеофайл)."
    dur = info["duration"] or 0
    rel = f.relative_to(state.WS).as_posix()
    lines = [f"{rel}: {dur:.1f} с, {info['width']}x{info['height']}, "
             f"{'со звуком' if info['has_audio'] else 'БЕЗ ЗВУКА'}, {f.stat().st_size / 1e6:.1f} МБ"]
    shots = state.WS / ".agent_shots"
    shots.mkdir(exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{util.uid()}.png"
    interval = max(0.5, dur / 4)
    code, o, e = _run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.2, dur * 0.1):.2f}", "-i", str(f),
                       "-vf", f"fps=1/{interval:.2f},scale=480:-1,tile=4x1", "-frames:v", "1", str(shots / name)], timeout=300)
    if code == 0 and (shots / name).exists():
        events.add_item({"role": "image", "id": util.uid(), "url": "/shots/" + name, "title": rel + " — кадры"})
        lines.append("Контрольные кадры показаны пользователю.")
        from . import browser
        if browser.profile_vision(state.ACTIVE):
            state.PENDING_IMAGES.append(str(shots / name))
            lines.append("Изображение придёт тебе следующим сообщением: оцени, всё ли выглядит правильно.")
    else:
        lines.append("Контрольные кадры получить не удалось.")
    if dur < 1:
        lines.append("ВНИМАНИЕ: ролик короче секунды.")
    return "\n".join(lines)


def install_ffmpeg():
    """Установка ffmpeg одним нажатием (через pip-пакет imageio-ffmpeg)."""
    if getattr(sys, "frozen", False):
        return False, "В собранной версии (.exe) поставь ffmpeg так: в PowerShell  winget install Gyan.FFmpeg  и перезапусти агента."
    code, o, e = _run([sys.executable, "-m", "pip", "install", "imageio-ffmpeg"], timeout=900)
    if code != 0:
        return False, (e or o)[-400:]
    return bool(find_ffmpeg()), (o or "")[-200:]
