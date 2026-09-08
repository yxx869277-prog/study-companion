# -*- coding: utf-8 -*-
"""麦克风录音（主动开启式，隐私优先）。
默认只在用户显式触发时录音（UI 单击把手 / 全局快捷键 / mic_toggle 命令），
常开模式 config.MIC_ALWAYS_ON=True 才持续分段录（公共场合勿开，会录到旁人）。
wav 落盘 logs/tmp_audio/mic-*.wav 供 whisper_worker 转写（文件名前缀 mic- 标注来源）。"""
import os
import threading
import time
import wave
from datetime import datetime

import pyaudiowpatch as pyaudio

import config
import logger


class MicRecorder(threading.Thread):
    """麦克风录音线程：start_recording/stop_recording/toggle 控制，段落落盘"""

    def __init__(self):
        super().__init__(daemon=True)
        self._recording = threading.Event()
        self._stop_event = threading.Event()
        self.available = True

    def start_recording(self):
        self._recording.set()

    def stop_recording(self):
        self._recording.clear()

    def toggle(self):
        """切换录音状态，返回新状态（True=录音中）"""
        if self._recording.is_set():
            self._recording.clear()
            return False
        self._recording.set()
        return True

    def is_recording(self):
        return self._recording.is_set()

    def stop(self):
        self._stop_event.set()
        self._recording.clear()

    def run(self):
        """Do not enumerate, probe, or open audio hardware before explicit activation."""
        while not self._stop_event.is_set():
            if not self._recording.wait(0.1):
                continue
            if self._stop_event.is_set():
                break
            if not config.MONITORING_ACTIVE:
                self._recording.clear()
                continue
            pa = None
            stream = None
            try:
                pa = pyaudio.PyAudio()
                dev = pa.get_default_input_device_info()
                rate = int(dev["defaultSampleRate"])
                channels = min(int(dev["maxInputChannels"]), 2)
                if channels < 1:
                    raise RuntimeError("No input channels")
                if (not self._recording.is_set() or self._stop_event.is_set()
                        or not config.MONITORING_ACTIVE):
                    continue
                stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                                 input=True, input_device_index=dev["index"],
                                 frames_per_buffer=1024)
                tmp_dir = os.path.join(config.LOG_DIR, "tmp_audio")
                os.makedirs(tmp_dir, exist_ok=True)
                while (self._recording.is_set() and not self._stop_event.is_set()
                       and config.MONITORING_ACTIVE):
                    frames = []
                    t_end = time.time() + config.AUDIO_SEGMENT_SECONDS
                    while (self._recording.is_set() and not self._stop_event.is_set()
                           and config.MONITORING_ACTIVE and time.time() < t_end):
                        avail = stream.get_read_available()
                        if avail:
                            frames.append(stream.read(min(avail, 4096),
                                                      exception_on_overflow=False))
                        else:
                            self._stop_event.wait(0.02)
                    if (not self._recording.is_set() or self._stop_event.is_set()
                            or not config.MONITORING_ACTIVE):
                        break  # Discard an unfinished segment when stopped.
                    data = b"".join(frames)
                    if len(data) >= rate * channels:  # At least half a second.
                        name = "mic-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".wav"
                        path = os.path.join(tmp_dir, name)
                        with wave.open(path + ".part", "wb") as wf:
                            wf.setnchannels(channels)
                            wf.setsampwidth(2)
                            wf.setframerate(rate)
                            wf.writeframes(data)
                        os.replace(path + ".part", path)
            except Exception as error:
                self.available = False
                logger.log("error", where="mic", error=type(error).__name__)
                self._recording.clear()
            finally:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                if pa is not None:
                    pa.terminate()
