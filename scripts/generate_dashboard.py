#!/usr/bin/env python3
"""Build the local reading surface for 手手日报.

Markdown remains the canonical report. This script adds a small, local-only
editorial page for the index and for each dated report, with optional AI
session metadata collected by collect_ai_activity.py.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
SECTION_ORDER = ["Today", "Timeline", "Projects", "Ideas", "Questions", "Next", "Found"]
SECTION_ALIASES = {
    "Today": {"Today", "概要", "工作摘要", "昨日概要"},
    "Timeline": {"Timeline", "时间分布"},
    "Projects": {"Projects", "事项动态"},
    "Ideas": {"Ideas", "想法", "Decisions"},
    "Questions": {"Questions", "问题", "Open Loops"},
    "Next": {"Next", "待办", "今日待办", "待办清单", "Tomorrow"},
    "Found": {"Found", "Discoveries", "发现"},
}


@dataclass
class DailyReport:
    date: str
    markdown_href: str
    html_href: str
    sections: dict[str, str]
    active_hours: str
    ai_activity: dict
    screenshot_count: int
    demo: bool = False


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def normalize_heading(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^(?:\d+|[一二三四五六七八九十百]+)\s*[、.．)）:]\s*", "", value)
    return value.strip().rstrip("：:")


def parse_sections(text: str) -> dict[str, str]:
    headings: list[tuple[int, str]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            headings.append((index, normalize_heading(match.group(1))))

    result = {name: "" for name in SECTION_ORDER}
    for position, (start, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        body = re.sub(r"\n?(?:活跃工作时长|活动时长（采样估算）)：[^\n]*\s*$", "", body).strip()
        for name, aliases in SECTION_ALIASES.items():
            if heading in aliases:
                result[name] = body
                break
    return result


def clean_line(line: str) -> str:
    line = re.sub(r"^\s*[-*+]\s+", "", line.strip())
    line = re.sub(r"^\s*\d+[.)]\s+", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)
    return re.sub(r"\s+", " ", line).strip()


def first_lines(text: str, limit: int = 3) -> list[str]:
    result: list[str] = []
    for raw in text.splitlines():
        line = clean_line(raw)
        if not line or line in {"---", "***"} or line.startswith("|"):
            continue
        result.append(line)
        if len(result) >= limit:
            break
    return result


def headline(text: str, fallback: str) -> str:
    """Keep the lead readable without turning the whole Today block into a title."""
    values = first_lines(text, 2)
    return " · ".join(values)[:220] if values else fallback


def load_ai_activity(raw_root: Path, day: str) -> dict:
    path = raw_root / day / "ai_activity.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def parse_daily(path: Path, output_dir: Path, raw_root: Path, demo: bool = False) -> DailyReport:
    text = read_text(path)
    sections = parse_sections(text)
    active = re.search(r"(?:活跃工作时长|活动时长（采样估算）)：([^\n]+)", text)
    day = path.stem
    screenshot_dir = raw_root / day / "screenshots"
    screenshot_count = len(list(screenshot_dir.glob("*.png"))) if screenshot_dir.is_dir() else 0
    return DailyReport(
        date=day,
        markdown_href=path.relative_to(output_dir).as_posix(),
        html_href=f"{day}.html",
        sections=sections,
        active_hours=active.group(1).strip() if active else "未统计",
        ai_activity=load_ai_activity(raw_root, day),
        screenshot_count=screenshot_count,
        demo=demo,
    )


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def inline(value: str) -> str:
    safe = esc(value)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', safe)
    return safe


TIMELINE_RE = re.compile(
    r"^(?P<time>[^｜]+)｜应用：(?P<app>[^｜]+)｜项目：(?P<project>[^｜]+)｜(?P<action>[^｜]+)｜时长：(?P<duration>[^｜]+)｜来源：(?P<source>.+)$"
)


def render_timeline_item(value: str) -> str | None:
    match = TIMELINE_RE.match(value.strip())
    if not match:
        return None
    return (
        '<li class="timeline-item">'
        f'<div class="timeline-top"><span class="timeline-time">{inline(match.group("time"))}</span>'
        f'<span class="timeline-duration">{inline(match.group("duration"))}</span></div>'
        f'<div class="timeline-main"><strong>{inline(match.group("app"))}</strong>'
        f'<span class="timeline-project">{inline(match.group("project"))}</span>'
        f'<span class="timeline-action">{inline(match.group("action"))}</span></div>'
        f'<div class="timeline-source">来源：{inline(match.group("source"))}</div>'
        '</li>'
    )


def render_list(lines: list[str], start: int) -> tuple[str, int]:
    """Render the small two-level Markdown lists used by the daily reports."""
    first_match = re.match(r"^(\s*)[-*+]\s+(.+)$", lines[start])
    if not first_match:
        return "", start
    base_indent = len(first_match.group(1).replace("\t", "    "))
    items: list[str] = []
    index = start
    while index < len(lines):
        match = re.match(r"^(\s*)[-*+]\s+(.+)$", lines[index])
        if not match:
            break
        indent = len(match.group(1).replace("\t", "    "))
        if indent < base_indent:
            break
        if indent > base_indent:
            break
        raw_item = match.group(2)
        timeline_item = render_timeline_item(raw_item)
        item = inline(raw_item)
        index += 1
        nested = ""
        if index < len(lines):
            next_match = re.match(r"^(\s*)[-*+]\s+(.+)$", lines[index])
            if next_match:
                next_indent = len(next_match.group(1).replace("\t", "    "))
                if next_indent > base_indent:
                    nested, index = render_list(lines, index)
        items.append(timeline_item or f"<li>{item}{nested}</li>")
    return "<ul>" + "".join(items) + "</ul>", index


def render_blocks(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        raw = lines[index].strip()
        if not raw:
            index += 1
            continue
        if raw.startswith("|"):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", cell) or not cell for cell in cells):
                    rows.append(cells)
                index += 1
            if rows:
                head, *body = rows
                table = ["<table><thead><tr>"]
                table.extend(f"<th>{inline(cell)}</th>" for cell in head)
                table.append("</tr></thead><tbody>")
                for row in body:
                    table.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
                table.append("</tbody></table>")
                output.append("".join(table))
            continue
        if re.match(r"^[-*+]\s+", raw):
            list_html, index = render_list(lines, index)
            output.append(list_html)
            continue
        if raw.startswith("### "):
            output.append(f"<h3>{inline(raw[4:])}</h3>")
            index += 1
            continue
        paragraph = [raw]
        index += 1
        while index < len(lines) and lines[index].strip() and not re.match(r"^\s*[-*+]\s+", lines[index]) and not lines[index].strip().startswith("|"):
            paragraph.append(lines[index].strip())
            index += 1
        output.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(output) or '<p class="muted">暂无内容。</p>'


def section_html(name: str, text: str) -> str:
    return f"""<section class="report-section" id="section-{name.lower()}">
  <div class="section-head"><h2>{esc(name)}</h2></div>
  <div class="section-body">{render_blocks(text)}</div>
