# -*- coding: utf-8 -*-
"""Видео из файлов папки: настоящий ffmpeg, настоящий рендер (тест пропускается, если ffmpeg нет)."""
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from pcagent import state, video
from tests.fakes import FakeLLM
from tests.harness import AgentCase
from tests.unit_base import UnitCase

FF = video.find_ffmpeg()
FAKE_TTS = str(pathlib.Path(__file__).resolve().parent / "fake_tts.py")


def _ff(*args):
    subprocess.run([FF, "-y", "-loglevel", "error", *args], check=True)


def mean_volume(path, ss, length):
    """Средняя громкость отрезка в дБ (около -91 — тишина)."""
    r = subprocess.run([FF, "-hide_banner", "-ss", str(ss), "-t", str(length), "-i", str(path), "-vn", "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else -99.0


def white_pixels(path, t, band):
    """Сколько белых пикселей в полосе кадра (доля высоты от и до) — признак нарисованной подписи."""
    from PIL import Image
    png = pathlib.Path(tempfile.mkdtemp()) / "f.png"
    _ff("-ss", str(t), "-i", str(path), "-frames:v", "1", str(png))
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.crop((0, int(h * band[0]), w, int(h * band[1]))).getdata()
    n = sum(1 for p in px if min(p) > 235)
    shutil.rmtree(png.parent, ignore_errors=True)
    return n


@unittest.skipUnless(FF, "ffmpeg не найден")
class VideoCase(UnitCase):
    media = None

    @classmethod
    def setUpClass(cls):
        cls.media = pathlib.Path(tempfile.mkdtemp(prefix="pca_media_"))
        m = cls.media
        _ff("-f", "lavfi", "-i", "color=c=0xc83c3c:s=800x450", "-frames:v", "1", str(m / "a.jpg"))
        _ff("-f", "lavfi", "-i", "color=c=0x3c9b5a:s=450x800", "-frames:v", "1", str(m / "b.jpg"))
        _ff("-f", "lavfi", "-i", "color=c=0x3c5ac8:s=600x600", "-frames:v", "1", str(m / "c.jpg"))
        _ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(m / "clip.mp4"))
        _ff("-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-c:a", "pcm_s16le", str(m / "music.wav"))
        (m / "script.txt").write_text("Первая сцена\nВторая сцена\nТретья сцена\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.media, ignore_errors=True)

    def setUp(self):
        super().setUp()
        state.AUTO = True
        self.statuses = []
        p = mock.patch.object(video.events, "emit", side_effect=lambda ev: self.statuses.append(ev))
        p.start()
        self.addCleanup(p.stop)

    def put(self, *names):
        for n in names:
            shutil.copy(self.media / n, self.ws / n)

    def info(self, rel):
        return video.probe(self.ws / rel)


class Scanning(VideoCase):
    def test_list_media_describes_files(self):
        self.put("a.jpg", "b.jpg", "clip.mp4", "music.wav", "script.txt")
        (self.ws / "notes.docx").write_text("не медиа")
        out = video.t_list_media()
        self.assertIn("a.jpg", out)
        self.assertIn("800x450 альбом", out)
        self.assertIn("450x800 портрет", out)
        self.assertRegex(out, r"clip\.mp4.*4\.0 с.*со звуком")
        self.assertIn("music.wav", out)
        self.assertIn("script.txt", out)
        self.assertNotIn("notes.docx", out)

    def test_natural_sort_and_summary(self):
        for n in ("img10.jpg", "img2.jpg", "img1.jpg"):
            shutil.copy(self.media / "a.jpg", self.ws / n)
        names = [r["path"] for r in video.scan_media()]
        self.assertEqual(names, ["img1.jpg", "img2.jpg", "img10.jpg"])
        self.assertEqual(video.media_summary()["counts"]["image"], 3)

    def test_internal_folders_are_ignored(self):
        (self.ws / ".agent_shots").mkdir()
        shutil.copy(self.media / "a.jpg", self.ws / ".agent_shots" / "x.jpg")
        self.assertEqual(video.scan_media(), [])

    def test_empty_folder(self):
        self.assertIn("не найдено", video.t_list_media())
        self.assertIn("нет фото и видео", video.t_make_video(quality="draft"))


class Rendering(VideoCase):
    def test_auto_video_landscape_with_music_captions_and_srt(self):
        self.put("a.jpg", "c.jpg", "clip.mp4", "music.wav", "script.txt")
        res = video.t_make_video("out/auto.mp4", quality="draft")
        self.assertIn("Видео создано: out/auto.mp4", res)
        self.assertIn("автоматически", res)
        i = self.info("out/auto.mp4")
        self.assertEqual((i["width"], i["height"]), (1280, 720))
        self.assertTrue(i["has_audio"] and i["has_video"])
        self.assertAlmostEqual(i["duration"], 3 + 4 + 4 + 4, delta=0.6)            # титул + 2 фото + клип
        srt = (self.ws / "out" / "auto.srt").read_text(encoding="utf-8")
        self.assertIn("Первая сцена", srt)
        self.assertRegex(srt, r"00:00:0\d,\d{3} --> 00:00:\d\d,\d{3}")
        self.assertTrue(state.UNDO, "создание видео должно быть отменяемым")
        self.assertTrue(any(e.get("type") == "status" and "Сцена" in e.get("text", "") for e in self.statuses))
        self.assertEqual(glob.glob(os.path.join(tempfile.gettempdir(), "pca_video_*")), [], "временные файлы не удалены")

    def test_auto_format_picks_vertical_for_portrait_photos(self):
        for n in ("p1.jpg", "p2.jpg"):
            shutil.copy(self.media / "b.jpg", self.ws / n)
        video.t_make_video("v.mp4", quality="draft")
        i = self.info("v.mp4")
        self.assertEqual((i["width"], i["height"]), (720, 1280))

    def test_explicit_scenes_trim_effects_and_keep_audio(self):
        self.put("a.jpg", "b.jpg", "clip.mp4", "music.wav")
        scenes = [{"title": "Заголовок ролика", "duration": 2, "bg": "#202040"},
                  {"file": "b.jpg", "duration": 2, "effect": "fit"},        # портрет в альбомный кадр: размытый фон
                  {"file": "a.jpg", "duration": 2, "effect": "pan", "text": "Панорама"},
                  {"file": "clip.mp4", "start": 1, "duration": 2, "keep_audio": True}]
        res = video.t_make_video("e.mp4", scenes=scenes, format="landscape", quality="draft", music="music.wav", transition="cut")
        self.assertIn("Видео создано", res)
        i = self.info("e.mp4")
        self.assertAlmostEqual(i["duration"], 8.0, delta=0.5)
        self.assertEqual((i["width"], i["height"]), (1280, 720))

    def test_short_music_loops_and_ends_with_video(self):
        self.put("a.jpg", "music.wav")                                   # музыка 3 с, ролик 8 с
        video.t_make_video("m.mp4", scenes=[{"file": "a.jpg", "duration": 8}], quality="draft", music="music.wav")
        self.assertAlmostEqual(self.info("m.mp4")["duration"], 8.0, delta=0.5)
        self.assertGreater(mean_volume(self.ws / "m.mp4", 5, 2.5), -50, "музыка закончилась раньше ролика (не зациклена)")
        video.t_make_video("m2.mp4", scenes=[{"file": "a.jpg", "duration": 4}], quality="draft")        # без музыки — тишина
        self.assertLess(mean_volume(self.ws / "m2.mp4", 0.5, 3), -80)

    def test_vertical_requested_explicitly(self):
        self.put("a.jpg")
        video.t_make_video("s.mp4", scenes=["a.jpg"], format="вертикальное", quality="draft")
        self.assertEqual((self.info("s.mp4")["width"], self.info("s.mp4")["height"]), (720, 1280))

    def test_overwrite_keeps_backup_and_undo_restores(self):
        from pcagent import fileops
        self.put("a.jpg")
        video.t_make_video("o.mp4", scenes=[{"file": "a.jpg", "duration": 2}], quality="draft")
        first = (self.ws / "o.mp4").read_bytes()
        video.t_make_video("o.mp4", scenes=[{"file": "a.jpg", "duration": 3}], quality="draft")
        self.assertNotEqual(first, (self.ws / "o.mp4").read_bytes())
        last = list(state.UNDO)[-1]
        self.assertIsNone(fileops.do_undo(last))
        self.assertEqual(first, (self.ws / "o.mp4").read_bytes(), "откат должен вернуть прежний ролик")


class Captions(VideoCase):
    def test_caption_is_drawn_only_where_requested(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("нужен Pillow для разбора кадров")
        self.put("a.jpg")
        video.t_make_video("c.mp4", scenes=[{"file": "a.jpg", "duration": 3, "text": "Подпись внизу кадра", "effect": "none"},
                                            {"file": "a.jpg", "duration": 3, "effect": "none"},
                                            {"title": "Титул по центру", "duration": 3}], quality="draft")
        self.assertGreater(white_pixels(self.ws / "c.mp4", 1.5, (0.7, 0.95)), 150, "подпись не нарисована")
        self.assertEqual(white_pixels(self.ws / "c.mp4", 4.5, (0.7, 0.95)), 0, "подпись появилась там, где её не просили")
        self.assertGreater(white_pixels(self.ws / "c.mp4", 7.5, (0.35, 0.65)), 150, "текст титульного кадра не нарисован")

    def test_keep_audio_switch(self):
        self.put("clip.mp4")
        video.t_make_video("k.mp4", scenes=[{"file": "clip.mp4", "duration": 3, "keep_audio": True}], quality="draft")
        video.t_make_video("q.mp4", scenes=[{"file": "clip.mp4", "duration": 3}], quality="draft")
        self.assertGreater(mean_volume(self.ws / "k.mp4", 0.7, 2), -40, "звук клипа потерян")
        self.assertLess(mean_volume(self.ws / "q.mp4", 0.7, 2), -80, "звук клипа не должен сохраняться без keep_audio")


class Narration(VideoCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"PC_AGENT_TTS_CMD": json.dumps([sys.executable, FAKE_TTS, "{text_file}", "{out}"])})
        p.start()
        self.addCleanup(p.stop)
        self.put("a.jpg", "b.jpg")

    def test_scene_is_stretched_to_fit_voice(self):
        text = "Это довольно длинный текст озвучки для проверки, что сцена не обрезает голос на полуслове."
        voice_len = min(6.0, 0.5 + 0.05 * len(text))
        res = video.t_make_video("n.mp4", scenes=[{"file": "a.jpg", "duration": 1, "voice": text}], quality="draft")
        self.assertIn("Видео создано", res)
        i = self.info("n.mp4")
        self.assertAlmostEqual(i["duration"], voice_len + 0.6, delta=0.5)
        self.assertTrue(i["has_audio"])
        self.assertGreater(mean_volume(self.ws / "n.mp4", 0.7, 1.5), -40, "голос не слышен в ролике")

    def test_voiceover_flag_speaks_captions_and_srt_contains_them(self):
        video.t_make_video("v.mp4", scenes=[{"file": "a.jpg", "text": "Привет"}, {"file": "b.jpg", "text": "Пока"}],
                           quality="draft", voiceover=True)
        self.assertGreater(self.info("v.mp4")["duration"], 2 * 1.0)
        self.assertIn("Привет", (self.ws / "v.srt").read_text(encoding="utf-8"))

    def test_voice_failure_still_produces_silent_video_with_warning(self):
        res = video.t_make_video("w.mp4", scenes=[{"file": "a.jpg", "duration": 2, "voice": "СБОЙ озвучки"}], quality="draft")
        self.assertIn("Видео создано", res)
        self.assertIn("озвучка недоступна", res)

    def test_make_voice_tool(self):
        res = video.t_make_voice("Короткий текст", "voice/hello.wav")
        self.assertIn("Озвучка сохранена", res)
        self.assertTrue((self.ws / "voice" / "hello.wav").exists())
        self.assertIn("не удалась", video.t_make_voice("СБОЙ", "voice/bad.wav"))


class Errors(VideoCase):
    def test_bad_scenes_are_explained(self):
        self.put("a.jpg", "music.wav", "script.txt")
        out = video.t_make_video("x.mp4", scenes=[{"file": "нет.jpg"}, {"file": "music.wav"}, {"file": "../секрет.jpg"}, {"duration": 3}])
        for part in ("Сцена 1: файл не найден", "Сцена 2", "не фото и не видео", "Сцена 3", "Сцена 4: нужно поле file"):
            self.assertIn(part, out)
        self.assertFalse((self.ws / "x.mp4").exists())

    def test_wrong_argument_types(self):
        self.assertIn("Ошибка", video.t_make_video("x.mp4", scenes="не json"))
        self.assertIn("Ошибка", video.t_make_video("x.mp4", scenes={"file": "a.jpg"}))
        self.put("a.jpg")
        self.assertIn("не найдена", video.t_make_video("x.mp4", scenes=["a.jpg"], music="нет.mp3"))

    def test_corrupt_media_is_reported(self):
        (self.ws / "bad.jpg").write_text("это не картинка")
        self.assertIn("повреждён", video.t_make_video("x.mp4", scenes=["bad.jpg"]))

    def test_no_ffmpeg_gives_install_hint(self):
        with mock.patch.object(video, "find_ffmpeg", return_value=None):
            self.assertIn("winget install Gyan.FFmpeg", video.t_make_video())
            self.assertIn("winget", video.t_check_video("x.mp4"))

    def test_too_long_video_is_refused(self):
        self.put("a.jpg")
        out = video.t_make_video("x.mp4", scenes=[{"file": "a.jpg", "duration": 1500}] * 2)
        self.assertIn("слишком длинно", out)

    def test_declined_confirmation_creates_nothing(self):
        self.put("a.jpg")
        state.AUTO = False
        with mock.patch.object(video.fileops, "confirm", return_value=False):
            self.assertIn("отклонил", video.t_make_video("x.mp4", scenes=["a.jpg"], quality="draft"))
        self.assertFalse((self.ws / "x.mp4").exists())

    def test_cannot_write_outside_workspace(self):
        self.put("a.jpg")
        with self.assertRaises(ValueError):
            video.t_make_video("../escaped.mp4", scenes=["a.jpg"], quality="draft")

    def test_stop_button_interrupts_render_and_cleans_up(self):
        self.put("a.jpg")
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "pca_video_*")))
        result = {}

        def work():
            try:
                video.t_make_video("long.mp4", scenes=[{"file": "a.jpg", "duration": 6, "effect": "zoom"}] * 8, quality="hd")
            except BaseException as e:
                result["err"] = e

        t = threading.Thread(target=work)
        t.start()
        time.sleep(1.5)
        state.CANCEL.set()
        t.join(30)
        self.assertFalse(t.is_alive(), "рендер не остановился")
        self.assertIsInstance(result.get("err"), state.Cancelled)
        self.assertFalse((self.ws / "long.mp4").exists())
        self.assertEqual(set(glob.glob(os.path.join(tempfile.gettempdir(), "pca_video_*"))) - before, set())


