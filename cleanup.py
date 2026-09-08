# -*- coding: utf-8 -*-
"""logs/ 磁盘占用自动清理：main.py 启动时调用一次（run() 内每天最多执行一次）。
- 按文件名日期删除超期文件（events-/transcript-/subtitles-/dashboard-）
- 滚动日志超 LOG_MAX_MB 截断保留尾部一半
- tmp_audio 里超过 1 小时的孤儿 wav 删除
报告输出目录不在本清理范围内；日报和备份由用户自行管理。"""
import os
import re
import time
from datetime import datetime, timedelta

import config
import logger

# 带日期的数据文件：events-YYYY-MM-DD.jsonl / transcript-*.md / subtitles-*.txt / dashboard-*.html
_DATED_RE = re.compile(
    r"^(events|transcript|subtitles|dashboard)-(\d{4}-\d{2}-\d{2})\.(jsonl|md|txt|html)$")
# 持续追加的滚动日志
_ROLLING_LOGS = ["main.log", "llama-server.log", "worker.log", "ui.log",
                 "crash-main.log", "crash-ui.log", "launcher.log"]
_ORPHAN_WAV_AGE = 3600         # tmp_audio 孤儿 wav 阈值（秒）
_state_file = os.path.join(config.LOG_DIR, ".last_cleanup")


def run():
    """每天最多执行一次；返回 (删除文件数, 释放字节数)"""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(_state_file) as f:
            if f.read().strip() == today:
                return 0, 0            # 今天已清理过
    except OSError:
        pass

    deleted, freed = 0, 0
    cutoff = (datetime.now() - timedelta(days=config.LOG_RETENTION_DAYS)).date()

    # 1) 超期数据文件（按文件名日期）
    for name in os.listdir(config.LOG_DIR):
        m = _DATED_RE.match(name)
        if not m:
            continue
        try:
            fdate = datetime.strptime(m.group(2), "%Y-%m-%d").date()
        except ValueError:
            continue
        if fdate < cutoff:
            path = os.path.join(config.LOG_DIR, name)
            try:
                size = os.path.getsize(path)
                os.remove(path)
                deleted += 1
                freed += size
            except OSError:
                pass

    # 2) 滚动日志超限截断（保留尾部一半）
    max_bytes = config.LOG_MAX_MB * 1024 * 1024
    for name in _ROLLING_LOGS:
        path = os.path.join(config.LOG_DIR, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > max_bytes:
            try:
                with open(path, "rb") as f:
                    f.seek(size // 2)
                    f.readline()          # 丢弃半行，对齐到行边界
                    tail = f.read()
                with open(path, "wb") as f:
                    f.write(f"=== {today} 截断，保留尾部 ===\n".encode("utf-8"))
                    f.write(tail)
                freed += size - (size // 2)
            except OSError:
                pass

    # 3) tmp_audio 孤儿 wav（worker 挂了没消费的）
    tmp_dir = os.path.join(config.LOG_DIR, "tmp_audio")
    if os.path.isdir(tmp_dir):
        now = time.time()
        for name in os.listdir(tmp_dir):
            if not name.endswith(".wav"):
                continue
            path = os.path.join(tmp_dir, name)
            try:
                if now - os.path.getmtime(path) > _ORPHAN_WAV_AGE:
                    size = os.path.getsize(path)
                    os.remove(path)
                    deleted += 1
                    freed += size
            except OSError:
                pass

    with open(_state_file, "w") as f:
        f.write(today)
    logger.log("cleanup", deleted=deleted, freed_mb=round(freed / 1048576, 2),
               retention_days=config.LOG_RETENTION_DAYS)
    print(f"[cleanup] 删除 {deleted} 个文件，释放 {freed/1048576:.1f}MB", flush=True)
    return deleted, freed
