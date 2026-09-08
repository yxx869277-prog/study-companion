# -*- coding: utf-8 -*-
"""本机学习日报；模型不可用时明确输出原始摘录。默认 data/reports。"""
import json
import os
import sys
from datetime import datetime

import local_api

import config


# ---------- 数据加载 ----------

def load_events(date):
    path = os.path.join(config.LOG_DIR, f"events-{date}.jsonl")
    if not os.path.exists(path):
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def load_text(date, kind):
    """kind: transcript(md) / subtitles(txt)"""
    ext = "md" if kind == "transcript" else "txt"
    path = os.path.join(config.LOG_DIR, f"{kind}-{date}.{ext}")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_timeline(events):
    """observation 事件 → 合并连续同状态为时段 [(start,end,state,detail)]
    没有 observation 时退回 state_change（兼容旧日志）"""
    obs = [e for e in events if e.get("type") == "observation" and e.get("state")]
    if not obs:
        obs = [e for e in events if e.get("type") == "state_change" and e.get("state")]
    segments = []
    for e in obs:
        ts = e.get("ts", "")[:19]
        if segments and segments[-1][2] == e["state"]:
            segments[-1][1] = ts
            segments[-1][3] = e.get("detail") or segments[-1][3]
        else:
            segments.append([ts, ts, e["state"], e.get("detail", "")])
    return segments


def behavior_stats(timeline):
    """各状态总时长（分钟），按相邻时段时间差估算"""
    stats = {}
    for i, (t0, t1, state, _) in enumerate(timeline):
        try:
            end = timeline[i + 1][0] if i + 1 < len(timeline) else t1
            minutes = max((datetime.fromisoformat(end) -
                           datetime.fromisoformat(t0)).total_seconds() / 60, 0)
        except ValueError:
            minutes = 0
        stats[state] = stats.get(state, 0) + minutes
    return stats


def _webcam_section(events):
    """webcam 事件 → 次数统计 + 时段明细"""
    wc = [e for e in events if e.get("type") == "webcam" and e.get("behavior")]
    if not wc:
        return "（当日无摄像头数据）"
    counts = {}
    for e in wc:
        counts[e["behavior"]] = counts.get(e["behavior"], 0) + 1
    count_line = "，".join(f"{k} {v} 次" for k, v in
                          sorted(counts.items(), key=lambda x: -x[1]))
    lines = "\n".join(
        f"- {e.get('ts','')[11:19]} 【{e['behavior']}】{e.get('note','')}"
        for e in wc)
    return f"统计：{count_line}\n\n明细：\n{lines}"


