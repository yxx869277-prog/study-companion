# -*- coding: utf-8 -*-
"""生成式互动文案 + corpus.json 语料库。
- LLM 生成时附 2-3 条该类别语料做 few-shot 风格示例
- 兜底从语料库对应类别随机选句填空（占位符填不上就换一句）
独立线程 + 超时，任何异常不炸主流程。"""
import json
import os
import random
import re
import threading
import time

import local_api

import config
import logger

GEN_TIMEOUT = 45               # 生成超时（秒）
MAX_LEN = 40                   # 超过这个长度视为不合格，走兜底

_CORPUS = None


def _load_corpus():
    """加载 corpus.json（只加载一次；缺文件时给空库，兜底退化为固定句）"""
    global _CORPUS
    if _CORPUS is None:
        path = os.path.join(config.BASE_DIR, "corpus.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _CORPUS = {k: v for k, v in data.items()
                       if not k.startswith("_") and isinstance(v, list)}
        except Exception:
            _CORPUS = {}
    return _CORPUS


# 从 detail 里提取应用名（匹配不到返回 None，就不选含 {app} 的句子）
_APP_PATTERNS = [
    (r"B站|bilibili|哔哩哔哩", "B站"),
    (r"微信|WeChat", "微信"),
    (r"QQ", "QQ"),
    (r"Kimi Code|kimi", "Kimi Code"),
    (r"[Cc]odex", "Codex"),
    (r"VS ?Code|Visual Studio Code", "VS Code"),
    (r"Word|WPS", "Word"),
    (r"PDF|pdf", "PDF阅读器"),
    (r"浏览器|Chrome|Edge|Firefox", "浏览器"),
    (r"终端|terminal|PowerShell|cmd", "终端"),
    (r"Excel|表格", "Excel"),
]


def extract_app(detail):
    for pat, name in _APP_PATTERNS:
        if re.search(pat, detail or ""):
            return name
    return None


def fill_corpus(rule, n=0, course=None, app=None, detail=None):
    """从语料库对应类别随机选句并填占位符；填不干净就换一句。
    始终返回无残留花括号的句子。
    fun_long 特殊：语料按语气从轻到急排序，n<20 从前半选，否则从后半选。"""
    pool = list(_load_corpus().get(rule, []))
    if rule == "fun_long" and len(pool) >= 2:
        half = len(pool) // 2
        pool = pool[:half] if n < 20 else pool[half:]
    random.shuffle(pool)
    for s in pool:
        # 缺的变量不硬填：含对应占位符的句子直接跳过
        if "{course}" in s and not course:
            continue
        if "{app}" in s and not app:
            continue
        if "{detail}" in s and not detail:
            continue
        if "{n}" in s and not n:
            continue
        out = s.replace("{n}", str(n))
        out = out.replace("{course}", course or "")
        out = out.replace("{app}", app or "")
        out = out.replace("{detail}", detail or "")
        if "{" not in out and "}" not in out:
            return out
    # 再兜底：任选一条无占位符的
    for s in pool:
        if "{" not in s:
            return s
    return "继续加油，我陪着你"


_RULE_INTENT = {
    "study_welcome": "用户刚开始学习，欢迎他一下，给他打气",
    "course_cheer": "用户已经连续看网课 {minutes} 分钟了，夸他专注，鼓励他继续",
    "course_to_fun": "用户刚才还在学习，现在切去娱乐了，温和地吐槽他一下（别凶）",
    "break_reminder": "用户已经连续学习 {minutes} 分钟了，提醒他起来休息一下",
    "coding_cheer": "用户已经连续写代码 {minutes} 分钟了，轻松夸一句",
    "agent_cheer": "用户已经连续用 AI 智能体（如 Kimi Code/Codex）协作 {minutes} 分钟了，像损友一样夸他会指挥 AI",
    "reading_cheer": "用户已经连续阅读/刷题 {minutes} 分钟了，轻松夸一句",
    "social_long": "用户已经连续聊天 {minutes} 分钟了，温和提醒他别聊太久",
    "fun_long": "用户已经连续娱乐 {minutes} 分钟了，提醒他该回去学习了",
    "late_night": "现在是深夜，用户还在学习，关心他让他别熬太晚",
    "phone_detected": "用户在屏幕学习状态下被摄像头发现连续看手机，像损友一样点破他",
    "away_notice": "用户在学习时间离开座位有一会儿了，随口说一句他溜了",
    "welcome_back": "用户离开座位后刚回来，欢迎他回来继续学习",
    "doze_care": "用户趴在桌上休息，温和关心他别太累",
}


