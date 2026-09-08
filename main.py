# -*- coding: utf-8 -*-
"""主循环：截屏 → 识别状态 → 规则互动 → 网课时录音转写 + 字幕 OCR"""
import os

# ctranslate2(faster-whisper) 与 onnxruntime(rapidocr) 各自静态链接了 OpenMP，
# 同进程同时做原生推理会段错误；允许重复 OpenMP 运行时规避
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import json
import threading
import sys
import time
from datetime import datetime

import audio
import capture
import config
import logger
import ocr_sub
import vision

# pythonw 下 sys.stdout 可能是 None；从终端启动时父进程退出后管道也会断。
# 把 print 重定向到"日志文件 + 原 stdout"的双写安全流，任何情况下都不炸主流程。
class _SafeOut:
    def __init__(self):
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self._log = open(os.path.join(config.LOG_DIR, "main.log"), "a",
                         encoding="utf-8", buffering=1)

    def write(self, s):
        try:
            self._log.write(s)
        except Exception:
            pass
        try:
            sys.__stdout__.write(s)
        except Exception:
            pass

    def flush(self):
        for f in (self._log, sys.__stdout__):
            try:
                f.flush()
            except Exception:
                pass


sys.stdout = _SafeOut()
sys.stderr = sys.stdout

# 崩溃留证据：段错误/未捕获异常都必须落盘（pythonw 无控制台）
import faulthandler
import traceback

_crash_f = open(os.path.join(config.LOG_DIR, "crash-main.log"), "a",
                encoding="utf-8", buffering=1)
faulthandler.enable(file=_crash_f)


def _excepthook(exc_type, exc, tb):
    _crash_f.write(f"\n=== {time.strftime('%F %T')} 未捕获异常 ===\n")
    traceback.print_exception(exc_type, exc, tb, file=_crash_f)
    _crash_f.flush()


sys.excepthook = _excepthook

# onnxruntime 必须先于 rules→notify 的 WinRT 加载，否则 OCR 引擎 DLL 初始化失败
ocr_sub.warmup()

import rules


def _launch_ui():
    """拉起桌面形象子进程；挂了不影响主流程，返回 Popen 或 None。
    仅启动此副本的界面；单例锁也位于此副本的数据目录。"""
    import subprocess
    import sys
    try:
        ui_py = os.path.join(config.BASE_DIR, "companion_ui.py")
        log_f = open(os.path.join(config.LOG_DIR, "ui.log"), "ab")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        return subprocess.Popen([sys.executable, "-u", ui_py],
                                cwd=config.BASE_DIR,
                                stdout=log_f, stderr=subprocess.STDOUT,
                                creationflags=flags)
    except Exception as e:
        logger.log("error", where="launch_ui", error=str(e))
        return None


