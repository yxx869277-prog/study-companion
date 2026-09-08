# -*- coding: utf-8 -*-
"""可选在线语音：开启后会把播报文案发送给 edge-tts 使用的在线服务。
文案可能包含从屏幕推导出的内容。默认关闭，且每次启动均需用户重新开启。"""
import os
import queue
import subprocess
import tempfile
import threading
import time

import config
import logger

_q = queue.Queue()
_worker = None
MAX_CHARS = 50                 # 太长截断再念

_PS_PLAY = (
    "Add-Type -AssemblyName presentationCore; "
    "$p = New-Object System.Windows.Media.MediaPlayer; "
    "$p.Open('{path}'); "
    "Start-Sleep -Milliseconds 800; "
    "$p.Play(); "
    "$d = $p.NaturalDuration.TimeSpan.TotalSeconds; "
    "if ($d -le 0) {{ $d = 5 }}; "
    "Start-Sleep -Seconds ($d + 0.5); "
    "$p.Close()"
)


def _synthesize(text, mp3_path):
    """edge-tts 生成 mp3；失败抛异常"""
    if not config.TTS_ENABLED or not config.MONITORING_ACTIVE:
        return
    import asyncio
    import edge_tts
    voice = getattr(config, "TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    rate = getattr(config, "TTS_RATE", "+0%")
    volume = getattr(config, "TTS_VOLUME", "+0%")

    async def _run():
        comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
        with open(mp3_path, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
    asyncio.run(_run())


def _play(mp3_path):
    """用 Windows MediaPlayer 播放（无窗口、不抢焦点），播完返回实际耗时"""
    cmd = ["powershell", "-NoProfile", "-Command", _PS_PLAY.format(path=mp3_path.replace("'", "''"))]
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    t0 = time.time()
    subprocess.run(cmd, timeout=120, capture_output=True, creationflags=flags)
    return time.time() - t0


def _work():
    while True:
        text = _q.get()
        if not config.TTS_ENABLED or not config.MONITORING_ACTIVE:
            continue
        mp3_path = None
        try:
            fd, mp3_path = tempfile.mkstemp(suffix=".mp3", prefix="tts-")
            os.close(fd)
            _synthesize(text, mp3_path)
            _play(mp3_path)
        except Exception as e:
            logger.log("error", where="tts", error=f"{type(e).__name__}: {e}")
        finally:
            if mp3_path:
                try:
                    os.remove(mp3_path)
                except OSError:
                    pass


def _ensure_worker():
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, daemon=True)
        _worker.start()


def speak(text):
    """提交一条文案到 TTS 队列（异步，立即返回）。TTS_ENABLED=False 时忽略"""
    if not config.TTS_ENABLED or not config.MONITORING_ACTIVE:
        return
    text = (text or "").strip()
    if not text:
        return
    _ensure_worker()
    _q.put(text[:MAX_CHARS])


def pending():
    return _q.qsize()
