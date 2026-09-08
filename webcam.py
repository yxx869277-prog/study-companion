# -*- coding: utf-8 -*-
"""摄像头在位/行为监测（隐私优先）。
硬性隐私约束：
- 摄像头帧只在内存中处理，禁止落盘（不存 jpg、不进 logs）
- 帧送视觉模型判断后立即释放引用
- 日志只记结论性事件（webcam: behavior + note + ts）
"""
import threading
import time

import config
import logger
import vision


class WebcamMonitor(threading.Thread):
    """每 config.WEBCAM_INTERVAL 秒抓一帧 → VLM 判断 → 回调 on_behavior(behavior)。
    无摄像头/采集失败：记一次日志后安静退出，不刷错误。"""

    def __init__(self, on_behavior, should_sample=None):
        super().__init__(daemon=True)
        self._cb = on_behavior
        # 可选回调：返回 False 时跳过采样（如锁屏/空闲时不浪费推理、不打扰摄像头）
        self._should_sample = should_sample
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        import cv2
        print(f"[webcam] 监测已启动，每 {config.WEBCAM_INTERVAL}s 一帧", flush=True)
        fail_count = 0
        while not self._stop_event.is_set():
            # 运行时开关（右键菜单可即时关/开）
            if not getattr(config, "WEBCAM_ENABLED", False):
                self._wait(5)
                continue
            # 屏幕空闲/锁屏时不采样（熄屏=没人在看，省算力也省摄像头）
            if self._should_sample is not None and not self._should_sample():
                self._wait(10)
                continue
            # 每次采样即开即关：避免长期占用摄像头影响其他程序
            img = self._grab_once(cv2)
            if img is None:
                fail_count += 1
                if fail_count == 3:
                    logger.log("error", where="webcam", error="连续采集失败，停用")
                    break
                self._wait(5)
                continue
            fail_count = 0
            if (self._stop_event.is_set() or not config.WEBCAM_ENABLED
                    or (self._should_sample is not None and not self._should_sample())):
                img = None
                continue
            result = vision.classify_frame(img)
            img = None            # 判断完立即释放，不留存
            if result:
                logger.log("webcam", behavior=result["behavior"],
                           note=result.get("note", ""))
                try:
                    self._cb(result["behavior"])
                except Exception as e:
                    logger.log("error", where="webcam_cb", error=str(e))
            self._wait(config.WEBCAM_INTERVAL)

    def _grab_once(self, cv2):
        """开摄像头抓一帧立即释放，返回 PIL Image 或 None"""
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        try:
            if not cap.isOpened():
                logger.log("error", where="webcam", error="无摄像头或打开失败")
                return None
            frame = None
            # 连读几帧让自动曝光稳定，取最后一帧
            for _ in range(5):
                ok, frame = cap.read()
                if not ok:
                    return None
            from PIL import Image
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            return img
        except Exception as e:
            logger.log("error", where="webcam", error=str(e))
            return None
        finally:
            frame = None          # 原始帧立即释放
            cap.release()

    def _wait(self, seconds):
        # 分段 sleep 保证 stop 能及时响应
        for _ in range(int(seconds)):
            if self._stop_event.is_set():
                return
            time.sleep(1)
