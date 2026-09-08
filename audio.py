# -*- coding: utf-8 -*-
"""WASAPI 回录系统声音；转写由独立进程 whisper_worker.py 完成"""
import os
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime


import numpy as np
import pyaudiowpatch as pyaudio

import config
import logger


def _get_loopback_device(pa):
    """找默认扬声器的 loopback 设备"""
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    for d in pa.get_loopback_device_info_generator():
        if default_out["name"] in d["name"]:
            return d
    # 兜底：取第一个 loopback
    for d in pa.get_loopback_device_info_generator():
        return d
    raise RuntimeError("未找到 WASAPI loopback 设备")


def record_segment(seconds, out_wav, stop_event=None, allowed=None):
    """录 seconds 秒系统声音写入 wav 文件。返回是否成功。"""
    if (stop_event is not None and stop_event.is_set()) or (allowed is not None and not allowed()):
        return False
    pa = pyaudio.PyAudio()
    stream = None
    try:
        dev = _get_loopback_device(pa)
        rate = int(dev["defaultSampleRate"])
        channels = dev["maxInputChannels"]
        frames = []
        stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                         input=True, input_device_index=dev["index"],
                         frames_per_buffer=1024)
        # 部分声卡驱动在系统无声时 loopback 不下发数据，read 会永久阻塞；
        # 改为按墙钟轮询 get_read_available，结束时不足部分补静音帧
        t_end = time.time() + seconds
        got = 0
        while time.time() < t_end:
            if ((stop_event is not None and stop_event.is_set())
                    or (allowed is not None and not allowed())):
                return False
            avail = stream.get_read_available()
            if avail > 0:
                data = stream.read(avail, exception_on_overflow=False)
                frames.append(data)
                got += len(data) // (channels * 2)
            else:
                time.sleep(0.02)
        stream.stop_stream()
        need = rate * seconds - got
        if need > 0:
            frames.append(b"\x00" * need * channels * 2)
        stream.close()
        stream = None
        if ((stop_event is not None and stop_event.is_set())
                or (allowed is not None and not allowed())):
            return False
        data = b"".join(frames)
        # 重采样到 16k 单声道不方便做就保持原样，faster-whisper 能处理原始 wav
        with wave.open(out_wav + ".part", "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(data)
        os.replace(out_wav + ".part", out_wav)
        return True
    except Exception as e:
        logger.log("error", where="record_segment", error=str(e))
        return False
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        pa.terminate()


def launch_worker():
    """启动独立转写进程（whisper_worker.py），返回 Popen 对象。

    进程级隔离：避免 ctranslate2 与 onnxruntime 同进程原生层冲突。
    """
    worker_py = os.path.join(config.BASE_DIR, "whisper_worker.py")
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_f = open(os.path.join(config.LOG_DIR, "worker.log"), "a", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-u", worker_py],
        cwd=config.BASE_DIR,
        stdout=log_f, stderr=subprocess.STDOUT,
    )


def append_transcript(lines, wav_path):
    date = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(config.LOG_DIR, f"transcript-{date}.md")
    os.makedirs(config.LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    # 按文件名前缀标注来源，日报好区分"老师说的"和"我说的"
    source = "麦克风" if os.path.basename(wav_path).startswith("mic-") else "系统声音"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n### 片段 {ts}（{source}）\n")
        for line in lines:
            f.write(line + "\n")
    logger.log("transcript_segment", file=wav_path, lines=len(lines), source=source)


class CourseRecorder(threading.Thread):
    """网课状态期间循环录 30 秒分段，wav 落盘到 tmp_audio 供转写进程消费"""

    def __init__(self):
        super().__init__(daemon=True)
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        tmp_dir = os.path.join(config.LOG_DIR, "tmp_audio")
        os.makedirs(tmp_dir, exist_ok=True)
        allowed = lambda: config.MONITORING_ACTIVE and config.COURSE_AUDIO_ENABLED
        while not self._stop_event.is_set() and allowed():
            name = f"seg-{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav"
            path = os.path.join(tmp_dir, name)
            record_segment(config.AUDIO_SEGMENT_SECONDS, path, self._stop_event, allowed)