class Checking(VideoCase):
    def test_check_video_reports_and_shows_frames(self):
        self.put("a.jpg", "clip.mp4")
        video.t_make_video("r.mp4", scenes=[{"file": "a.jpg", "duration": 2}, {"file": "clip.mp4", "keep_audio": True, "duration": 2}],
                           quality="draft")
        state.ACTIVE = {"model": "deepseek-chat"}
        out = video.t_check_video("r.mp4")
        self.assertRegex(out, r"r\.mp4: 4\.\d с, 1280x720, со звуком")
        self.assertIn("Контрольные кадры показаны", out)
        self.assertTrue(any(i["role"] == "image" for i in self.items))
        self.assertEqual(len(os.listdir(self.ws / ".agent_shots")), 1)
        self.assertEqual(state.PENDING_IMAGES, [])
        state.ACTIVE = {"model": "qwen2.5vl:7b"}                    # модель, умеющая смотреть картинки, получит кадры
        self.assertIn("придёт тебе следующим сообщением", video.t_check_video("r.mp4"))
        self.assertEqual(len(state.PENDING_IMAGES), 1)

    def test_check_video_on_bad_files(self):
        (self.ws / "bad.mp4").write_text("не видео")
        self.assertIn("нет видео", video.t_check_video("bad.mp4"))
        self.assertIn("не найден", video.t_check_video("ghost.mp4"))