def _build_prompt(rule, state, detail, course_hint, minutes):
    intent = _RULE_INTENT.get(rule, "陪用户学习").format(minutes=minutes)
    ctx = f"用户当前状态：{state}。屏幕上正在发生的事：{detail or '未知'}。"
    if course_hint:
        ctx += f"课程主题：{course_hint}。"
    # few-shot：附该类别 2-3 条语料做风格示例
    pool = _load_corpus().get(rule, [])
    shots = random.sample(pool, min(3, len(pool)))
    shot_txt = "\n".join(f"- {s}" for s in shots) or "- 继续加油"
    return (
        f"你是用户的学习搭子朋友。{ctx}\n"
        f"现在你要对他说一句话：{intent}。\n"
        f"风格参考（语气向这些看齐，别照抄）：\n{shot_txt}\n"
        "要求：≤25 字；像朋友聊天一样轻松口语；尽量具体提到他正在做的事；"
        "**软件名只能在 detail 里明确出现时才能提**（比如 detail 写了 Kimi Code 才能说 Kimi Code）；"
        "detail 里没写清具体名字的（如只写“AI 智能体”“Coder Agent”“终端”），就用“AI”“智能体”这类泛称，严禁编造具体产品名；"
        "不要 emoji 堆砌，不要说教。只输出这句话本身，不要引号不要解释。 /no_think"
    )


def _generate(rule, state, detail, course_hint, minutes):
    """Generate on the same local backend selected for vision."""
    if not config.MONITORING_ACTIVE:
        return None
    prompt = _build_prompt(rule, state, detail, course_hint, minutes)
    try:
        msg = local_api.text_chat(prompt, config.GENMSG_MODEL,
                                  timeout=GEN_TIMEOUT, max_tokens=120)
        msg = msg.split("\n")[0].strip().strip('"“”')
        if not msg or len(msg) > MAX_LEN or "{" in msg:
            return None
        return msg
    except Exception:
        return None


def fire_async(rule, state, detail, course_hint, minutes, deliver, fallback=None):
    """触发互动：优先吃预生成缓存（命中≈零延迟）；未命中且该 intent 正在预生成
    则等它一会儿；再不行走现有同步生成 + 语料库填空兜底。"""
    ent = pop_cache(rule)
    if ent is not None:
        msg = ent[0]
        logger.log("interaction_cache_hit", rule=rule, message=msg)
        print(f"[genmsg] 预生成缓存命中({rule})，零延迟上屏", flush=True)
        try:
            deliver(msg)
        except Exception:
            pass
        return

    def work():
        # 该 intent 可能正在预生成，等它最多 12 秒，避免重复调 LLM
        waited = 0.0
        while is_pending(rule) and waited < 12:
            time.sleep(0.5)
            waited += 0.5
            ent = pop_cache(rule)
            if ent is not None:
                try:
                    deliver(ent[0])
                except Exception:
                    pass
                return
        msg = _generate(rule, state, detail, course_hint, minutes)
        if msg is None:
            msg = _generate(rule, state, detail, course_hint, minutes)  # 重试一次
        if msg is None:
            if fallback:
                msg = random.choice(fallback)
            else:
                msg = fill_corpus(rule, n=minutes, course=course_hint,
                                  app=extract_app(detail), detail=detail)
        try:
            deliver(msg)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


# ---- 预生成缓存（预测式：阈值 70% 时提前生成，触发即零延迟）----
CACHE_TTL = 600                # 缓存 10 分钟过期
_cache = {}                    # rule -> (msg, context, expire_ts)
_pending = set()               # 正在预生成的 rule（防重复）
_cache_lock = threading.Lock()


def pop_cache(rule):
    """取并消费缓存（一次性），过期返回 None"""
    with _cache_lock:
        ent = _cache.pop(rule, None)
    if ent and ent[2] > time.time():
        return ent
    return None


def is_pending(rule):
    with _cache_lock:
        return rule in _pending


def pre_generate(rule, state, detail, course_hint, minutes):
    """后台预生成并缓存。已有新鲜缓存或正在生成则不重复跑。
    minutes 传目标阈值（如 course_cheer 传 30），不是当前分钟数。"""
    with _cache_lock:
        if rule in _pending:
            return
        ent = _cache.get(rule)
        if ent and ent[2] > time.time():
            return
        _pending.add(rule)
    print(f"[genmsg] 预生成启动({rule})", flush=True)

    def work():
        msg = _generate(rule, state, detail, course_hint, minutes)
        with _cache_lock:
            _pending.discard(rule)
            if msg:
                _cache[rule] = (msg, {"state": state, "detail": detail,
                                      "course_hint": course_hint,
                                      "minutes": minutes},
                                time.time() + CACHE_TTL)
                print(f"[genmsg] 预生成完成({rule}): {msg[:20]}", flush=True)
    threading.Thread(target=work, daemon=True).start()
