# -*- coding: utf-8 -*-
"""日志可视化仪表盘：python dashboard.py [YYYY-MM-DD]（默认今天）
读取当天 events jsonl（+ transcript 若有），生成单文件 HTML 并用默认浏览器打开。
纯标准库，内联 CSS/JS，离线可开。"""
import html
import json
import os
import sys
from datetime import datetime

import config

# ---- 状态色板（改这里调配色）----
STATE_COLORS = {
    "网课":   "#2e9e5b",
    "写代码": "#37b24d",
    "AI协作": "#0ca678",
    "读文档": "#74c69d",
    "学习平台": "#52b788",
    "娱乐视频": "#e03131",
    "社交聊天": "#f4a261",
    "空闲":   "#adb5bd",
    "其他":   "#4d96ff",
}
STUDY_STATES = {"网课", "写代码", "读文档", "学习平台", "AI协作"}
DEFAULT_COLOR = "#4d96ff"


def load_events(date):
    path = os.path.join(config.LOG_DIR, f"events-{date}.jsonl")
    events = []
    if not os.path.exists(path):
        return events
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def load_transcript(date):
    path = os.path.join(config.LOG_DIR, f"transcript-{date}.md")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_segments(events):
    """observation（无则用 state_change 兜底）→ 连续同状态合并为时段"""
    obs = [e for e in events if e.get("type") == "observation" and e.get("state")]
    if not obs:
        obs = [e for e in events if e.get("type") == "state_change" and e.get("state")]
    segs = []
    for e in obs:
        ts = e.get("ts", "")[:19]
        if segs and segs[-1][2] == e["state"]:
            segs[-1][1] = ts
            segs[-1][3] = e.get("detail") or segs[-1][3]
        else:
            segs.append([ts, ts, e["state"], e.get("detail", "")])
    return segs


def stats(events, segs):
    """各状态分钟数 + 互动次数 + 转写段数"""
    dur = {}
    for i, (t0, t1, state, _) in enumerate(segs):
        try:
            end = segs[i + 1][0] if i + 1 < len(segs) else t1
            m = max((datetime.fromisoformat(end) -
                     datetime.fromisoformat(t0)).total_seconds() / 60, 0)
        except ValueError:
            m = 0
        dur[state] = dur.get(state, 0) + m
    interactions = sum(1 for e in events if e.get("type") == "interaction")
    transcripts = sum(1 for e in events if e.get("type") == "transcript_segment")
    return dur, interactions, transcripts


def esc(s):
    return html.escape(str(s or ""))


def timeline_html(segs):
    """0-24h 横向色带，绝对定位色块"""
    blocks = []
    for i, (t0, t1, state, detail) in enumerate(segs):
        try:
            start = datetime.fromisoformat(t0)
            end = datetime.fromisoformat(segs[i + 1][0]) if i + 1 < len(segs) \
                else datetime.fromisoformat(t1)
        except ValueError:
            continue
        s_sec = start.hour * 3600 + start.minute * 60 + start.second
        e_sec = max(end.hour * 3600 + end.minute * 60 + end.second, s_sec + 30)
        left = s_sec / 86400 * 100
        width = (e_sec - s_sec) / 86400 * 100
        color = STATE_COLORS.get(state, DEFAULT_COLOR)
        tip = f"{t0[11:19]} ~ {end.strftime('%H:%M:%S')} 【{state}】{detail}"
        blocks.append(
            f'<div class="tl-block" style="left:{left:.3f}%;width:{width:.3f}%;'
            f'background:{color}" title="{esc(tip)}"></div>')
    hours = "".join(f'<span class="tl-hour" style="left:{h/24*100:.2f}%">{h}</span>'
                    for h in range(0, 25, 2))
    return f'<div class="tl-wrap"><div class="tl-bar">{"".join(blocks)}</div>' \
           f'<div class="tl-scale">{hours}</div></div>'


def legend_html():
    items = "".join(
        f'<span class="legend-item"><span class="legend-dot" style="background:{c}"></span>{s}</span>'
        for s, c in STATE_COLORS.items())
    return f'<div class="legend">{items}</div>'


