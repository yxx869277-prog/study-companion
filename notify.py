# -*- coding: utf-8 -*-
"""互动消息出口：优先推桌面 UI（气泡/弹幕），UI 不在线时退化 Windows 通知"""
import json
import os
import time

import config

_toaster = None
ALIVE_FILE = os.path.join(config.LOG_DIR, "ui_alive.txt")


def ui_alive():
    """UI 进程心跳是否新鲜（5 秒内）"""
    try:
        return time.time() - os.path.getmtime(ALIVE_FILE) < 5
    except OSError:
        return False


def push_ui(text, kind="bubble"):
    """往 UI 队列追加一条消息"""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(config.UI_QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": kind, "text": text}, ensure_ascii=False) + "\n")


def system_toast(title, message):
    """Windows 通知；失败静默（不阻塞主流程）"""
    global _toaster
    try:
        if _toaster is None:
            from windows_toasts import Toast, WindowsToaster
            _toaster = (WindowsToaster("AI 学习搭子"), Toast)
        toaster, toast_cls = _toaster
        toaster.show_toast(toast_cls([title, message]))
    except Exception as e:
        import logger
        logger.log("error", where="notify", error=str(e))


def notify(title, message, kind="bubble", toast=False):
    """发互动消息。
    kind: "bubble" / "danmaku"（UI 在线时生效）
    toast: True 时额外发系统通知（用于休息提醒等重要消息）
    UI 不在线时整体退化为系统通知。
    """
    if ui_alive():
        try:
            push_ui(message, kind)
        except Exception as e:
            import logger
            logger.log("error", where="notify_push_ui", error=str(e))
            system_toast(title, message)
    else:
        system_toast(title, message)
    if toast:
        system_toast(title, message)
