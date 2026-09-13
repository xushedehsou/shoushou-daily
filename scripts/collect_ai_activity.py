#!/usr/bin/env python3
"""Collect local Claude Code and Codex sessions for one calendar day.

The collector deliberately writes a normalized, local-only snapshot instead
of exposing the original transcript files to the report renderer.  The
snapshot keeps enough context for the scheduled report to analyze the work,
while the HTML surface only shows titles, projects, times, and counts.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


LOCAL_TZ = datetime.now().astimezone().tzinfo
MAX_CONTEXT = 2600
MAX_MESSAGE = 1200
IMAGE_TERMS = (
    "生图", "绘画", "图像", "图片", "参考图", "立绘", "人物画", "封面图",
    "视觉", "风格板", "提示词", "即梦", "dreamina", "seedance", "comfyui",
    "stable diffusion", "image_gen", "imagegen", "character portrait",
)


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def local_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ)


def record_timestamp(record: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "cacheBreaker"):
        parsed = parse_timestamp(record.get(key))
        if parsed:
            return local_time(parsed)
    payload = record.get("payload")
    if isinstance(payload, dict):
        for key in ("timestamp", "cacheBreaker"):
            parsed = parse_timestamp(payload.get(key))
            if parsed:
                return local_time(parsed)
    message = record.get("message")
    if isinstance(message, dict):
        for key in ("timestamp", "cacheBreaker"):
            parsed = parse_timestamp(message.get(key))
            if parsed:
                return local_time(parsed)
    return None


def text_from_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    chunks: list[str] = []
    for item in value:
        if isinstance(item, str):
            chunks.append(item)
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
            elif isinstance(item.get("content"), str):
                chunks.append(item["content"])
    return " ".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()


def clean_message(text: str) -> str:
    compact = " ".join(text.replace("\x00", " ").split())
    # Codex rollouts can repeat the desktop envelope (plugin lists, app
    # context, and environment metadata) as a user record. It is not work
    # content and would otherwise crowd the useful conversation out.
    noise_prefixes = (
        "<recommended_plugins>",
        "<environment_context>",
        "<app-context>",
        "<skills_instructions>",
        "# AGENTS.md instructions",
        "读取 /",
        "这是已授权的定时自动化任务",
        "Files mentioned by the user",
        "# Files mentioned by the user",
        "<system-reminder>",
        "Failed to authenticate.",
        "Invalid or expired user code",
        "你是影策的画布执行 Agent",
        "ERROR:",
        "warning:",
    )
    if compact.startswith(noise_prefixes):
        return ""
    return compact[:MAX_MESSAGE]


def project_name(cwd: str, fallback: str = "") -> str:
    if cwd:
        path = Path(cwd).expanduser()
        if path.name:
            return path.name
    value = fallback
    if value.startswith("-Users-"):
        parts = value.split("-", 3)
        value = parts[3] if len(parts) == 4 else value
    if value.startswith("-private-tmp-"):
        value = value[len("-private-tmp-") :]
    value = value.replace("-", "/")
    return value.rsplit("/", 1)[-1] or fallback or "未标注项目"


def session_kind(project: str, context: str) -> str:
    haystack = f"{project} {context}".casefold()
    return "image" if any(term.casefold() in haystack for term in IMAGE_TERMS) else "conversation"


def make_session(
    source: str,
    session_id: str,
    cwd: str,
    fallback_project: str,
    events: list[tuple[datetime, str, str]],
    target: date,
) -> dict[str, Any] | None:
    day_events = [event for event in events if event[0].date() == target]
    if not day_events:
        return None
    day_events.sort(key=lambda event: event[0])
    context_lines: list[str] = []
    user_messages: list[str] = []
    selected_events = [event for event in day_events if event[1] == "user"][:3]
    selected_events += [event for event in day_events if event[1] == "assistant"][-2:]
    selected_events.sort(key=lambda event: event[0])
    for timestamp, role, text in selected_events:
        text = clean_message(text)
        if not text:
            continue
        if role == "user":
            user_messages.append(text)
        context_lines.append(f"{role}: {text}")

    if not user_messages:
        return None

    context = "\n".join(context_lines)
    if len(context) > MAX_CONTEXT:
        context = context[:MAX_CONTEXT].rstrip() + "\n...[截断]"
    title = (user_messages[0] if user_messages else (context_lines[0] if context_lines else ""))[:180]
    project = project_name(cwd, fallback_project)
    return {
        "id": session_id,
        "source": source,
        "project": project,
        "kind": session_kind(project, context),
        "cwd": cwd,
        "start": day_events[0][0].isoformat(timespec="minutes"),
        "end": day_events[-1][0].isoformat(timespec="minutes"),
        "title": title,
        "message_count": len(day_events),
        "context": context,
    }


def parse_claude_file(path: Path, target: date) -> dict[str, Any] | None:
    events: list[tuple[datetime, str, str]] = []
    cwd = ""
    try:
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                cwd = cwd or str(record.get("cwd") or "")
                timestamp = record_timestamp(record)
                if not timestamp or record.get("isSidechain"):
                    continue
                kind = record.get("type")
                if kind not in {"user", "human", "assistant"}:
                    continue
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                role = "user" if kind in {"user", "human"} else "assistant"
                text = text_from_content(message.get("content"))
                if text:
                    events.append((timestamp, role, text))
    except OSError:
        return None
    return make_session("Claude Code", path.stem, cwd, path.parent.name, events, target)


def parse_codex_file(path: Path, target: date) -> dict[str, Any] | None:
    events: list[tuple[datetime, str, str]] = []
    cwd = ""
    try:
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                payload = record.get("payload")
                if record.get("type") == "session_meta" and isinstance(payload, dict):
                    cwd = cwd or str(payload.get("cwd") or "")
                if record.get("type") != "response_item" or not isinstance(payload, dict):
                    continue
                if payload.get("type") != "message" or payload.get("role") not in {"user", "assistant"}:
                    continue
                timestamp = record_timestamp(record)
                if not timestamp:
                    continue
                text = text_from_content(payload.get("content"))
                if text:
                    events.append((timestamp, str(payload["role"]), text))
    except OSError:
        return None
    return make_session("Codex", path.stem, cwd, "Codex", events, target)


def collect(target: date) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    claude_root = Path(os.path.expanduser("~/.claude/projects"))
    codex_root = Path(os.path.expanduser("~/.codex/sessions"))

    if claude_root.is_dir():
        for path in claude_root.rglob("*.jsonl"):
            if "subagent" in str(path):
                continue
            session = parse_claude_file(path, target)
            if session:
                sessions.append(session)
    if codex_root.is_dir():
        for path in codex_root.rglob("rollout-*.jsonl"):
            session = parse_codex_file(path, target)
            if session:
                sessions.append(session)

    sessions.sort(key=lambda item: (item["start"], item["source"], item["id"]))
    source_counts: dict[str, int] = {}
    for session in sessions:
        source_counts[session["source"]] = source_counts.get(session["source"], 0) + 1
    return {
        "date": target.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        "session_count": len(sessions),
        "source_counts": source_counts,
        "sessions": sessions,
    }


def main() -> int:
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    json.dump(collect(target), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
