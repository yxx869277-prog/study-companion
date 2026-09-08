# -*- coding: utf-8 -*-
"""JSONL 事件日志"""
import json
import os
import threading
from datetime import datetime

import config

_lock = threading.Lock()


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def log_path(date=None):
    date = date or _today()
    os.makedirs(config.LOG_DIR, exist_ok=True)
    return os.path.join(config.LOG_DIR, f"events-{date}.jsonl")


def log(event_type, **fields):
    """写一条事件，线程安全"""
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "type": event_type}
    rec.update(fields)
    with _lock:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
