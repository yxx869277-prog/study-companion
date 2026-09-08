# -*- coding: utf-8 -*-
"""llama.cpp llama-server 进程管理：没起就自动拉起，等它就绪；
默认端口被占时自动换空闲端口（实际端口写回 config.LLAMA_URL）"""
import json
import os
import socket
import subprocess
import time

import local_api

import config

_server_proc = None   # 本进程拉起的 llama-server（用于退出时收尸）


def stop_if_owned():
    """如果 llama-server 是本进程拉起的，终止它"""
    global _server_proc
    if _server_proc is not None and _server_proc.poll() is None:
        try:
            _server_proc.terminate()
        except Exception:
            pass
    _server_proc = None


def _health(url):
    """返回 /health 响应 dict 或 None"""
    try:
        r = local_api.request("GET", url + "/health", timeout=3)
        if r.status_code == 200:
            return r.json() if r.content else {}
    except Exception:
        pass
    return None


def is_ready():
    return _health(config.LLAMA_URL) is not None


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_port():
    """让系统分配一个空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ensure_running():
    """确保 llama-server 在跑；成功返回 True，并把实际地址写进 config.LLAMA_URL"""
    if is_ready():
        return True

    # 默认端口被别的东西占了（健康检查不过但端口不通）→ 换空闲端口
    port = config.LLAMA_PORT
    if not _port_free(port):
        port = _free_port()
        print(f"[llama] 默认端口 {config.LLAMA_PORT} 被占用，改用 {port}", flush=True)
    base_url = f"http://127.0.0.1:{port}"

    cmd = [
        config.LLAMA_SERVER_EXE,
        "--model", config.LLAMA_MODEL,
        "--mmproj", config.LLAMA_MMPROJ,
        "-ngl", str(config.LLAMA_NGL),
        "-c", str(config.LLAMA_CTX),
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_f = open(os.path.join(config.LOG_DIR, "llama-server.log"), "ab")
    global _server_proc
    _server_proc = subprocess.Popen(cmd, cwd=config.BASE_DIR,
                                    stdout=log_f, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
    print(f"[llama] llama-server 启动中（端口 {port}，日志 logs/llama-server.log）…", flush=True)
    deadline = time.time() + config.LLAMA_START_TIMEOUT
    while time.time() < deadline:
        if _health(base_url) is not None:
            config.LLAMA_URL = base_url
            print(f"[llama] llama-server 就绪: {base_url}", flush=True)
            return True
        time.sleep(2)
    print("[llama] llama-server 启动超时", flush=True)
    return False
