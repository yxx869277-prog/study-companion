"""Hardware-free regression tests; all content is synthetic."""
import contextlib
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
import local_api
import audio
import mic
import tts
import summarize


def scratch():
    # Test artifacts are outside the publication tree and retained for inspection.
    parent = os.environ.get("STUDY_TEST_OUTPUT")
    if parent:
        Path(parent).mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="study-test-", dir=parent))


class LocalApiTests(unittest.TestCase):
    def test_remote_hosts_and_credentials_rejected_before_request(self):
        for url in ("https://example.org/api/chat", "http://198.51.100.10:11434",
                    "http://localhost:11434", "http://user:pass@127.0.0.1:11434",
                    "http://127.0.0.1:11434/#fragment"):
            with self.subTest(url=url), patch("requests.Session") as session:
                with self.assertRaises(ValueError):
                    local_api.request("POST", url, json={"text": "SYNTHETIC"})
                session.assert_not_called()

    def test_local_request_ignores_proxy_and_refuses_redirect(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                hits.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(307)
                self.send_header("Location", "/unexpected")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"HTTP_PROXY": "http://198.51.100.20:9",
                                        "ALL_PROXY": "http://198.51.100.20:9",
                                        "NO_PROXY": ""}):
                with self.assertRaises(ValueError):
                    local_api.request("POST", f"http://127.0.0.1:{server.server_port}/chat",
                                      json={"text": "SYNTHETIC"}, timeout=2)
            self.assertEqual(hits, ["/chat"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_cloud_metadata_blocks_content_request(self):
        for metadata in ({"remote_host": "https://example.org", "model_info": {"x": 1}},
                         {"remote_model": "example-cloud", "model_info": {"x": 1}},
                         {"model_info": {}}):
            response = MagicMock()
            response.json.return_value = metadata
            with patch.object(local_api, "request", return_value=response) as send:
                with self.assertRaises(ValueError):
                    local_api.ollama_chat({"model": "local-name",
                                          "messages": [{"content": "SYNTHETIC"}]}, 2)
                self.assertEqual(send.call_count, 1)
                self.assertTrue(send.call_args.args[1].endswith("/api/show"))
                self.assertEqual(send.call_args.kwargs["json"], {"model": "local-name"})

    def test_local_model_metadata_then_content(self):
        metadata, response = MagicMock(), MagicMock()
        metadata.json.return_value = {"model_info": {"general.architecture": "qwen"},
                                     "details": {"format": "gguf"}}
        response.json.return_value = {"message": {"content": "OK"}}
        with patch.object(local_api, "request", side_effect=[metadata, response]) as send:
            out = local_api.ollama_chat({"model": "local-name",
                                        "messages": [{"content": "SYNTHETIC"}]}, 2)
            self.assertEqual(out["message"]["content"], "OK")
            self.assertEqual(send.call_count, 2)
            self.assertTrue(send.call_args.args[1].endswith("/api/chat"))

    def test_text_generation_uses_selected_llama_backend(self):
        response = MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": "SYNTHETIC"}}]}
        with patch.object(config, "VISION_BACKEND", "llama"), \
                patch.object(local_api, "request", return_value=response) as send, \
                patch.object(local_api, "ollama_chat") as ollama:
            self.assertEqual(local_api.text_chat("TEST", "ignored"), "SYNTHETIC")
            self.assertIn("/v1/chat/completions", send.call_args.args[1])
            ollama.assert_not_called()

    def test_ollama_cpu_mode_is_per_request_and_preserves_caller_options(self):
        payload = {"model": "local-name", "options": {"num_predict": 16},
                   "messages": [{"content": "SYNTHETIC"}]}
        before = json.dumps(payload, sort_keys=True)
        for cpu_only in (True, False):
            metadata, response = MagicMock(), MagicMock()
            metadata.json.return_value = {"model_info": {"general.architecture": "qwen"}}
            with patch.object(config, "OLLAMA_CPU_ONLY", cpu_only), \
                    patch.object(local_api, "request", side_effect=[metadata, response]) as send:
                local_api.ollama_chat(payload, 2)
                sent = send.call_args.kwargs["json"]
                self.assertEqual(sent["options"]["num_predict"], 16)
                self.assertEqual(sent["options"]["num_ctx"], config.OLLAMA_CTX)
                self.assertEqual(sent["keep_alive"], 0)
                self.assertEqual(sent["options"].get("num_gpu"), 0 if cpu_only else None)
            self.assertEqual(json.dumps(payload, sort_keys=True), before)


class CaptureTests(unittest.TestCase):
    def test_mic_does_not_open_before_activation_and_releases_on_stop(self):
        opened, released = threading.Event(), threading.Event()
        stream = MagicMock()
        stream.get_read_available.return_value = 0
        stream.close.side_effect = released.set
        device = MagicMock()
        device.get_default_input_device_info.return_value = {
            "defaultSampleRate": 16000, "maxInputChannels": 1, "index": 0}
        def open_stream(**kwargs):
            opened.set()
            return stream
        device.open.side_effect = open_stream
        with patch.object(config, "MONITORING_ACTIVE", True), \
                patch.object(mic.pyaudio, "PyAudio", return_value=device) as factory, \
                patch.object(config, "LOG_DIR", str(scratch())):
            recorder = mic.MicRecorder()
            recorder.start()
            try:
                self.assertFalse(opened.wait(0.15))
                factory.assert_not_called()
                recorder.start_recording()
                self.assertTrue(opened.wait(2))
                recorder.stop_recording()
                self.assertTrue(released.wait(2))
            finally:
                recorder.stop()
                recorder.join(timeout=2)
            self.assertFalse(recorder.is_alive())
            device.terminate.assert_called()

    def test_cancelled_system_audio_never_opens_device(self):
        stop = threading.Event()
        stop.set()
        with patch.object(audio.pyaudio, "PyAudio") as factory:
            self.assertFalse(audio.record_segment(1, str(scratch() / "unused.wav"), stop))
            factory.assert_not_called()

    def test_pause_gate_blocks_late_recorder_start(self):
        with patch.object(audio.pyaudio, "PyAudio") as factory:
            self.assertFalse(audio.record_segment(
                1, str(scratch() / "unused.wav"), allowed=lambda: False))
            factory.assert_not_called()

    def test_system_audio_cancellation_closes_device_without_saving(self):
        stop = threading.Event()
        stream, device = MagicMock(), MagicMock()
        stream.get_read_available.side_effect = lambda: (stop.set() or 0)
        device.open.return_value = stream
        path = scratch() / "unused.wav"
        with patch.object(audio.pyaudio, "PyAudio", return_value=device), \
                patch.object(audio, "_get_loopback_device", return_value={
                    "defaultSampleRate": 16000, "maxInputChannels": 1, "index": 0}):
            self.assertFalse(audio.record_segment(1, str(path), stop))
        self.assertFalse(path.exists())
        stream.close.assert_called()
        device.terminate.assert_called()

    def test_tts_disabled_does_not_start_worker(self):
        with patch.object(config, "TTS_ENABLED", False), \
                patch.object(config, "MONITORING_ACTIVE", True), \
                patch.object(tts, "_ensure_worker") as worker:
            tts.speak("SYNTHETIC")
            worker.assert_not_called()

    def test_queued_tts_is_dropped_after_disabling(self):
        with patch.object(config, "TTS_ENABLED", False), \
                patch.object(tts._q, "get", side_effect=["SYNTHETIC", StopIteration]), \
                patch.object(tts, "_synthesize") as synthesize:
            with self.assertRaises(StopIteration):
                tts._work()
            synthesize.assert_not_called()


class MainControlsTests(unittest.TestCase):
    def run_main_scenario(self, resume):
        temp = scratch()
        (temp / "model").mkdir()
        (temp / "model" / "model.bin").write_bytes(b"SYNTHETIC-NOT-A-MODEL")
        capture_instance = MagicMock()
        capture_instance.changed.return_value = (True, 10)
        mic_instance = MagicMock()
        mic_instance.available = True
        recording = {"active": False}
        mic_instance.is_recording.side_effect = lambda: recording["active"]
        mic_instance.toggle.side_effect = lambda: recording.update(
            active=not recording["active"]) or recording["active"]
        mic_instance.start_recording.side_effect = lambda: recording.update(active=True)
        mic_instance.stop_recording.side_effect = lambda: recording.update(active=False)
        recorder_instance = MagicMock()
        process = MagicMock()
        process.poll.return_value = None
        fake_webcam = MagicMock()
        fake_audio = types.SimpleNamespace(launch_worker=MagicMock(return_value=process),
                                           CourseRecorder=MagicMock(return_value=recorder_instance))
        fake_modules = {
            "faulthandler": types.SimpleNamespace(enable=MagicMock()),
            "audio": fake_audio,
            "capture": types.SimpleNamespace(ScreenCapture=lambda: capture_instance),
            "ocr_sub": types.SimpleNamespace(warmup=MagicMock(), extract_subtitles=MagicMock(return_value=[]),
                                             append_subtitles=MagicMock()),
            "rules": types.SimpleNamespace(RuleEngine=MagicMock(return_value=MagicMock())),
            "vision": types.SimpleNamespace(classify=MagicMock(return_value={
                "state": "网课", "detail": "synthetic lesson", "course_hint": None}),
                current_backend=lambda: "ollama"),
            "mic": types.SimpleNamespace(MicRecorder=lambda: mic_instance),
            "webcam": types.SimpleNamespace(WebcamMonitor=fake_webcam),
            "cleanup": types.SimpleNamespace(run=MagicMock()),
            "logger": types.SimpleNamespace(log=MagicMock()),
            "notify": types.SimpleNamespace(notify=MagicMock()),
            "keyboard": types.SimpleNamespace(add_hotkey=MagicMock()),
            "llama_server": types.SimpleNamespace(stop_if_owned=MagicMock()),
        }
        targets = []
        class FakeThread:
            def __init__(self, target, **kwargs):
                targets.append(target)
            def start(self):
                pass
        patch_values = dict(LOG_DIR=str(temp), UI_QUEUE=str(temp / "ui.jsonl"),
                            UI_CMD_QUEUE=str(temp / "commands.jsonl"),
                            WHISPER_MODEL=str(temp / "model"), VISION_BACKEND="ollama",
                            MIC_ALWAYS_ON=False, WEBCAM_ENABLED=False, TTS_ENABLED=False,
                            COURSE_AUDIO_ENABLED=False, OCR_ENABLED=False,
                            MONITORING_ACTIVE=False)
        old_stdout, old_stderr, old_hook = sys.stdout, sys.stderr, sys.excepthook
        application_stream = None
        loaded = None
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, fake_modules))
            for key, value in patch_values.items():
                stack.enter_context(patch.object(config, key, value))
            try:
                loaded = runpy.run_path(str(ROOT / "main.py"), run_name="privacy_test_main")
                application_stream = sys.stdout
                sys.stdout, sys.stderr, sys.excepthook = old_stdout, old_stderr, old_hook
                namespace = loaded["main"].__globals__
                namespace["_launch_ui"] = lambda: process
                namespace["threading"] = types.SimpleNamespace(Thread=FakeThread)
                phase = [0]
                def sleep(_seconds):
                    import inspect
                    command_loop = next(f for f in targets if f.__name__ == "_ui_cmd_loop")
                    closure = inspect.getclosurevars(command_loop).nonlocals
                    flags = closure["flags"]
                    apply_set = closure["_apply_set"]
                    if phase[0] == 0:
                        self.assertEqual(capture_instance.grab.call_count, 0)
                        self.assertFalse(config.MONITORING_ACTIVE)
                        if not resume:
                            flags["quit"] = True
                        else:
                            apply_set("PAUSED", False)
                            for key in ("COURSE_AUDIO_ENABLED", "OCR_ENABLED",
                                        "WEBCAM_ENABLED", "MIC_ALWAYS_ON", "TTS_ENABLED"):
                                apply_set(key, True)
                            self.assertTrue(recording["active"])
                    elif phase[0] == 1:
                        self.assertEqual(capture_instance.grab.call_count, 1)
                        self.assertEqual(recorder_instance.start.call_count, 1)
                        apply_set("PAUSED", True)
                        self.assertFalse(recording["active"])
                        self.assertFalse(config.MONITORING_ACTIVE)
                        self.assertTrue(all(not getattr(config, key) for key in
                                            ("COURSE_AUDIO_ENABLED", "OCR_ENABLED",
                                             "WEBCAM_ENABLED", "MIC_ALWAYS_ON", "TTS_ENABLED")))
                        recorder_instance.stop.assert_called()
                        self.assertFalse(fake_webcam.call_args.kwargs["should_sample"]())
                    else:
                        self.assertEqual(capture_instance.grab.call_count, 1)
                        flags["quit"] = True
                    phase[0] += 1
                import time
                namespace["time"] = types.SimpleNamespace(
                    sleep=sleep, time=time.time, strftime=time.strftime)
                loaded["main"]()
                self.assertEqual(capture_instance.grab.call_count, 1 if resume else 0)
                if not resume:
                    fake_audio.launch_worker.assert_not_called()
                    recorder_instance.start.assert_not_called()
            finally:
                sys.stdout, sys.stderr, sys.excepthook = old_stdout, old_stderr, old_hook
                if application_stream is not None:
                    application_stream._log.close()
                if loaded is not None:
                    loaded["_crash_f"].close()

    def test_startup_collects_nothing(self):
        self.run_main_scenario(False)

    def test_pause_stops_active_recording_and_all_optional_features(self):
        self.run_main_scenario(True)


class ReportTests(unittest.TestCase):
    def test_report_generation_preserves_existing_report(self):
        temp = scratch()
        reports = temp / "reports"
        reports.mkdir()
        target = reports / "2000-01-01.md"
        target.write_text("SYNTHETIC EXISTING REPORT", encoding="utf-8")
        with patch.object(config, "LOG_DIR", str(temp)), \
                patch.object(config, "REPORT_DIR", str(reports)), \
                patch.object(local_api, "text_chat", return_value="SYNTHETIC NEW REPORT"), \
                patch.object(sys, "argv", ["summarize.py", "2000-01-01"]):
            summarize.main()
        self.assertIn("SYNTHETIC NEW REPORT", target.read_text(encoding="utf-8"))
        backups = list(reports.glob("*.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "SYNTHETIC EXISTING REPORT")

    def test_invalid_report_date_rejected(self):
        with patch.object(sys, "argv", ["summarize.py", "../outside"]):
            with self.assertRaises(ValueError):
                summarize.main()


if __name__ == "__main__":
    unittest.main()