def overview_html(date, dur, interactions, transcripts, segs):
    total = sum(dur.values())
    study = sum(v for k, v in dur.items() if k in STUDY_STATES)
    fun = dur.get("娱乐视频", 0)
    social = dur.get("社交聊天", 0)
    idle = dur.get("空闲", 0)

    def card(label, value, sub=""):
        return (f'<div class="card"><div class="card-value">{value}</div>'
                f'<div class="card-label">{label}</div>'
                f'<div class="card-sub">{sub}</div></div>')

    dur_rows = "".join(
        f'<tr><td><span class="legend-dot" style="background:{STATE_COLORS.get(k, DEFAULT_COLOR)}"></span>{esc(k)}</td>'
        f'<td>{v:.0f} 分钟</td><td>{(v/total*100 if total else 0):.1f}%</td></tr>'
        for k, v in sorted(dur.items(), key=lambda x: -x[1]))
    return f"""
<div class="cards">
  {card("总监控时长", f"{total:.0f}<small>分钟</small>")}
  {card("学习类", f"{study:.0f}<small>分钟</small>", f"{(study/total*100 if total else 0):.0f}%")}
  {card("娱乐视频", f"{fun:.0f}<small>分钟</small>")}
  {card("社交聊天", f"{social:.0f}<small>分钟</small>")}
  {card("空闲", f"{idle:.0f}<small>分钟</small>")}
  {card("互动次数", interactions)}
  {card("网课转写段", transcripts)}
</div>
<table class="dur-table"><tr><th>状态</th><th>时长</th><th>占比</th></tr>{dur_rows}</table>
"""


def flow_html(segs):
    """活动流水：最近 50 条默认显示，其余折叠"""
    rows = []
    for i, (t0, t1, state, detail) in enumerate(segs):
        rows.append(
            f'<tr class="flow-row" data-idx="{i}"><td>{esc(t0[11:19])}</td>'
            f'<td><span class="legend-dot" style="background:{STATE_COLORS.get(state, DEFAULT_COLOR)}"></span>{esc(state)}</td>'
            f'<td>{esc(detail)}</td></tr>')
    n = len(rows)
    show_from = max(0, n - 50)          # 默认只显示最近 50 条
    body = "".join(
        r.replace('class="flow-row"', 'class="flow-row hidden"')
        if i < show_from else r for i, r in enumerate(rows))
    btn = (f'<button onclick="toggleFlow(this)" data-shown="0">展开全部（{n} 条）</button>'
           if n > 50 else "")
    return btn + f'<table class="flow-table"><tr><th>时间</th><th>状态</th><th>内容</th></tr>{body}</table>'


def interactions_html(events):
    rows = "".join(
        f'<tr><td>{esc(e.get("ts","")[11:19])}</td><td>{esc(e.get("rule"))}</td>'
        f'<td>{esc(e.get("message"))}</td><td>{esc("+".join(e.get("channels") or []))}</td></tr>'
        for e in events if e.get("type") == "interaction")
    if not rows:
        return "<p class='empty'>当日无互动记录</p>"
    return f'<table class="flow-table"><tr><th>时间</th><th>规则</th><th>文案</th><th>渠道</th></tr>{rows}</table>'


def transcript_html(text):
    if not text.strip():
        return ""
    parts = [p.strip() for p in text.split("### 片段") if p.strip()]
    blocks = "".join(
        f'<div class="seg"><div class="seg-title">片段 {esc(p.splitlines()[0])}</div>'
        f'<pre>{esc(chr(10).join(p.splitlines()[1:]))}</pre></div>' for p in parts)
    return f"<h2>网课内容（语音转写）</h2>{blocks}"