</section>"""


def ai_sidebar(item: DailyReport) -> str:
    activity = item.ai_activity
    sessions = activity.get("sessions") if isinstance(activity, dict) else []
    sessions = sessions if isinstance(sessions, list) else []
    source_counts = activity.get("source_counts", {}) if isinstance(activity, dict) else {}
    source_text = " · ".join(f"{esc(str(key))} {esc(str(value))}" for key, value in source_counts.items()) or "暂无 AI 会话"
    rows = []
    for session in sessions[:12]:
        if not isinstance(session, dict):
            continue
        rows.append(
            f"""<div class="session-row"><div class="session-meta"><span>{esc(str(session.get('start', ''))[11:16])}–{esc(str(session.get('end', ''))[11:16])}</span><span class="source">{esc(str(session.get('source', '')))}</span></div><strong>{esc(str(session.get('project', '未标注项目')))}</strong><p>{esc(str(session.get('title', ''))[:150])}</p></div>"""
        )
    body = "".join(rows) or '<p class="muted">当天没有解析到 Claude Code / Codex 会话。</p>'
    return f"""<aside class="side-column">
  <section class="side-card"><div class="eyebrow">AI ACTIVITY</div><h2>{esc(str(activity.get('session_count', 0)))} 个会话</h2><p class="muted">{source_text}</p>{body}</section>
  <section class="side-card"><div class="eyebrow">SIGNALS</div><div class="signal-grid"><div><strong>{item.screenshot_count}</strong><span>screenshots</span></div><div><strong>{esc(item.active_hours)}</strong><span>active time</span></div></div></section>
