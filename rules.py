# -*- coding: utf-8 -*-
"""状态机 + 互动规则。文案走 genmsg 生成式（few-shot 语料风格），失败语料库填空兜底。
同一 tick 多条命中时只发优先级最高的一条：break > late_night > fun/social > cheer。"""
import time

import config
import genmsg
import logger
import notify

STUDY_STATES = {"网课", "学习平台", "写代码", "读文档", "AI协作"}

# 优先级（数字小者优先）
PRIO_BREAK = 1
PRIO_LATE = 2
PRIO_LONG = 3     # fun_long / social_long
PRIO_CHEER = 4    # course_cheer / coding_cheer / reading_cheer

# 各类阈值（分钟）
CODING_CHEER_MIN = 30
SOCIAL_LONG_MIN = 15
LATE_NIGHT_EVERY = 30
LATE_NIGHT_HOURS = {23, 0, 1}   # 23:00-02:00


class RuleEngine:
    def __init__(self):
        self._last_notify = 0.0
        self._state = None
        self._state_since = time.time()   # 当前状态连续起始
        self._study_since = time.time()   # 连续学习起始
        # 各规则进度标记
        self._cheered_at = 0              # course_cheer 已打气的分钟档位
        self._break_notified = False
        self._skill_cheered_at = 0        # coding/reading cheer 已打气档位
        self._social_fired = False
        self._fun_stage = 0               # fun_long 已提醒到第几档（10/25/40…分钟）
        self._late_at = 0                 # late_night 已提醒档位
        # 摄像头行为规则计数
        self._phone_streak = 0
        self._doze_streak = 0
        self._away_streak = 0
        self._was_away = False
        self._last_detail = ""

    def update_webcam(self, behavior):
        """摄像头行为结论输入（WebcamMonitor 线程回调）。
        只在屏幕处于学习类状态时评估，全部走生成式+语料兜底+冷却。"""
        state = self._state
        detail = self._last_detail
        if state not in STUDY_STATES:
            self._phone_streak = 0
            self._doze_streak = 0
            return
        # 连续 2 次"看手机" → 损友提醒
        if behavior == "在座看手机":
            self._phone_streak += 1
            if self._phone_streak >= 2 and self._cooldown_ok():
                self._phone_streak = 0
                self._fire("phone_detected", state, detail, None, 0,
                           kinds=("bubble",))
        else:
            self._phone_streak = 0
        # 连续 2 次"趴桌休息"且是白天 → 关怀
        if behavior == "趴桌休息":
            self._doze_streak += 1
            hour = time.localtime().tm_hour
            if self._doze_streak >= 2 and 6 <= hour < 23 and self._cooldown_ok():
                self._doze_streak = 0
                self._fire("doze_care", state, detail, None, 0,
                           kinds=("bubble",))
        else:
            self._doze_streak = 0
        # 连续 3 次"离开" → 标记离开；回座 → 欢迎回来
        if behavior == "离开座位":
            self._away_streak += 1
            if self._away_streak >= 3 and not self._was_away:
                self._was_away = True
                if self._cooldown_ok():
                    self._fire("away_notice", state, detail, None, 0,
                               kinds=("bubble",))
        elif behavior in ("在座学习", "在座看手机"):
            self._away_streak = 0
            if self._was_away:
                self._was_away = False
                if self._cooldown_ok():
                    self._fire("welcome_back", state, detail, None, 0,
                               kinds=("bubble", "danmaku"))

    def _cooldown_ok(self):
        return time.time() - self._last_notify >= config.INTERACT_COOLDOWN

    def _deliver(self, rule, msg, kinds, toast):
        """实际发送（可能在生成线程里被回调）"""
        if not config.MONITORING_ACTIVE:
            return
        if notify.ui_alive():
            for k in kinds:
                notify.notify("学习搭子", msg, kind=k)
            if toast:
                notify.system_toast("学习搭子", msg)
        else:
            notify.system_toast("学习搭子", msg)
        logger.log("interaction", rule=rule, title="学习搭子", message=msg,
                   channels=list(kinds) + (["toast"] if toast else []))
        # 语音播报（异步队列，不阻塞；TTS_ENABLED 控制）
        try:
            import tts
            tts.speak(msg)
        except Exception as e:
            logger.log("error", where="tts_submit", error=str(e))

    def _fire(self, rule, state, detail, course_hint, minutes,
              kinds=("bubble",), toast=False):
        """触发一次互动：冷却时间戳立即记录，文案后台生成后发送"""
        self._last_notify = time.time()
        genmsg.fire_async(rule, state, detail, course_hint, minutes,
                          lambda msg: self._deliver(rule, msg, kinds, toast))

    def update(self, state, course_hint=None, detail=""):
        """每次识别出新状态时调用"""
        now = time.time()
        prev = self._state
        self._last_detail = detail or self._last_detail

        if state != prev:
            self._state = state
            self._state_since = now
            self.pregen_on_transition(state, detail, course_hint)
            # 状态切换时重置按状态计的规则标记
            self._skill_cheered_at = 0
            self._social_fired = False
            self._fun_stage = 0
            # 规则：任何学习类状态 → 娱乐视频，立即提醒（气泡+弹幕）
            if prev in STUDY_STATES and state == "娱乐视频" and self._cooldown_ok():
                rule = "course_to_fun" if prev == "网课" else "study_to_fun"
                self._fire(rule, state, detail, course_hint, 0,
                           kinds=("bubble", "danmaku"))
            # 规则：进入学习类状态 → 弹幕欢迎（受冷却约束）
            if state in STUDY_STATES and prev not in STUDY_STATES:
                self._study_since = now
                self._cheered_at = 0
                self._break_notified = False
                self._late_at = 0
                if self._cooldown_ok():
                    # 欢迎语走气泡+弹幕双通道：纯弹幕容易被专注中的用户错过
                    self._fire("study_welcome", state, detail, course_hint, 0,
                               kinds=("danmaku", "bubble"))
            elif state not in STUDY_STATES:
                self._study_since = now
                self._cheered_at = 0
                self._break_notified = False
                self._late_at = 0

        state_min = (now - self._state_since) / 60   # 当前状态连续分钟
        study_min = (now - self._study_since) / 60   # 连续学习分钟

        # ---- 收集本 tick 命中的规则（优先级, rule, minutes, kinds, toast, 标记回调）----
        cands = []

        if state in STUDY_STATES:
            brk = config.STUDY_BREAK_MINUTES
            if study_min >= brk and not self._break_notified:
                cands.append((PRIO_BREAK, "break_reminder", int(study_min),
                              ("bubble",), True,
                              lambda: setattr(self, "_break_notified", True)))
            hour = time.localtime(now).tm_hour
            if hour in LATE_NIGHT_HOURS and study_min >= self._late_at + LATE_NIGHT_EVERY:
                cands.append((PRIO_LATE, "late_night", int(study_min),
                              ("bubble",), False,
                              lambda: setattr(self, "_late_at",
                                              self._late_at + LATE_NIGHT_EVERY)))
            if state == "网课":
                cheer_min = config.COURSE_CHEER_MINUTES
                if study_min >= cheer_min and self._cheered_at < cheer_min:
                    cands.append((PRIO_CHEER, "course_cheer", int(study_min),
                                  ("danmaku", "bubble"), False,
                                  lambda: setattr(self, "_cheered_at", cheer_min)))
            elif state in ("写代码", "AI协作"):
                # 写代码 → coding_cheer；AI协作 → agent_cheer（同档位逻辑）
                cheer_rule = "coding_cheer" if state == "写代码" else "agent_cheer"
                if state_min >= self._skill_cheered_at + CODING_CHEER_MIN:
                    cands.append((PRIO_CHEER, cheer_rule, int(state_min),
                                  ("danmaku",), False,
                                  lambda: setattr(self, "_skill_cheered_at",
                                                  self._skill_cheered_at + CODING_CHEER_MIN)))
            elif state in ("读文档", "学习平台"):
                if state_min >= self._skill_cheered_at + CODING_CHEER_MIN:
                    cands.append((PRIO_CHEER, "reading_cheer", int(state_min),
                                  ("danmaku",), False,
                                  lambda: setattr(self, "_skill_cheered_at",
                                                  self._skill_cheered_at + CODING_CHEER_MIN)))
        elif state == "社交聊天":
            if state_min >= SOCIAL_LONG_MIN and not self._social_fired:
                cands.append((PRIO_LONG, "social_long", int(state_min),
                              ("bubble",), False,
                              lambda: setattr(self, "_social_fired", True)))
        elif state == "娱乐视频":
            # FUN_WARN_MINUTES 首提醒，之后每 FUN_REPEAT_MINUTES 重复提醒（弹幕+气泡）
            threshold = (config.FUN_WARN_MINUTES +
                         config.FUN_REPEAT_MINUTES * self._fun_stage)
            if state_min >= threshold:
                cands.append((PRIO_LONG, "fun_long", int(state_min),
                              ("danmaku", "bubble"), False,
                              lambda: setattr(self, "_fun_stage",
                                              self._fun_stage + 1)))

        # ---- 仲裁：只发优先级最高的一条（冷却不通过就都不发，下 tick 再评）----
        if cands and self._cooldown_ok():
            cands.sort(key=lambda c: c[0])
            _, rule, minutes, kinds, toast, mark = cands[0]
            mark()
            self._fire(rule, state, detail, course_hint, minutes,
                       kinds=kinds, toast=toast)

        # ---- 预测式预生成：阈值 70% 时提前生成文案，触发即零延迟 ----
        P = genmsg.pre_generate
        if state == "网课":
            if study_min >= 0.7 * config.COURSE_CHEER_MINUTES:
                P("course_cheer", state, detail, course_hint,
                  config.COURSE_CHEER_MINUTES)
            if study_min >= 0.7 * config.STUDY_BREAK_MINUTES:
                P("break_reminder", state, detail, course_hint,
                  config.STUDY_BREAK_MINUTES)
        elif state == "写代码" and state_min >= 0.7 * CODING_CHEER_MIN:
            P("coding_cheer", state, detail, course_hint, CODING_CHEER_MIN)
        elif state == "AI协作" and state_min >= 0.7 * CODING_CHEER_MIN:
            P("agent_cheer", state, detail, course_hint, CODING_CHEER_MIN)
        elif state in ("读文档", "学习平台") and state_min >= 0.7 * CODING_CHEER_MIN:
            P("reading_cheer", state, detail, course_hint, CODING_CHEER_MIN)
        elif state == "娱乐视频" and state_min >= 0.7 * config.FUN_WARN_MINUTES:
            P("fun_long", state, detail, course_hint, config.FUN_WARN_MINUTES)
        elif state == "社交聊天" and state_min >= 0.7 * SOCIAL_LONG_MIN:
            P("social_long", state, detail, course_hint, SOCIAL_LONG_MIN)
        # 深夜学习：到 70% 档位就预生成下一条
        if state in STUDY_STATES and time.localtime(now).tm_hour in LATE_NIGHT_HOURS \
                and study_min >= 0.7 * (self._late_at + LATE_NIGHT_EVERY):
            P("late_night", state, detail, course_hint,
              self._late_at + LATE_NIGHT_EVERY)

    def pregen_on_transition(self, state, detail, course_hint):
        """状态切换时预生成最可能的下一条互动（1-2 条，不堆量）"""
        if state == "网课":
            genmsg.pre_generate("course_to_fun", state, detail, course_hint, 0)
        elif state in ("学习平台", "写代码", "读文档", "AI协作"):
            genmsg.pre_generate("study_to_fun", state, detail, course_hint, 0)