CSS = """
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei UI", "PingFang SC", sans-serif; background:#f6f7f9;
       color:#222; margin:0; padding:24px; max-width:1100px; margin:0 auto; }
h1 { font-size:22px; } h2 { font-size:17px; margin-top:28px; border-left:4px solid #2e9e5b; padding-left:8px; }
.sub { color:#888; font-size:13px; }
.cards { display:flex; flex-wrap:wrap; gap:12px; margin:16px 0; }
.card { background:#fff; border-radius:10px; padding:14px 18px; min-width:120px;
        box-shadow:0 1px 3px rgba(0,0,0,.08); }
.card-value { font-size:24px; font-weight:700; color:#2e9e5b; }
.card-value small { font-size:12px; font-weight:400; margin-left:2px; }
.card-label { font-size:13px; color:#555; } .card-sub { font-size:12px; color:#999; }
.dur-table, .flow-table { width:100%; border-collapse:collapse; background:#fff;
        border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-top:10px; }
th, td { padding:8px 12px; text-align:left; font-size:13px; border-bottom:1px solid #eee; }
th { background:#f0f1f3; }
.tl-wrap { margin:14px 0 4px; }
.tl-bar { position:relative; height:44px; background:#e9ecef; border-radius:6px; overflow:hidden; }
.tl-block { position:absolute; top:0; height:100%; }
.tl-scale { position:relative; height:18px; }
.tl-hour { position:absolute; font-size:11px; color:#999; transform:translateX(-50%); }
.legend { margin:8px 0; font-size:12px; color:#555; }
.legend-item { margin-right:14px; } .legend-dot { display:inline-block; width:10px; height:10px;
        border-radius:2px; margin-right:4px; }
.hidden { display:none; }
button { background:#2e9e5b; color:#fff; border:0; border-radius:6px; padding:6px 14px;
         font-size:13px; cursor:pointer; margin:8px 0; }
.seg { background:#fff; border-radius:8px; padding:10px 14px; margin:10px 0;
       box-shadow:0 1px 3px rgba(0,0,0,.08); }
.seg-title { font-weight:600; font-size:13px; color:#2e9e5b; }
pre { white-space:pre-wrap; font-size:13px; font-family:inherit; margin:6px 0 0; }
.empty { color:#999; font-size:13px; }
"""

JS = """
function toggleFlow(btn){
  var hidden = document.querySelectorAll('.flow-row.hidden');
  if(btn.dataset.shown === '0'){
    hidden.forEach(function(r){ r.classList.remove('hidden'); });
    btn.textContent = '收起'; btn.dataset.shown = '1';
  } else {
    document.querySelectorAll('.flow-row').forEach(function(r){
      if(parseInt(r.dataset.idx) < window._showFrom) r.classList.add('hidden');
    });
    btn.textContent = '展开全部'; btn.dataset.shown = '0';
  }
}
"""


def generate(date):
    events = load_events(date)
    transcript = load_transcript(date)
    out_path = os.path.join(config.LOG_DIR, f"dashboard-{date}.html")

    if not events:
        body = "<p class='empty'>当日无数据</p>"
        show_from_js = "0"
    else:
        segs = build_segments(events)
        dur, n_inter, n_trans = stats(events, segs)
        show_from_js = str(max(0, len(segs) - 50))
        body = f"""
<h2>概览</h2>
{overview_html(date, dur, n_inter, n_trans, segs)}
<h2>24 小时时间线</h2>
{legend_html()}
{timeline_html(segs)}
<h2>活动流水</h2>
{flow_html(segs)}
<h2>互动记录</h2>
{interactions_html(events)}
{transcript_html(transcript)}
"""

    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>学习搭子日报 {date}</title><style>{CSS}</style></head>
<body>
<h1>学习搭子 · {date}</h1>
<div class="sub">由 AI 学习搭子生成 · 数据源 data/logs/events-{date}.jsonl</div>
{body}
<script>window._showFrom = {show_from_js};</script>
<script>{JS}</script>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    date = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
    out = generate(date)
    print(f"仪表盘已生成: {out}")
    try:
        os.startfile(out)      # Windows：用默认浏览器打开
    except Exception as e:
        print(f"自动打开失败（可手动打开）: {e}")


if __name__ == "__main__":
    main()
