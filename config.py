# -*- coding: utf-8 -*-
"""Single-computer settings. Optional personal overrides: config.local.json."""
import json
import os
from pathlib import Path

BASE_DIR = str(Path(__file__).resolve().parent)
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")
REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")
CAPTURE_INTERVAL = 20
CHANGE_THRESHOLD = 2.0
THUMB_SIZE = (64, 36)
STATES = ["网课", "学习平台", "AI协作", "娱乐视频", "写代码", "读文档", "社交聊天", "其他", "空闲"]
IDLE_SECONDS = 300

VISION_BACKEND = "ollama"  # "ollama" or "llama", both on this computer.
VISION_TIMEOUT = 120
OLLAMA_PORT = 11434
# Conservative request settings verified on Windows; no global Ollama changes.
OLLAMA_CPU_ONLY = True
OLLAMA_CTX = 4096
VISION_MODEL = "qwen3-vl:4b-instruct"
SUMMARY_MODEL = VISION_MODEL
GENMSG_MODEL = VISION_MODEL
LLAMA_PORT = 8080
LLAMA_SERVER_EXE = os.path.join(BASE_DIR, "vendor", "llama-vulkan", "llama-server.exe")
LLAMA_MODEL = os.path.join(BASE_DIR, "models", "Qwen3-VL-4B-Instruct-Q4_K_M.gguf")
LLAMA_MMPROJ = os.path.join(BASE_DIR, "models", "mmproj-Qwen3-VL-4B-Instruct-F16.gguf")
LLAMA_NGL = 99
LLAMA_CTX = 4096
LLAMA_START_TIMEOUT = 180

UI_AVATAR = "🐱"
UI_AVATAR_BG = "#F5F5F0"
UI_AVATAR_BORDER = "#8a8a80"
DANMAKU_LANES = 4
DANMAKU_SPEED = 0
DANMAKU_CROSS_SECONDS = 8
UI_QUEUE = os.path.join(LOG_DIR, "ui_queue.jsonl")
UI_CMD_QUEUE = os.path.join(LOG_DIR, "ui_cmd.jsonl")

WHISPER_MODEL = os.path.join(BASE_DIR, "models", "whisper-small")
WHISPER_COMPUTE = "int8"
WHISPER_LANG = "zh"
AUDIO_SEGMENT_SECONDS = 30
AUDIO_RATE = 16000
AUDIO_CHANNELS = 2
OCR_MAX_WIDTH = 1600
LOG_RETENTION_DAYS = 14
LOG_MAX_MB = 20
INTERACT_COOLDOWN = 300
COURSE_CHEER_MINUTES = 30
STUDY_BREAK_MINUTES = 50
FUN_WARN_MINUTES = 10
FUN_REPEAT_MINUTES = 15
WEBCAM_INTERVAL = 120
MIC_HOTKEY = "ctrl+shift+v"
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_VOLUME = "+0%"
TTS_RATE = "+0%"

# These choices apply only to the current run and always start disabled.
# Personal config cannot silently enable capture or online speech.
START_PAUSED = True
MONITORING_ACTIVE = False
WEBCAM_ENABLED = False
MIC_ALWAYS_ON = False
COURSE_AUDIO_ENABLED = False
OCR_ENABLED = False
TTS_ENABLED = False

_OVERRIDES = {
    "VISION_BACKEND": str, "OLLAMA_PORT": int, "LLAMA_PORT": int,
    "OLLAMA_CPU_ONLY": bool, "OLLAMA_CTX": int,
    "VISION_MODEL": str, "SUMMARY_MODEL": str, "GENMSG_MODEL": str,
    "LLAMA_SERVER_EXE": str, "LLAMA_MODEL": str, "LLAMA_MMPROJ": str,
    "WHISPER_MODEL": str, "REPORT_DIR": str,
    "CAPTURE_INTERVAL": int, "INTERACT_COOLDOWN": int,
}
_personal = Path(BASE_DIR) / "config.local.json"
if _personal.exists():
    _values = json.loads(_personal.read_text(encoding="utf-8-sig"))
    if not isinstance(_values, dict):
        raise ValueError("config.local.json must contain a JSON object")
    for _key, _value in _values.items():
        if _key not in _OVERRIDES or type(_value) is not _OVERRIDES[_key]:
            raise ValueError(f"Unsupported setting or value type: {_key}")
        globals()[_key] = _value

if VISION_BACKEND not in ("ollama", "llama"):
    raise ValueError("VISION_BACKEND must be ollama or llama")
for _port in (OLLAMA_PORT, LLAMA_PORT):
    if not 1 <= _port <= 65535:
        raise ValueError("Local API port must be between 1 and 65535")
if CAPTURE_INTERVAL < 1 or INTERACT_COOLDOWN < 1:
    raise ValueError("Intervals must be positive")
if OLLAMA_CTX < 1024:
    raise ValueError("OLLAMA_CTX must be at least 1024 tokens")
for _setting in ("LLAMA_SERVER_EXE", "LLAMA_MODEL", "LLAMA_MMPROJ",
                 "WHISPER_MODEL", "REPORT_DIR"):
    _path = Path(globals()[_setting]).expanduser()
    globals()[_setting] = str(_path if _path.is_absolute() else Path(BASE_DIR) / _path)

# Hostnames and remote addresses are intentionally not configurable.
OLLAMA_BASE = f"http://127.0.0.1:{OLLAMA_PORT}"
OLLAMA_URL = OLLAMA_BASE + "/api/chat"
LLAMA_URL = f"http://127.0.0.1:{LLAMA_PORT}"
