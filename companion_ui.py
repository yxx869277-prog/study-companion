# -*- coding: utf-8 -*-
"""桌面搭子形象 + 气泡 + 弹幕（tkinter，独立进程）

消息通道：轮询 logs/ui_queue.jsonl 增量消费，每行 {"type": "bubble"|"danmaku", "text": ...}
心跳：每轮 polls 刷新 logs/ui_alive.txt，供主进程判断 UI 是否在线。
"""
import json
import os
import time
import sys
from tkinter import messagebox
import tkinter as tk
import tkinter.font as tkfont

import config


def _set_dpi_aware():
    """声明 DPI 感知。不感知时 OS 会对窗口做位图拉伸，
    -transparentcolor 的颜色键被插值破坏 → 透明区域显示为黑色底块。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_set_dpi_aware()

ALIVE_FILE = os.path.join(config.LOG_DIR, "ui_alive.txt")
TRANSPARENT = "#010101"          # 透明色（近黑，避免与文字撞色）
DANMAKU_LANES = 3
DANMAKU_COLORS = ["#ff6680", "#66ccff", "#ffcc66", "#99ff99"]   # 弹幕颜色轮换
FRAME_MS = 25                    # 帧间隔（40fps，顺滑且 CPU 开销可忽略）


def _make_top(root, transparent=True):
    """无边框置顶窗口"""
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    if transparent:
        win.attributes("-transparentcolor", TRANSPARENT)
        win.configure(bg=TRANSPARENT)
    return win


def _click_through(win):
    """让窗口点击穿透（WS_EX_LAYERED | WS_EX_TRANSPARENT）
    注意：Toplevel 的 winfo_id 是内部子窗口，真正的顶层窗口是其父句柄，
    样式必须打在父句柄上（打在子窗口上会导致内容不渲染）"""
    try:
        import ctypes
        win.update_idletasks()
        hwnd = win.winfo_id()
        parent = ctypes.windll.user32.GetParent(hwnd)
        if parent:
            hwnd = parent
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20)
    except Exception as e:
        print(f"[ui] 点击穿透设置失败: {e}", flush=True)


class CompanionUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        # ---- 搭子形象窗口（右下角）----
        self.avatar = _make_top(self.root)
        # 胶囊底衬：浅色不透明底板+边框，深色壁纸下也清晰；
        # 窗口 transparentcolor 只作用于底板之外，保持周围透明
        capsule = tk.Frame(self.avatar,
                           bg=getattr(config, "UI_AVATAR_BG", "#F5F5F0"),
                           highlightthickness=2,
                           highlightbackground=getattr(config, "UI_AVATAR_BORDER",
                                                       "#8a8a80"))
        capsule.pack()
        self.avatar_label = tk.Label(capsule, text=config.UI_AVATAR,
                                     font=("Segoe UI Emoji", 42),
                                     bg=getattr(config, "UI_AVATAR_BG", "#F5F5F0"))
        self.avatar_label.pack()
        # 不透明小把手：透明色窗口只有非透明像素能点到，
        # 纯 emoji 字形太细不好抓，给个底座方便拖动
        self.handle = tk.Label(capsule, text="学习搭子", bg="#3a3a4a", fg="white",
                               font=("Microsoft YaHei UI", 8), padx=8, pady=1)
        self.handle.pack(fill="x")
        self.avatar.update_idletasks()
        w, h = self.avatar.winfo_width(), self.avatar.winfo_height()
        self.avatar.geometry(f"+{self.screen_w - w - 40}+{self.screen_h - h - 80}")
        # 拖动/单击/右键绑定在胶囊容器及两个子件上（点到哪都生效）
        for widget in (capsule, self.avatar_label, self.handle):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._click_or_drag_end)
            widget.bind("<Button-3>", self._popup_menu)

        # ---- Explicit controls; all collection starts disabled. ----
        self._var_tts = tk.BooleanVar(value=False)
        self._var_webcam = tk.BooleanVar(value=False)
        self._var_mic_on = tk.BooleanVar(value=False)
        self._var_course_audio = tk.BooleanVar(value=False)
        self._var_ocr = tk.BooleanVar(value=False)
        self._paused = True
        self._mic_recording = False
        self.menu = tk.Menu(self.root, tearoff=0, font=("Microsoft YaHei UI", 10))
        self.menu.add_command(label="开始屏幕识别（读取主屏幕）", command=self._toggle_pause)
        self._pause_idx = 0
        self.menu.add_separator()
        for key, label, variable in (
            ("COURSE_AUDIO_ENABLED", "网课声音转写（录制系统声音）", self._var_course_audio),
            ("OCR_ENABLED", "网课文字提取（保存整屏文字）", self._var_ocr),
            ("WEBCAM_ENABLED", "摄像头监测", self._var_webcam),
            ("MIC_ALWAYS_ON", "麦克风持续录音", self._var_mic_on),
            ("TTS_ENABLED", "在线语音播报（发送文案）", self._var_tts),
        ):
            self.menu.add_checkbutton(
                label=label, variable=variable,
                command=lambda k=key, v=variable: self._confirm_setting(k, v))
        self.menu.add_separator()
        self.menu.add_command(label="开始/停止麦克风录音", command=self._send_mic_toggle)
        self.menu.add_command(label="生成今日本机日报", command=lambda: self._send_cmd("report"))
        self.menu.add_command(label="打开今日仪表盘", command=lambda: self._send_cmd("dashboard"))
        self.menu.add_separator()
        self.menu.add_command(label="退出学习搭子", command=lambda: self._send_cmd("quit"))
        self.handle.config(text="已暂停 · 右键开始")

        # ---- 弹幕窗口（顶部横条，点击穿透）----
        # 用字体真实行高（metrics）计算车道和窗口高度，杜绝拍脑袋像素切字：
        # canvas anchor="w" 的 y 是文字垂直中心，车道中心必须 ≥ 行高/2 + 上边距
        n_lanes = getattr(config, "DANMAKU_LANES", DANMAKU_LANES)
        self.danmaku_font = tkfont.Font(family="Microsoft YaHei UI",
                                        size=14, weight="bold")
        ls = self.danmaku_font.metrics("linespace")   # 实际行高（DPI 缩放后的真实像素）
        self._lane_h = ls + 12                        # 车道高 = 行高 + 余量
        self._lane_top = 6                            # 顶部边距
        win_h = self._lane_top + n_lanes * self._lane_h + 6
        self.danmaku_win = _make_top(self.root)
        self.danmaku_win.geometry(f"{self.screen_w}x{win_h}+0+0")
        self.danmaku_canvas = tk.Canvas(self.danmaku_win, bg=TRANSPARENT,
                                        highlightthickness=0)
        self.danmaku_canvas.pack(fill="both", expand=True)
        _click_through(self.danmaku_win)
        self._danmakus = []        # [(canvas_item_id, lane_idx)]
        self._lanes = [None] * n_lanes

        # Never replay previous interactions or permission acknowledgements.
        self._queue_offset = os.path.getsize(config.UI_QUEUE) if os.path.exists(config.UI_QUEUE) else 0
        self._bubble_win = None

    # ---- 拖动 / 单击 ----
    def _drag_start(self, event):
        # 记录按下点相对窗口左上角的偏移
        self._drag_x = self.avatar.winfo_pointerx() - self.avatar.winfo_x()
        self._drag_y = self.avatar.winfo_pointery() - self.avatar.winfo_y()
        self._dragged = False
        self._press_t = time.time()

    def _drag_move(self, event):
        self._dragged = True
        x = self.avatar.winfo_pointerx() - self._drag_x
        y = self.avatar.winfo_pointery() - self._drag_y
        self.avatar.geometry(f"+{x}+{y}")

    def _click_or_drag_end(self, event):
        """松手时没拖过且按下时间短 → 视为单击 → 切换麦克风录音"""
        if not getattr(self, "_dragged", True) and \
                time.time() - getattr(self, "_press_t", 0) < 0.5:
            self._send_mic_toggle()

    def _send_mic_toggle(self):
        if self._paused:
            messagebox.showinfo("采集已暂停", "先右键开启屏幕识别，再单独开启需要的录音功能。")
            return
        if not self._mic_recording and not messagebox.askyesno(
                "开启麦克风", "将录制周围声音，并在本机生成文字。再次点击可停止。是否开启？"):
            return
        self._send_cmd("mic_toggle")

    def _confirm_setting(self, key, variable):
        if not variable.get():
            self._send_set(key, False)
            return
        if self._paused:
            variable.set(False)
            messagebox.showinfo("采集已暂停", "请先开启屏幕识别，再选择需要的功能。")
            return
        explanations = {
            "COURSE_AUDIO_ENABLED": "识别为网课时录制电脑播放的声音，可能包含通知或通话。音频暂存本机并转写。",
            "OCR_ENABLED": "识别为网课时提取整屏文字，可能包含课件周边的其他窗口文字。结果保存在本机。",
            "WEBCAM_ENABLED": "定期读取摄像头画面交给本机模型判断；不保存原图，保存行为判断。",
            "MIC_ALWAYS_ON": "持续录制麦克风声音，可能包含周围人的声音。暂停采集或关闭此项会停止。",
            "TTS_ENABLED": "播报文案将发送给在线语音服务，文案可能包含屏幕推导的内容。是否允许本次运行使用？",
        }
        if messagebox.askyesno("启用此功能", explanations[key]):
            self._send_set(key, True)
        else:
            variable.set(False)

    def _send_cmd(self, cmd, **kw):
        try:
            rec = {"cmd": cmd}
            rec.update(kw)
            with open(config.UI_CMD_QUEUE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception as e:
            print(f"[ui] 发送命令失败: {e}", flush=True)

    def _send_set(self, key, value):
        self._send_cmd("set", key=key, value=bool(value))

    def _toggle_pause(self):
        if self._paused and not messagebox.askyesno(
                "开始屏幕识别",
                "将读取主显示器画面，交给本机模型识别活动；活动描述和互动记录保存在本机。"
                "请先关闭不希望被处理的窗口。摄像头、声音和文字提取仍需分别开启。"):
            return
        self._send_set("PAUSED", not self._paused)

    def _popup_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _apply_setting(self, key, value):
        """main 回播的运行时设置 → 同步菜单勾选状态"""
        if key == "TTS_ENABLED":
            self._var_tts.set(bool(value))
        elif key == "WEBCAM_ENABLED":
            self._var_webcam.set(bool(value))
        elif key == "MIC_ALWAYS_ON":
            self._var_mic_on.set(bool(value))
        elif key == "COURSE_AUDIO_ENABLED":
            self._var_course_audio.set(bool(value))
        elif key == "OCR_ENABLED":
            self._var_ocr.set(bool(value))
        elif key == "PAUSED":
            self._paused = bool(value)
            self._set_mic_state(self._mic_recording)
            self.menu.entryconfig(self._pause_idx,
                                  label="开始屏幕识别（读取主屏幕）" if self._paused else "暂停全部采集")

    def _set_mic_state(self, on):
        """录音状态显示：把手变红 ● 录音中 / 恢复"""
        self._mic_recording = on
        if on:
            self.handle.config(text="● 录音中", bg="#c0392b")
        else:
            self.handle.config(text="已暂停 · 右键开始" if self._paused else "屏幕识别中", bg="#3a3a4a")

    # ---- 气泡 ----
    def show_bubble(self, text, seconds=5):
        if self._bubble_win is not None:
            try:
                self._bubble_win.destroy()
            except tk.TclError:
                pass
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        label = tk.Label(win, text=text, font=("Microsoft YaHei UI", 11),
                         bg="#fffbe6", fg="#333", padx=12, pady=8,
                         wraplength=320, justify="left",
                         relief="solid", bd=1)
        label.pack()
        win.update_idletasks()
        # 显示在形象左侧（不够宽就放上边），四边都做屏幕边界钳制
        ax, ay = self.avatar.winfo_x(), self.avatar.winfo_y()
        bw, bh = win.winfo_width(), win.winfo_height()
        x = min(max(10, ax - bw - 10), self.screen_w - bw - 10)
        y = min(max(10, ay - bh // 2), self.screen_h - bh - 10)
        win.geometry(f"+{x}+{y}")
        self._bubble_win = win
        self._fade_out(win, seconds * 1000)

    def _fade_out(self, win, delay):
        def step(alpha=1.0):
            try:
                if alpha <= 0:
                    win.destroy()
                    return
                win.attributes("-alpha", alpha)
                win.after(80, step, alpha - 0.1)
            except tk.TclError:
                pass
        win.after(delay, step)

    # ---- 弹幕 ----
    def show_danmaku(self, text):
        """车道管理：每条车道同一时刻最多一条；没有空闲车道就丢弃（简单可靠）"""
        try:
            lane = self._lanes.index(None)
        except ValueError:
            print(f"[ui] 弹幕车道已满，丢弃: {text[:20]}", flush=True)
            return
        # 车道中心 y = 上边距 + 车道偏移 + 半车道高，保证整行文字在窗口内
        y = self._lane_top + lane * self._lane_h + self._lane_h // 2
        color = DANMAKU_COLORS[lane % len(DANMAKU_COLORS)]
        # 不同车道错开水平出发点，避免并排齐飞
        x0 = self.screen_w + 10 + lane * 220
        item = self.danmaku_canvas.create_text(
            x0, y, text=text, anchor="w",
            font=self.danmaku_font, fill=color)
        # 速度：config.DANMAKU_SPEED>0 用固定值；=0 按文案长度自适应，
        # 全程横越（右缘出发到完全飞出左缘）控制在 DANMAKU_CROSS_SECONDS 秒
        fixed = getattr(config, "DANMAKU_SPEED", 0)
        if fixed and fixed > 0:
            speed = fixed
        else:
            width = self.danmaku_font.measure(text)
            distance = x0 + width + 20
            frames = max(getattr(config, "DANMAKU_CROSS_SECONDS", 5) * 1000
                         / FRAME_MS, 1)
            speed = max(distance / frames, 4)
        self._lanes[lane] = item
        self._danmakus.append((item, lane, speed))

    def _tick_danmaku(self):
        alive = []
        for item, lane, speed in self._danmakus:
            self.danmaku_canvas.move(item, -speed, 0)
            x = self.danmaku_canvas.coords(item)[0]
            if x + 800 > 0:      # 粗略宽度，飞出左边界就删
                alive.append((item, lane, speed))
            else:
                self.danmaku_canvas.delete(item)
                self._lanes[lane] = None
        self._danmakus = alive
        self.root.after(FRAME_MS, self._tick_danmaku)

    # ---- 队列消费 + 心跳 ----
    def _poll_queue(self):
        try:
            with open(ALIVE_FILE, "w") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        try:
            with open(config.UI_QUEUE, encoding="utf-8") as f:
                f.seek(self._queue_offset)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "bubble":
                        self.show_bubble(msg.get("text", ""))
                    elif msg.get("type") == "danmaku":
                        self.show_danmaku(msg.get("text", ""))
                    elif msg.get("type") == "mic_state":
                        self._set_mic_state(bool(msg.get("on")))
                    elif msg.get("type") == "setting":
                        self._apply_setting(msg.get("key"), msg.get("value"))
                self._queue_offset = f.tell()
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[ui] 队列消费异常: {e}", flush=True)
        self.root.after(500, self._poll_queue)

    def run(self):
        print("[ui] 搭子形象已启动", flush=True)
        self.root.after(500, self._poll_queue)
        self.root.after(FRAME_MS, self._tick_danmaku)
        # 向 main 查询当前运行时设置，同步菜单勾选
        self.root.after(1500, lambda: self._send_cmd("query_settings"))
        self.root.mainloop()


if __name__ == "__main__":
    # 单例锁：已有活实例直接退出（双保险，防双形象）
    import ctypes
    _lock = os.path.join(config.LOG_DIR, "ui.lock")
    os.makedirs(config.LOG_DIR, exist_ok=True)
    try:
        with open(_lock) as _f:
            _old = int(_f.read().strip())
        _h = ctypes.windll.kernel32.OpenProcess(0x1000, False, _old)
        if _h:
            ctypes.windll.kernel32.CloseHandle(_h)
            sys.exit(0)          # 已有活实例
    except (OSError, ValueError):
        pass
    with open(_lock, "w") as _f:
        _f.write(str(os.getpid()))

    # 崩溃留证据：pythonw 无控制台，段错误/异常都必须落盘
    import faulthandler
    import traceback
    _crash_f = open(os.path.join(config.LOG_DIR, "crash-ui.log"), "a",
                    encoding="utf-8", buffering=1)
    faulthandler.enable(file=_crash_f)
    try:
        CompanionUI().run()
    except BaseException:
        _crash_f.write(f"\n=== {time.strftime('%F %T')} UI 异常退出 ===\n")
        traceback.print_exc(file=_crash_f)
        _crash_f.flush()
        raise
    finally:
        try:
            os.remove(_lock)
        except OSError:
            pass
