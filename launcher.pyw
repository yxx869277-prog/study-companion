# -*- coding: utf-8 -*-
"""看门狗启动器（pythonw 无窗口运行）：
- 锁文件防重复实例（logs/launcher.lock 存 PID，活实例在就直接退出）
- 启动 main.py 并 wait；异常退出（非 0）记日志、收孤儿、10 秒后重启；正常退出（0）不重启
"""
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
import config
LOG_DIR = config.LOG_DIR
LOCK_FILE = os.path.join(LOG_DIR, "launcher.lock")
LOG_FILE = os.path.join(LOG_DIR, "launcher.log")
RESTART_DELAY = 10

os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%F %T')}] {msg}\n")


def pid_alive(pid):
    """Windows 下检测 PID 是否存活"""
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def acquire_lock():
    """已有活实例返回 False，否则写入自己 PID 返回 True"""
    try:
        with open(LOCK_FILE) as f:
            old_pid = int(f.read().strip())
        if old_pid != os.getpid() and pid_alive(old_pid):
            return False
    except (OSError, ValueError):
        pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def cleanup_orphans():
    """Only processes whose command line contains this copy's full script path."""
    paths = [os.path.join(BASE_DIR, name) for name in
             ("main.py", "companion_ui.py", "whisper_worker.py")]
    conditions = " -or ".join(
        "$_.CommandLine.Contains('" + path.replace("'", "''") + "')"
        for path in paths)
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and (" +
          conditions + ") } | ForEach-Object { "
          "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   timeout=30, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    if not acquire_lock():
        log(f"已有活实例（锁文件 PID），本实例 {os.getpid()} 退出")
        return
    log(f"launcher 启动，PID={os.getpid()}")
    pythonw = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    try:
        while True:
            proc = subprocess.Popen(
                [pythonw, os.path.join(BASE_DIR, "main.py")], cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NO_WINDOW)
            log(f"main.py 已启动，PID={proc.pid}")
            code = proc.wait()
            log(f"main.py 退出，退出码={code}")
            cleanup_orphans()
            if code == 0:
                log("正常退出，不重启")
                break
            log(f"{RESTART_DELAY} 秒后重启…")
            time.sleep(RESTART_DELAY)
    except BaseException as e:
        log(f"launcher 自身异常: {type(e).__name__}: {e}")
    finally:
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