</aside>"""


PAGE_CSS = """
:root{--paper:#faf9f5;--surface:#fff;--subtle:#f4f1ea;--ink:#141413;--muted:#5d5d57;--faint:#8b8a82;--line:#e8e6dc;--line-strong:#b0aea5;--accent:#d97757;--accent-dark:#b95d40;--display:"Inter Tight",-apple-system,BlinkMacSystemFont,"SF Pro Display","PingFang SC",sans-serif;--body:"Newsreader","Iowan Old Style",Georgia,"Times New Roman",serif;--ui:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif;--mono:"SFMono-Regular",Menlo,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:19px/1.82 var(--body);-webkit-font-smoothing:antialiased}a{color:inherit}.shell{width:min(1120px,calc(100% - 64px));margin:0 auto}.masthead{display:grid;grid-template-columns:1fr;align-items:end;padding:28px 0 0;border-bottom:1px solid var(--line)}.wordmark{font:600 30px/1 var(--display);letter-spacing:-.055em;text-decoration:none;padding-bottom:22px}.mast-meta{display:none}.nav{display:flex;gap:25px;padding:13px 0 14px;font:500 13px var(--display);color:var(--muted);white-space:nowrap}.nav a{text-decoration:none}.nav a:hover{color:var(--accent)}.date-label,.section-kicker{font:600 12px/1 var(--display);letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}.hero{display:flex;justify-content:center;align-items:center;padding:86px 0 82px;border-bottom:1px solid var(--line);text-align:center}.hero .date-label{display:none}.hero h1{margin:0;font:500 clamp(48px,8vw,86px)/1 var(--display);letter-spacing:-.07em}.daily-main>.main-column{max-width:800px}.main-column{min-width:0}.report-section{padding:58px 0;border-bottom:1px solid var(--line);scroll-margin-top:18px}.section-head{display:flex;align-items:baseline;margin-bottom:24px}.section-head h2{margin:0;font:600 30px/1.15 var(--display);letter-spacing:-.04em}.section-body{max-width:780px}.section-body p{margin:0 0 18px}.section-body ul{margin:0 0 18px;padding-left:27px}.section-body li{margin:8px 0}.section-body strong{font-family:var(--display);font-weight:650}.section-body code{font:13px var(--mono);background:var(--subtle);padding:2px 5px;border-radius:4px}.section-body table{width:100%;border-collapse:collapse;margin:12px 0 8px;font:15px/1.6 var(--ui)}.section-body th,.section-body td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line)}.section-body th{color:var(--muted);font-weight:600}.muted{color:var(--muted)}.latest{padding:74px 0 68px;border-bottom:1px solid var(--line)}.latest h1{max-width:860px;margin:18px 0 28px;font:500 clamp(34px,5vw,64px)/1.08 var(--body);letter-spacing:-.045em}.latest .next-box{max-width:760px;border-top:2px solid var(--accent);padding-top:18px}.next-box h2{font:600 13px var(--display);margin:0 0 10px;text-transform:uppercase;letter-spacing:.12em;color:var(--accent-dark)}.next-box ul{margin:0;padding-left:22px}.next-box li{margin:5px 0;font-size:17px}.history{padding:48px 0 80px}.history-row{display:grid;grid-template-columns:150px minmax(0,1fr);gap:28px;align-items:baseline;padding:18px 0;border-bottom:1px solid var(--line);text-decoration:none}.history-row:hover .history-summary{color:var(--accent-dark)}.history-date{font:13px var(--mono);color:var(--muted)}.history-meta{display:none}.history-summary{font-size:17px;transition:color .2s}
.timeline-item{list-style:none;margin:0 0 12px!important;padding:14px 16px;border:1px solid var(--line);background:rgba(255,255,255,.45)}.timeline-top{display:flex;justify-content:space-between;gap:16px;margin-bottom:5px;font:13px var(--mono);color:var(--muted)}.timeline-duration{color:var(--accent-dark)}.timeline-main{display:flex;flex-wrap:wrap;align-items:baseline;gap:9px 14px}.timeline-main strong{font:650 17px/1.3 var(--display)}.timeline-project{font:600 14px/1.3 var(--display);color:var(--accent-dark)}.timeline-action{flex-basis:100%;font-size:18px}.timeline-source{margin-top:8px;font:12px/1.4 var(--ui);color:var(--faint)}.demo-badge{display:inline-block;margin-left:10px;padding:4px 7px;border:1px solid var(--accent);color:var(--accent-dark);font:600 11px var(--mono);letter-spacing:.04em;vertical-align:middle}.hero-meta{margin-top:18px;font:13px var(--ui);color:var(--muted)}
@media(max-width:800px){.shell{width:calc(100% - 40px)}.masthead{padding-top:22px}.wordmark{font-size:26px}.hero{padding:60px 0}.hero h1{font-size:54px}.report-section{padding:42px 0}.section-head h2{font-size:26px}.latest{padding:56px 0}.history-row{display:block}.history-date{display:block;margin-bottom:5px}}
"""


def render_daily_page(item: DailyReport) -> str:
    present = [name for name in SECTION_ORDER if item.sections.get(name)]
    nav = "".join(f'<a href="#section-{name.lower()}">{esc(name)}</a>' for name in present)
    sections = "\n".join(section_html(name, item.sections[name]) for name in present)
    badge = '<span class="demo-badge">DEMO · 示例数据</span>' if item.demo else ''
    title_suffix = ' · Demo' if item.demo else ''
    hero_meta = '' if item.demo else f'<div class="hero-meta">活动时长（采样估算）：{esc(item.active_hours)}</div>'
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>手手日报 · {esc(item.date)}{title_suffix}</title><style>{PAGE_CSS}</style></head><body><div class="shell">
<header class="masthead"><a class="wordmark" href="index.html">手手日报{badge}</a><nav class="nav"><a href="index.html">Index</a>{nav}</nav></header>
<main class="daily-main"><section class="hero"><div><h1>{esc(item.date)}</h1>{hero_meta}</div></section>
<div class="main-column">{sections}</div></main>
</div></body></html>"""


def render_index(daily: list[DailyReport], generated_at: str, demo: bool = False) -> str:
    latest = daily[0] if daily else None
    latest_next = first_lines(latest.sections.get("Next", ""), 5) if latest else []
    next_html = "".join(f"<li>{inline(value)}</li>" for value in latest_next) or '<li class="muted">暂无下一步。</li>'
    history = []
    for item in daily:
        summary = headline(item.sections.get("Today", ""), "未生成概要。")
        history.append(f"""<a class="history-row" href="{esc(item.html_href)}"><span class="history-date">{esc(item.date)}</span><span class="history-summary">{inline(summary)}</span></a>""")
    history_html = "".join(history) or '<p class="muted">还没有日报。完成一次日报生成后，这里会自动出现。</p>'
    badge = '<span class="demo-badge">DEMO · 示例数据</span>' if demo else ''
    title_suffix = ' · Demo' if demo else ''
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>手手日报 · Index{title_suffix}</title><style>{PAGE_CSS}
.index-main{{padding:0 34px 30px}}.latest{{padding:74px 0 68px;border-bottom:1px solid var(--line)}}.latest h1{{max-width:850px;margin:0 0 42px;font:500 clamp(48px,8vw,86px)/1 var(--display);letter-spacing:-.07em}}.latest .next-box{{max-width:760px;border-top:2px solid var(--accent);padding-top:18px}}.next-box h2{{font:600 13px var(--ui);margin:0 0 10px;text-transform:uppercase;letter-spacing:.12em;color:var(--accent-dark)}}.next-box ul{{margin:0;padding-left:20px}}.next-box li{{margin:5px 0;font-size:17px}}.history{{padding:46px 0}}.history-row{{display:grid;grid-template-columns:150px minmax(0,1fr);gap:28px;align-items:baseline;padding:18px 0;border-bottom:1px solid var(--line);text-decoration:none}}.history-row:hover .history-summary{{color:var(--accent-dark)}}.history-date{{font:13px var(--mono);color:var(--muted)}}.history-meta{{display:none}}.history-summary{{font-size:17px;transition:color .2s}}@media(max-width:800px){{.index-main{{padding:0 20px 24px}}.latest{{padding:52px 0}}.latest h1{{font-size:54px}}.history-row{{display:block}}.history-date{{display:block;margin-bottom:5px}}}}
</style></head><body><div class="shell"><header class="masthead"><a class="wordmark" href="index.html">手手日报{badge}</a><nav class="nav"><a href="#latest">Latest</a><a href="#history">Archive</a></nav></header><main class="index-main"><section class="latest" id="latest"><h1>{esc(latest.date if latest else '—')}</h1><div class="next-box"><h2>Next</h2><ul>{next_html}</ul></div></section><section class="history" id="history"><div class="section-kicker">Archive</div>{history_html}</section></main></div></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obsidian-dir", type=Path, default=Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian/日志")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-dir", type=Path, default=Path.home() / "xiaohei-daily/raw")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--demo", action="store_true", help="mark generated pages as synthetic demonstration data")
    args = parser.parse_args()

    output_dir = args.obsidian_dir.expanduser().resolve()
    output_path = (args.output or output_dir / "index.html").expanduser().resolve()
    raw_root = args.raw_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    daily_paths = sorted((path for path in output_dir.glob("*.md") if DATE_RE.match(path.name)), key=lambda path: path.name, reverse=True)[: max(1, args.limit)]
    daily = [parse_daily(path, output_dir, raw_root, demo=args.demo) for path in daily_paths]
    for item in daily:
        (output_dir / item.html_href).write_text(render_daily_page(item), encoding="utf-8")
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    output_path.write_text(render_index(daily, generated_at, demo=args.demo), encoding="utf-8")
    print(f"dashboard written: {output_path}")
    print(f"daily pages written: {len(daily)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
