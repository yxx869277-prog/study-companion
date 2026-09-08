"""Read package metadata and model file presence; no capture or network calls."""
import importlib.metadata
import json
from pathlib import Path
import platform
import config

PACKAGES = ["mss", "pillow", "numpy", "requests", "pyaudiowpatch", "faster-whisper",
            "rapidocr-onnxruntime", "windows-toasts", "opencv-python", "keyboard"]

def main():
    installed = {}
    for package in PACKAGES:
        try:
            installed[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed[package] = None
    result = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "packages": installed,
        "whisper_model_present": (Path(config.WHISPER_MODEL) / "model.bin").is_file(),
        "llama_files_present": all(Path(p).is_file() for p in
                                  (config.LLAMA_SERVER_EXE, config.LLAMA_MODEL, config.LLAMA_MMPROJ)),
        "ollama_model": "not contacted",
        "screen_camera_microphone": "not opened",
        "ready_for_hardware_run": "requires separate model and device verification",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
