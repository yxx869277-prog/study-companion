"""Offline UI demonstration. Uses fictional messages and never starts collection."""
from pathlib import Path

import config
import companion_ui


class DemoUI(companion_ui.CompanionUI):
    def __init__(self):
        # The UI may inspect the length of its queue on construction. Keep even
        # this bookkeeping separate from the user's real application queue.
        config.UI_QUEUE = str(Path(config.BASE_DIR) / "data" / "demo" / "unused.jsonl")
        super().__init__()
        self.handle.config(text="演示模式 · 右键退出")
        self.menu.delete(0, "end")
        self.menu.add_command(label="重播虚构示例", command=self.replay)
        self.menu.add_separator()
        self.menu.add_command(label="退出演示", command=self.root.destroy)
        self._scheduled = []

    def _send_cmd(self, *args, **kwargs):
        # Demonstration interactions cannot send commands to a running app.
        pass

    def _send_mic_toggle(self):
        self.show_bubble("这是桌面演示，点击不会开启麦克风。")

    def replay(self):
        for job in self._scheduled:
            self.root.after_cancel(job)
        self._scheduled.clear()
        self.show_bubble("你好！这是虚构内容演示，不读取屏幕、不录音、不联网。")
        scenes = [
            (3000, "今天的小目标：读完一节，再用自己的话复述。"),
            (6500, "示例提醒：学了一会儿，起来伸个懒腰。"),
            (10000, "正式运行后，可按需整理网课文字和本机学习日报。"),
        ]
        for delay, text in scenes:
            self._scheduled.append(self.root.after(delay, self.show_danmaku, text))

    def run(self):
        # Intentionally omit live queues, heartbeats, model calls and capture.
        self.root.after(companion_ui.FRAME_MS, self._tick_danmaku)
        self.root.after(500, self.replay)
        self.root.mainloop()


if __name__ == "__main__":
    DemoUI().run()