def main():
    # logs/ 磁盘占用清理（每天最多一次，见 cleanup.py）
    try:
        import cleanup
        cleanup.run()
    except Exception as e:
        logger.log("error", where="cleanup", error=str(e))

    cap = capture.ScreenCapture()
    flags = {"paused": True, "quit": False}
    config.MONITORING_ACTIVE = False
    recorder = None
    worker_proc = None
    current_state = None

    engine = rules.RuleEngine()
    ui_proc = _launch_ui()

    # 麦克风（主动开启式）：UI 单击/快捷键/命令文件三路触发
    mic_rec = None
    try:
        import mic
        mic_rec = mic.MicRecorder()
        mic_rec.start()
        if not mic_rec.available:
            mic_rec = None
        elif config.MIC_ALWAYS_ON:
            mic_rec.start_recording()
    except Exception as e:
        logger.log("error", where="mic_init", error=str(e))

    def _ensure_worker():
        nonlocal worker_proc
        if not os.path.isfile(os.path.join(config.WHISPER_MODEL, "model.bin")):
            _bubble("请先按安装说明准备本机语音模型，再开启录音。")
            return False
        if worker_proc is None or worker_proc.poll() is not None:
            worker_proc = audio.launch_worker()
        return True

    def _push_mic_state():
        on = mic_rec is not None and mic_rec.is_recording()
        with open(config.UI_QUEUE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "mic_state", "on": on}) + "\n")

    def _mic_toggle():
        if flags["paused"]:
            _bubble("采集已暂停，请先开启屏幕识别；麦克风仍需单独开启。")
            return
        if mic_rec is None:
            return
        if not mic_rec.is_recording() and not _ensure_worker():
            return
        on = mic_rec.toggle()
        logger.log("mic_toggle", recording=on)
        _push_mic_state()

    def _broadcast_setting(key, value):
        """运行时设置回播给 UI（菜单勾选同步）"""
        try:
            os.makedirs(config.LOG_DIR, exist_ok=True)
            with open(config.UI_QUEUE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "setting", "key": key, "value": value},
                                   ensure_ascii=False) + "\n")
        except Exception as e:
            logger.log("error", where="setting_push", error=str(e))

    def _apply_set(key, value):
        """All capture changes pass through this handler."""
        nonlocal recorder, current_state, engine
        if type(value) is not bool:
            return
        if key in ("TTS_ENABLED", "WEBCAM_ENABLED", "MIC_ALWAYS_ON",
                   "COURSE_AUDIO_ENABLED", "OCR_ENABLED"):
            if flags["paused"] and value:
                _bubble("当前已暂停采集，请先开启屏幕识别。")
                _broadcast_setting(key, False)
                return
            if key in ("MIC_ALWAYS_ON", "COURSE_AUDIO_ENABLED") and value:
                if not _ensure_worker():
                    _broadcast_setting(key, False)
                    return
            setattr(config, key, value)
            if key == "MIC_ALWAYS_ON" and mic_rec is not None:
                mic_rec.start_recording() if value else mic_rec.stop_recording()
                _push_mic_state()
            if key == "COURSE_AUDIO_ENABLED" and not value and recorder is not None:
                recorder.stop()
                recorder = None
        elif key == "PAUSED":
            if not value and config.VISION_BACKEND == "llama":
                import llama_server
                if not llama_server.ensure_running():
                    _bubble("本机视觉模型尚未就绪，采集保持暂停。")
                    _broadcast_setting("PAUSED", True)
                    return
            flags["paused"] = value
            config.MONITORING_ACTIVE = not value
            if value:
                if recorder is not None:
                    recorder.stop()
                    recorder = None
                if mic_rec is not None:
                    mic_rec.stop_recording()
                    _push_mic_state()
                for setting in ("MIC_ALWAYS_ON", "WEBCAM_ENABLED",
                                "COURSE_AUDIO_ENABLED", "OCR_ENABLED", "TTS_ENABLED"):
                    setattr(config, setting, False)
                    _broadcast_setting(setting, False)
                current_state = None
                engine = rules.RuleEngine()
                cap._last_thumb = None
        else:
            return
        logger.log("setting", key=key, value=value)
        _broadcast_setting(key, value)

    def _all_settings():
        return {**{key: getattr(config, key) for key in
                   ("TTS_ENABLED", "WEBCAM_ENABLED", "MIC_ALWAYS_ON",
                    "COURSE_AUDIO_ENABLED", "OCR_ENABLED")},
                "PAUSED": flags["paused"]}

    # 日报/仪表盘动作：Popen detach 不阻塞，监视线程完成后发结果气泡；日报防重复
    _action_state = {"report_proc": None}

    def _bubble(text):
        try:
            import notify
            notify.notify("学习搭子", text, kind="bubble")
        except Exception:
            pass

    def _run_action(c):
        import subprocess
        flags_nw = (subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        if c == "report":
            proc = _action_state["report_proc"]
            if proc is not None and proc.poll() is None:
                _bubble("日报正在生成中，请稍候…")
                return
            try:
                proc = subprocess.Popen([sys.executable, "summarize.py"],
                                        cwd=config.BASE_DIR, creationflags=flags_nw)
            except Exception as e:
                logger.log("error", where="ui_report", error=str(e))
                _bubble("日报启动失败，看 logs/main.log")
                return
            _action_state["report_proc"] = proc
            _bubble("日报生成中，约 3-4 分钟…")
            logger.log("ui_action", action="report")

            def _watch():
                code = proc.wait()
                today = datetime.now().strftime("%Y-%m-%d")
                out = os.path.join(config.REPORT_DIR, f"{today}.md")
                ok = (code == 0 and os.path.exists(out)
                      and time.time() - os.path.getmtime(out) < 600)
                _bubble("日报已生成，保存到你配置的报告目录" if ok
                        else f"日报生成失败（退出码 {code}）")
                logger.log("ui_action", action="report_done", exit_code=code,
                           success=ok)
            threading.Thread(target=_watch, daemon=True).start()
        else:  # dashboard：生成很快，立即反馈
            try:
                proc = subprocess.Popen([sys.executable, "dashboard.py"],
                                        cwd=config.BASE_DIR, creationflags=flags_nw)
                _bubble("仪表盘已生成并打开 📊")
                logger.log("ui_action", action="dashboard")
            except Exception as e:
                logger.log("error", where="ui_dashboard", error=str(e))
                _bubble("仪表盘生成失败，看 logs/main.log")

    def _ui_cmd_loop():
        """轮询 UI 命令文件：mic_toggle / set / query_settings / report / dashboard / quit
        起始偏移设在文件末尾——历史命令不重演（否则旧 quit 会秒杀新实例）"""
        offset = 0
        try:
            offset = os.path.getsize(config.UI_CMD_QUEUE)
        except OSError:
            pass
        while True:
            try:
                with open(config.UI_CMD_QUEUE, encoding="utf-8") as f:
                    f.seek(offset)
                    for line in f:
                        try:
                            cmd = json.loads(line.strip())
                        except (json.JSONDecodeError, ValueError):
                            continue
                        c = cmd.get("cmd")
                        if c == "mic_toggle":
                            _mic_toggle()
                        elif c == "set":
                            _apply_set(cmd.get("key"), cmd.get("value"))
                        elif c == "query_settings":
                            for k, v in _all_settings().items():
                                _broadcast_setting(k, v)
                        elif c in ("report", "dashboard"):
                            _run_action(c)
                        elif c == "quit":
                            logger.log("ui_action", action="quit")
                            _apply_set("PAUSED", True)
                            flags["quit"] = True
                    offset = f.tell()
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.log("error", where="ui_cmd", error=str(e))
            time.sleep(1)

    threading.Thread(target=_ui_cmd_loop, daemon=True).start()
    if mic_rec is not None:
        # 全局快捷键（失败降级为仅形象点击）
        try:
            import keyboard
            keyboard.add_hotkey(config.MIC_HOTKEY, _mic_toggle)
            print(f"[mic] 快捷键 {config.MIC_HOTKEY} 已注册", flush=True)
        except Exception as e:
            logger.log("error", where="mic_hotkey", error=f"快捷键注册失败（仅形象点击可用）: {e}")
            print("[mic] 快捷键注册失败，仅形象点击可用", flush=True)

    # The thread itself does not open the camera until both gates are enabled.
    webcam_mon = None
    try:
        import webcam
        webcam_mon = webcam.WebcamMonitor(
            lambda behavior: engine.update_webcam(behavior),
            should_sample=lambda: not flags["paused"] and current_state not in (None, "空闲"))
        webcam_mon.start()
    except Exception as error:
        logger.log("error", where="webcam_init", error=type(error).__name__)

    last_change = time.time()
    vision_fails = 0

    print("学习搭子已启动，采集默认暂停；右键桌面形象选择开始屏幕识别。", flush=True)
    try:
        while True:
            if flags["quit"]:
                print("收到退出命令，正在退出…", flush=True)
                break
            if flags["paused"]:
                time.sleep(2)      # 暂停监控：不截屏不识别，只保活
                continue
            img = cap.grab()
            if flags["paused"]:
                img = None
                continue
            changed, diff = cap.changed(img)
            now = time.time()
            if changed:
                last_change = now

            # 画面长时间未动 → 空闲，跳过识别
            if now - last_change >= config.IDLE_SECONDS:
                state_info = {"state": "空闲", "detail": "画面长时间无变化", "course_hint": None}
            elif not changed:
                time.sleep(2)
                continue
            else:
                result = vision.classify(img)
                if flags["paused"]:
                    img = None
                    continue
                if result is None:
                    vision_fails += 1
                    if vision_fails >= 3:
                        logger.log("error", where="vision", error="连续识别失败")
                        if vision.current_backend() == "llama":
                            import llama_server
                            llama_server.ensure_running()
                        vision_fails = 0
                    time.sleep(config.CAPTURE_INTERVAL)
                    continue
                vision_fails = 0
                state_info = result
                print(f"[{time.strftime('%H:%M:%S')}] 识别({vision.current_backend()}): {result['state']} | {result.get('detail','')[:40]}", flush=True)
                # OCR is a separate opt-in and limited to recognized course frames.
                if config.OCR_ENABLED and state_info["state"] == "网课":
                    texts = ocr_sub.extract_subtitles(img)
                    if not flags["paused"] and config.OCR_ENABLED:
                        ocr_sub.append_subtitles(texts)
            img = None
            if flags["paused"]:
                continue

            state = state_info["state"]
            # 每次成功判定都记 observation，日报据此还原全天时间线
            logger.log("observation", state=state,
                       detail=state_info.get("detail", ""),
                       course_hint=state_info.get("course_hint"))
            if state != current_state:
                logger.log("state_change", prev=current_state, state=state,
                           detail=state_info.get("detail", ""),
                           course_hint=state_info.get("course_hint"))
                print(f"[{time.strftime('%H:%M:%S')}] {current_state} -> {state}: {state_info.get('detail','')}", flush=True)
                current_state = state

            # Re-evaluate every tick, including after a menu change in the same state.
            want_audio = state == "网课" and config.COURSE_AUDIO_ENABLED and not flags["paused"]
            if want_audio and recorder is None and _ensure_worker():
                recorder = audio.CourseRecorder()
                recorder.start()
            elif not want_audio and recorder is not None:
                recorder.stop()
                recorder = None

            engine.update(state, state_info.get("course_hint"),
                          state_info.get("detail", ""))
            time.sleep(config.CAPTURE_INTERVAL)
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        config.MONITORING_ACTIVE = False
        flags["paused"] = True
        if recorder is not None:
            recorder.stop()
        if worker_proc is not None and worker_proc.poll() is None:
            worker_proc.terminate()
        if ui_proc is not None and ui_proc.poll() is None:
            ui_proc.terminate()
        if webcam_mon is not None:
            webcam_mon.stop()
        if mic_rec is not None:
            mic_rec.stop()
            mic_rec.join(timeout=2)
        # llama-server 若是本进程拉起的，收掉不留孤儿
        try:
            import llama_server
            llama_server.stop_if_owned()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        # 双保险：excepthook 只管线程内异常，这里兜主流程
        _crash_f.write(f"\n=== {time.strftime('%F %T')} 主流程异常退出 ===\n")
        traceback.print_exc(file=_crash_f)
        _crash_f.flush()
        sys.exit(1)
