# -*- coding: utf-8 -*-
"""截屏 + 简单变化检测"""
import mss
import numpy as np
from PIL import Image

import config


class ScreenCapture:
    def __init__(self):
        self._sct = mss.mss()
        self._last_thumb = None

    def grab(self):
        """截取主显示器，返回 PIL Image"""
        mon = self._sct.monitors[1]
        shot = self._sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def _thumb(self, img):
        small = img.resize(config.THUMB_SIZE, Image.BILINEAR)
        return np.asarray(small, dtype=np.float32)

    def changed(self, img):
        """画面相比上次是否变化；返回 (是否变化, 平均像素差)"""
        t = self._thumb(img)
        if self._last_thumb is None:
            self._last_thumb = t
            return True, float("inf")
        diff = float(np.abs(t - self._last_thumb).mean())
        self._last_thumb = t
        return diff >= config.CHANGE_THRESHOLD, diff
