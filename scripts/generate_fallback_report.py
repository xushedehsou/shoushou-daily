#!/usr/bin/env python3
"""Generate a conservative six-section report when model analysis is unavailable."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def clean(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit] + ("…" if len(value) > limit else "")


def formalize(value: str, limit: int = 180) -> str:
    """Make raw conversational titles minimally report-like without inventing work."""
    value = clean(value, limit=400)
    value = re.sub(r"^[-#*\s]+", "", value)
    value = re.sub(r"<details>.*?</details>", "", value)
    value = re.sub(r"^(?:首先啊?|首先，我|现在我们|我们现在|咱们现在)\s*", "", value)
    replacements = (
        (r"^为啥(?:还不行)?[，,:：]?\s*", "排查"),
        (r"^看一下[“\"]?(.+?)[”\"]?(?:，|。|$)", r"检查\1"),
        (r"^帮我", "处理"),
        (r"^你可以", "评估"),
        (r"^我想", "讨论"),
        (r"^试一下", "测试"),
        (r"^生成一下", "生成"),
        (r"^现在来", "开展"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    value = value.replace("对不对", "").replace("好吧", "")
    value = re.sub(r"[，,。！？!?]+$", "", value).strip()
    return clean(value, limit=limit)


def summarize_activity(value: str, limit: int = 180) -> str:
    """Use conservative, evidence-preserving summaries for common raw prompts."""
    raw = clean(value, limit=500)
    lowered = raw.lower()
    patterns = (
        (("日报",), "排查日报采集、生成与定时运行链路"),
        (("日报",), "排查日报采集、生成与定时运行链路"),
        (("初步的剪辑",), "整理视频粗剪素材、镜头顺序与配音使用方案"),
        (("新建一个codex文件",), "整理 Codex 工作区并确认敏感文件边界"),
        (("查找游戏玩法头脑风暴资源",), "检索游戏玩法头脑风暴资源和可复用方法"),
        (("游戏玩法设计", "头脑风暴"), "检索游戏玩法头脑风暴资源和可复用方法"),
        (("粗剪", "废片"), "整理视频粗剪素材、镜头取舍与废片归档"),
        (("红的标签",), "标记并归档视频粗剪中的备用废片"),
        (("初步剪辑的要求",), "明确视频粗剪的镜头顺序、配音与取舍规则"),
        (("开源", "导演工作台"), "评估开源导演工作台与本地 CLI 工作流的替代方案"),
        (("封面图", "竖版"), "规划视频封面与竖版、横版版式适配"),
        (("贴纸", "花字"), "筛选视频贴纸与花字素材的使用范围"),
        (("音效", "背景音"), "整理视频背景音乐与音效素材"),
        (("参考图方案",), "设计镜头参考图方案，供后续视频生成"),
        (("独立立绘",), "拆分角色立绘并评估动作与人物识别度"),
        (("威武的姿势",), "整理角色立绘的动作与人物气质方向"),
        (("总结该项目进度",), "整理角色立绘分类与提示词结构"),
        (("github之类的平台",), "检索人物立绘提示词项目"),
        (("头像包",), "评估角色头像资源的参考价值"),
        (("人物立绘不仅",), "建立人物、界面与玩法统一的视觉套装方向"),
        (("发呆", "软件"), "调研持续观看型动画软件的案例与实现方向"),
        (("镜头8",), "设计人物讲话与信息动画的拆分方案"),
        (("政策说明", "英文字体"), "设计政策说明信息动画的中英文版式"),
        (("人物", "镜头"), "设计人物入场、坐下与对话动作"),
        (("镜头延长",), "规划镜头一延长段与镜头二的连续性衔接"),
        (("小丑牌", "像素"), "讨论策略游戏构筑玩法与像素视觉的结合方式"),
        (("thronefall", "美术", "风格"), "评估 Thronefall 式视觉风格与 AI 美术制作的可行性"),
        (("steam", "源码", "贴纸", "素材"), "评估已发布游戏的素材提取与源码恢复边界"),
        (("地图几何距离", "地形", "人物"), "评估地图几何距离、地形形状与人物位置效果"),
        (("地图", "阵型", "资源结算"), "整理地图、阵型与资源结算顺序的简化验证方案"),
        (("数值模型", "数值", "游戏设计"), "检查游戏设计进度并优化数值模型"),
        (("名梗",), "探索角色组合和效果触发条件"),
        (("rpg", "军事逻辑"), "重构角色养成、军事逻辑与构筑核心玩法"),
        (("最基本的玩法", "美术", "素材"), "收束工作顺序，优先验证基础玩法后再扩展美术与素材"),
        (("网页", "游戏玩法", "存进游戏设计"), "将网页改动与游戏玩法讨论内容归档至游戏设计"),
        (("可玩性", "游戏玩法"), "审查当前游戏玩法的可玩性与进度"),
    )
    for terms, result in patterns:
        if all(term in lowered for term in terms):
            return result
    return formalize(raw, limit=limit)


def legacy_hours(report_file: Path) -> str | None:
    try:
        text = report_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r"(?:活跃工作时长|活动时长（采样估算）)：([^\n]+)", text)
    if not match:
        return None
    value = match.group(1).strip()
    return None if value.startswith("数据不足") else value


def canonical_project(project: str, title: str) -> str:
    """Merge aliases that are work lines inside the same game project."""
    text = f"{project} {title}".lower()
    if any(term in text for term in ("镜头一", "镜头1", "镜头8", "政策说明", "花字")):
        return "视频项目"
    if any(term in text for term in ("人物立绘", "角色立绘", "武将立绘", "独立立绘")):
        return "角色视觉项目"
    if any(term in text for term in ("发呆", "持续观看", "apple watch", "动画软件")):
        return "桌面视觉项目"
    if any(term in text for term in ("日报", "日报未更新", "日报生成", "日报采集")):
        return "日报自动化"
    if project.lower().endswith("-codex"):
        return "Codex 工作区"
    game_terms = (
        "游戏设计", "游戏玩法", "玩法合并", "地图", "阵型", "武将",
        "thronefall", "游戏美术", "游戏制作", "小丑牌", "幸运房东", "头脑风暴",
    )
    if any(term in text for term in game_terms):
        return "某款策略游戏原型"
    if project.lower() in {"claude", "codex", "tmp", "new-chat-8", "mu"}:
        return "未标注项目"
    if project.lower().startswith("https-github-com-"):
        return "其他工作"
    return project or "未标注项目"


def workstream(title: str) -> str:
    text = title.lower()
    if any(term in text for term in ("像素", "视觉", "美术", "thronefall", "人物", "界面", "风格", "ai 制作")):
        return "视觉美术"
    if any(term in text for term in ("拆", "源码", "素材", "工具", "文件夹", "steam")):
        return "工具与资料"
    return "玩法"


def ticktick_items(ticktick_file: Path, reminders_file: Path) -> tuple[list[str], list[str], list[str]]:
    ticktick = load_json(ticktick_file, {})
    reminders = load_json(reminders_file, {})
    created = ticktick.get("created_today", []) if isinstance(ticktick, dict) else []
    completed = ticktick.get("completed_today", []) if isinstance(ticktick, dict) else []
    open_items = reminders.get("currently_open", []) if isinstance(reminders, dict) else []
    def values(items):
        result = []
        for item in items:
            raw_title = item.get("title", "") if isinstance(item, dict) else item
            title = formalize(raw_title)
            action_words = ("完成", "处理", "整理", "搜索", "研究", "设计", "生成", "制作", "检查", "修复", "补充", "下载", "安装", "写", "做", "看", "测试", "配置", "更新", "排查", "记录", "跟进")
            likely_task = len(title) <= 140 and any(word in title for word in action_words)
            if title and likely_task:
                result.append(title)
        return result

    return values(created), values(completed), values(open_items)


def next_items(ticktick_file: Path, reminders_file: Path) -> list[str]:
    created, _, open_items = ticktick_items(ticktick_file, reminders_file)
    result = []
    for title in created + open_items:
        if title not in result:
            result.append(title)
    return result[:5]


def format_duration(minutes: object) -> str:
    try:
        value = max(1, int(minutes))
    except (TypeError, ValueError):
        return "时长不明"
    hours, remainder = divmod(value, 60)
    if hours and remainder:
        return f"{hours} 小时 {remainder} 分钟"
    if hours:
        return f"{hours} 小时"
    return f"{remainder} 分钟"


def timeline_lines(timeline_file: Path) -> list[str]:
    payload = load_json(timeline_file, {})
    items = payload.get("timeline", []) if isinstance(payload, dict) else []
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = clean(item.get("start", ""))[11:16]
        end = clean(item.get("end", ""))[11:16]
        app = clean(item.get("app", "未知应用"), 40)
        raw_project = clean(item.get("project", "生活与浏览"), 80)
        action = clean(item.get("action", "记录到活动"), 150)
        source = clean(item.get("source", "窗口活动记录"), 40)
        if source.endswith("本地会话"):
            action = summarize_activity(action, 150)
        project = canonical_project(raw_project, action) if raw_project else "生活与浏览"
        result.append(
            f"- {start}–{end}｜应用：{app}｜项目：{project}｜{action}｜时长：{format_duration(item.get('duration_minutes'))}｜来源：{source}"
        )
        if len(result) >= 12:
            break
    return result


def estimate_hours(activity_file: Path) -> str:
    rows = []
    try:
        with activity_file.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return "数据不足，无法估算"
    timestamps = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("ts")
        if isinstance(value, str):
            timestamps.append(value)
    if len(timestamps) < 2:
        return "数据不足，无法估算"
    # The recorder samples every few minutes; use the observed span as a
    # conservative fallback, capped to avoid turning a sparse day into 24h.
    from datetime import datetime
    try:
        start = datetime.fromisoformat(min(timestamps))
        end = datetime.fromisoformat(max(timestamps))
        hours = max(0.0, min((end - start).total_seconds() / 3600, 12.0))
        return f"{hours:.1f} 小时"
    except ValueError:
        return "数据不足，无法估算"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: generate_fallback_report.py YYYY-MM-DD REPORT_FILE", file=sys.stderr)
        return 2
    day = sys.argv[1]
    report_file = Path(sys.argv[2])
    root = Path.home() / "xiaohei-daily"
    raw_day = root / "raw" / day
    activity = load_json(raw_day / "ai_activity.json", {})
    sessions = activity.get("sessions", []) if isinstance(activity, dict) else []
    sessions = [s for s in sessions if isinstance(s, dict)]
    sessions = [
        s for s in sessions
        if not clean(s.get("project", "")).lower().startswith("scratch-")
    ]
    sessions.sort(key=lambda s: (str(s.get("start", "")), str(s.get("source", ""))))

    by_project: dict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        raw_title = clean(session.get("title", ""), 400)
        project = canonical_project(clean(session.get("project", "未标注项目"), 80), raw_title)
        if project in {"未标注项目", "其他工作"}:
            continue
        if project.lower().startswith("scratch-"):
            continue
        by_project[project].append(session)

    today_lines = []
    for project, items in list(by_project.items())[:6]:
        today_lines.append(f"- **{project}**")
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in items:
            title = summarize_activity(item.get("title", "")) or "完成项目相关工作"
            if title not in grouped[workstream(title)]:
                grouped[workstream(title)].append(title)
        for stream in ("玩法", "视觉美术", "工具与资料"):
            if grouped.get(stream):
                today_lines.append(f"  - **{stream}**")
                today_lines.extend(f"    - {title}" for title in grouped[stream][:3])
    if not today_lines:
        today_lines = ["- 无明确项目记录；可查看 Timeline 中的窗口与截图记录。"]

    timeline = timeline_lines(raw_day / "activity_timeline.json")
    if not timeline:
        for item in sessions[:12]:
            start = clean(item.get("start", ""))[11:16]
            end = clean(item.get("end", ""))[11:16]
            project = canonical_project(clean(item.get("project", "未标注项目"), 60), clean(item.get("title", ""), 300))
            title = summarize_activity(item.get("title", "记录了会话"), 130)
            timeline.append(f"- {start}–{end}｜应用：{item.get('source', 'AI 会话')}｜项目：{project}｜{title}｜时长：时长不明｜来源：本地会话")
    if not timeline:
        timeline = ["- 无明确 AI 会话时间线。"]

    projects = []
    for project, items in list(by_project.items())[:8]:
        unique_titles = []
        for item in items:
            title = summarize_activity(item.get("title", ""), 90)
            if title and title not in unique_titles:
                unique_titles.append(title)
        titles = "；".join(unique_titles[:2])
        projects.append(f"- **{project}**｜{titles or '记录了项目相关工作'}")
    if not projects:
        projects = ["- 无明确持续项目记录。"]

    created, completed, _ = ticktick_items(raw_day / "ticktick.json", raw_day / "reminders.json")
    next_values = next_items(raw_day / "ticktick.json", raw_day / "reminders.json")
    next_section = [f"- {value}" for value in next_values] or ["- 无明确下一步记录。"]
    if completed:
        today_lines.append(f"- **任务管理**：完成 {formalize('、'.join(completed), 120)}")
    hours = legacy_hours(report_file) or estimate_hours(raw_day / "activity.jsonl")
    if hours.startswith(("约", "大约", "估算为")):
        hours = re.sub(r"^(约|大约|估算为)\s*", "", hours)

    report = "\n".join([
        "## Today", *today_lines, "",
        "## Timeline", *timeline, "",
        "## Projects", *projects, "",
        "## Ideas", "- 无明确记录。", "",
        "## Questions", "- 无明确记录。", "",
        "## Next", *next_section, "",
        f"活动时长（采样估算）：{hours}", "",
    ])
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(report, encoding="utf-8")
    print(f"fallback report written: {report_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
