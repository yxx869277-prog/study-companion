# -*- coding: utf-8 -*-
"""独立转写进程：监视 tmp_audio 目录，转写 wav → 追加 transcript → 删除 wav

单独成进程的原因：faster-whisper(ctranslate2) 与 rapidocr(onnxruntime)
同进程加载会在原生层段错误，进程级隔离后互不干扰。
"""
import os
import sys
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from faster_whisper import WhisperModel

import config
from audio import append_transcript


def main():
    tmp_dir = os.path.join(config.LOG_DIR, "tmp_audio")
    os.makedirs(tmp_dir, exist_ok=True)
    print(f"[whisper-worker] 加载模型 {config.WHISPER_MODEL} ({config.WHISPER_COMPUTE})…", flush=True)
    model = WhisperModel(config.WHISPER_MODEL, device="cpu",
                         compute_type=config.WHISPER_COMPUTE,
                         cpu_threads=2, num_workers=1, local_files_only=True)
    print("[whisper-worker] 就绪，等待音频片段", flush=True)
    while True:
        wavs = sorted(f for f in os.listdir(tmp_dir) if f.endswith(".wav"))
        if not wavs:
            time.sleep(2)
            continue
        path = os.path.join(tmp_dir, wavs[0])
        try:
            # 文件可能还在写入（同一秒内刚建），等它稳定
            size0 = os.path.getsize(path)
            time.sleep(0.5)
            if os.path.getsize(path) != size0:
                continue
            segments, _ = model.transcribe(path, language=config.WHISPER_LANG,
                                           vad_filter=True)
            lines = []
            for seg in segments:
                text = seg.text.strip()
                if text:
                    lines.append(f"[{seg.start:7.1f}-{seg.end:7.1f}] {text}")
            if lines:
                append_transcript(lines, path)
                print(f"[whisper-worker] 转写 {wavs[0]}: {len(lines)} 行", flush=True)
        except Exception as e:
            print(f"[whisper-worker] 转写失败 {wavs[0]}: {e}", flush=True)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