@unittest.skipUnless(FF, "ffmpeg не найден")
class AgentVideo(AgentCase):
    def _media(self):
        for n in ("a.jpg", "b.jpg"):
            shutil.copy(VideoCase.media / n, os.path.join(self.ws, n))

    @classmethod
    def setUpClass(cls):
        VideoCase.setUpClass.__func__(VideoCase)

    @classmethod
    def tearDownClass(cls):
        VideoCase.tearDownClass.__func__(VideoCase)

    def test_agent_builds_video_with_tools(self):
        self._media()
        llm = self.serve(FakeLLM("v"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})
        self.cloud(a, llm, "video")
        a.post("auto", {"value": True})
        a.clear()
        a.post("chat", {"message": "создай видео"})
        self.assertTrue(a.wait_idle(60), "агент не закончил")
        self.assertEqual([i["name"] for i in a.items("tool")], ["list_media", "make_video", "check_video"])
        self.assertTrue(os.path.exists(os.path.join(self.ws, "result.mp4")))
        self.assertTrue(a.items("image"), "контрольные кадры не показаны в чате")
        self.assertIn("Видео готово", a.deltas())

    def test_button_flow_media_list_and_autopilot_task(self):
        self._media()
        llm = self.serve(FakeLLM("v"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1"})
        self.cloud(a, llm, "video")
        info = a.post("media_list")
        self.assertTrue(info["ffmpeg"])
        self.assertEqual(info["counts"]["image"], 2)
        a.clear()
        r = a.post("make_video", {"idea": "отчёт о поездке", "format": "vertical", "voice": True, "seconds": "20", "music": False})
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(a.wait_idle(60))
        task = a.items("user")[0]["text"]
        for part in ("отчёт о поездке", "9:16", "Озвучь", "около 20 секунд", "Без музыки", "list_media"):
            self.assertIn(part, task)
        self.assertEqual(a.items("confirm"), [], "автопилот не спрашивает разрешений")
        self.assertTrue(os.path.exists(os.path.join(self.ws, "result.mp4")))

    def test_button_refuses_when_ffmpeg_missing(self):
        llm = self.serve(FakeLLM("v"))
        a = self.start(env={"PC_AGENT_NO_PROBE": "1", "PC_AGENT_FFMPEG": "", "PATH": os.path.dirname(sys.executable)})
        self.cloud(a, llm, "video")
        if a.post("media_list")["ffmpeg"]:
            self.skipTest("ffmpeg находится и без PATH (например, через imageio-ffmpeg)")
        self.assertEqual(a.post("make_video", {}).get("_status"), 400)


if __name__ == "__main__":
    unittest.main()