def _split_transcript(text):
    """transcript 按片段标题里的来源标注拆成系统声音/麦克风两路"""
    sys_parts, mic_parts = [], []
    for chunk in text.split("### 片段"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "（麦克风）" in chunk.splitlines()[0]:
            mic_parts.append(chunk)
        else:
            sys_parts.append(chunk)
    fmt = lambda parts: "\n\n".join("### 片段 " + p for p in parts)
    return fmt(sys_parts), fmt(mic_parts)


def build_material(date, timeline, stats, interactions, transcript, subtitles, events):
    """整理成素材文件文本（三路数据：屏幕 + 摄像头 + 声音）"""
    tl_lines = "\n".join(
        f"- {s[11:19]} ~ {e[11:19]} 【{st}】{d}" for s, e, st, d in timeline) or "（无记录）"
    stat_lines = "\n".join(f"- {k}: {v:.0f} 分钟" for k, v in
                           sorted(stats.items(), key=lambda x: -x[1])) or "（无记录）"
    sys_t, mic_t = _split_transcript(transcript)
    return f"""# {date} 学习监控原始素材（三路数据源）

## 一、屏幕时间线（observation/state_change）
{tl_lines}

### 状态时长汇总
{stat_lines}

### 互动记录（搭子发出的提醒/打气/吐槽）
{interactions or "（无）"}

## 二、摄像头行为（webcam 事件：在座学习/在座看手机/离开座位/趴桌休息/无法判断）
{_webcam_section(events)}

## 三、声音记录

### 系统声音转写原文（网课/视频/通话对方说的话）
{sys_t[:10000] or "（无）"}

### 麦克风转写原文（用户自己说的话/口述想法）
{mic_t[:6000] or "（无）"}

### 屏幕 OCR 原文（参考，噪声较大）
{subtitles[:5000] or "（无）"}
"""


REPORT_REQUIREMENTS = """日报要求：
1. 分两层。**行为层**：根据屏幕时间线给出逐时段活动表（时间段 | 状态 | 内容），加状态时长汇总表；再结合摄像头行为数据做专注度分析——看手机几次、离开座位几次、趴桌休息几次、各在什么时段，必须写清楚；屏幕与摄像头相互印证（如"屏幕在学习但人在看手机"）。
2. **内容层**：网课知识点来自"系统声音转写原文"，分主题列要点。如果当天有"麦克风转写原文"，单独开一小节"今日口述/想法"，忠于原文整理用户自己口头表达的内容。
3. 公式、术语、知识点必须忠于转写原文，绝对不许编造原文没有的内容；哪路数据没有就明说哪路没数据（如"今日无麦克风记录"），不许硬凑。
4. 语气自然简洁，不要客套话。"""


def frontmatter(date):
    return f"""---
title: 学习日报 {date}
created: {datetime.now().isoformat(timespec="seconds")}
tags: [学习日报]
---

"""


def call_ollama(prompt, model):
    try:
        return local_api.text_chat(prompt, model, timeout=300, max_tokens=1800)
    except Exception as error:
        print(f"[report] 本机模型不可用：{type(error).__name__}", flush=True)
        return None


def local_report(date, material):
    prompt = (
        f"你是一位学习陪伴助手。以下是 {date} 的监控素材，请生成一份 Markdown 学习日报正文"
        f"（不要 frontmatter，不要代码块包裹）。\n{REPORT_REQUIREMENTS}\n\n{material}"
    )
    for model in dict.fromkeys((config.SUMMARY_MODEL, config.VISION_MODEL)):
        body = call_ollama(prompt, model)
        if body:
            print(f"[summarize] 本地模型 {model} 生成成功", flush=True)
            return body
        print(f"[summarize] 本地模型 {model} 不可用", flush=True)
    return None


# ---------- 第三级：降级拼接 ----------

def fallback_report(date, timeline, stats, transcript, subtitles):
    tl_lines = "\n".join(
        f"| {s[11:19]} ~ {e[11:19]} | {st} | {d} |" for s, e, st, d in timeline) \
        or "| （无） | - | - |"
    stat_lines = "\n".join(f"| {k} | {v:.0f} |" for k, v in
                           sorted(stats.items(), key=lambda x: -x[1])) or "| （无） | 0 |"
    return f"""## 行为层（降级输出）

| 时间段 | 状态 | 内容 |
| --- | --- | --- |
{tl_lines}

| 状态 | 时长（分钟） |
| --- | --- |
{stat_lines}

## 内容层（降级输出）

> LLM 不可用，以下为原始转写/字幕摘录，未做总结。

### 网课转写
{transcript[:3000] or "（无）"}

### 字幕 OCR
{subtitles[:1500] or "（无）"}
"""


# ---------- 主流程 ----------

def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    date = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
    events = load_events(date)
    transcript = load_text(date, "transcript")
    subtitles = load_text(date, "subtitles")
    timeline = build_timeline(events)
    stats = behavior_stats(timeline)
    interactions = "\n".join(
        f"- {e.get('ts','')[:19]}[{e.get('rule','')}] {e.get('message','')}"
        for e in events if e.get("type") == "interaction")

    material = build_material(date, timeline, stats, interactions,
                              transcript, subtitles, events)
    os.makedirs(config.LOG_DIR, exist_ok=True)
    material_path = os.path.join(config.LOG_DIR, f"report-material-{date}.md")
    with open(material_path, "w", encoding="utf-8") as f:
        f.write(material)

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    out_path = os.path.join(config.REPORT_DIR, f"{date}.md")

    # 第二级：本地 Ollama
    body = local_report(date, material)
    degraded = False
    if not body:
        # 第三级：降级拼接
        body = fallback_report(date, timeline, stats, transcript, subtitles)
        degraded = True

    md = frontmatter(date) + f"# 学习日报 {date}\n\n{body}\n"
    md += "\n> 活动分类与时长为抽样估计；知识点可能误识别，请对照课程原文核对。\n"
    if degraded:
        md += "\n> ⚠️ 本日报为降级输出（本机 LLM 不可用，未做智能总结）。\n"
    if os.path.exists(out_path):
        from shutil import copy2
        copy2(out_path, out_path + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"日报已写入: {out_path}" + ("（降级输出）" if degraded else ""))


if __name__ == "__main__":
    main()
