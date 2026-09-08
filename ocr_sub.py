# -*- coding: utf-8 -*-
"""在用户开启 OCR 且识别为网课时提取整屏文字；可能包含窗口周边文字。"""
import os
from datetime import datetime

import config
import logger

_engine = None
_recent = []   # 最近几条 OCR 结果，用于去重
_MAX_RECENT = 20


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def warmup():
    """启动时预加载 OCR 引擎。

    必须在 notify(windows_toasts/WinRT) 加载之前调用：
    WinRT 先加载会导致 onnxruntime 的 DLL 初始化失败。
    """
    _get_engine()


def extract_subtitles(img):
    """对整屏截图做 OCR（全监控：不局限于字幕区），返回去重后的新文本列表。
    截图先缩放到 OCR_MAX_WIDTH 宽以内控制耗时。"""
    w, h = img.size
    max_w = getattr(config, "OCR_MAX_WIDTH", 1600)
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)))
    try:
        engine = _get_engine()
        result, _ = engine(img)
    except Exception as e:
        logger.log("error", where="ocr", error=str(e))
        return []
    if not result:
        return []
    new_texts = []
    for box, text, score in result:
        text = text.strip()
        if len(text) < 2 or score < 0.5:
            continue
        if text not in _recent:
            new_texts.append(text)
            _recent.append(text)
    while len(_recent) > _MAX_RECENT:
        _recent.pop(0)
    return new_texts


def append_subtitles(texts):
    if not texts:
        return
    date = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(config.LOG_DIR, f"subtitles-{date}.txt")
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for t in texts:
            f.write(t + "\n")
