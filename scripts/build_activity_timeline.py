#!/usr/bin/env python3
"""Build a normalized, evidence-labeled activity timeline for one day.

This is deliberately a conservative bridge between raw local observations and
the report prompt. It never reads message bodies or browser history. It only
uses the frontmost app/window samples, normalized local AI-session metadata,
and screenshot timestamps already collected by the recorder.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


SAMPLE_INTERVAL_MINUTES = 5
MAX_SAMPLE_GAP_MINUTES = 12


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def iso_minute(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def duration_minutes(start: datetime, end: datetime) -> int:
    observed = max(0, int((end - start).total_seconds() // 60))
    return max(SAMPLE_INTERVAL_MINUTES, observed)


def activity_blocks(rows: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        timestamp = parse_time(row.get("ts"))
        if not timestamp or timestamp.date().isoformat() != target:
            continue
        parsed.append((timestamp, row))
    parsed.sort(key=lambda item: item[0])

    groups: list[list[tuple[datetime, dict[str, Any]]]] = []
    for timestamp, row in parsed:
        app = str(row.get("app") or "未知应用")
        if groups:
            previous_time, previous_row = groups[-1][-1]
            same_app = str(previous_row.get("app") or "未知应用") == app
            close_enough = (timestamp - previous_time) <= timedelta(minutes=MAX_SAMPLE_GAP_MINUTES)
            if same_app and close_enough:
                groups[-1].append((timestamp, row))
                continue
        groups.append([(timestamp, row)])

    result: list[dict[str, Any]] = []
    for group in groups:
        start, first = group[0]
        last, last_row = group[-1]
        app = str(first.get("app") or "未知应用")
        titles = [str(item.get("title") or "").strip() for _, item in group]
        titles = [title for title in titles if title and title != "[excluded]"]
        title = max(titles, key=len) if titles else ""
        action = f"{app} 处于前台"
        if title:
            action = f"查看：{title[:180]}"
        result.append(
            {
                "start": iso_minute(start),
                "end": iso_minute(last),
                "duration_minutes": duration_minutes(start, last),
                "app": app,
                "project": "",
                "action": action,
                "source": "窗口活动记录",
                "evidence": ["frontmost_app", "window_title"] if title else ["frontmost_app"],
                "confidence": "medium" if title else "low",
                "sample_count": len(group),
            }
        )
    return result


def session_blocks(activity: dict[str, Any], target: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    sessions = activity.get("sessions", []) if isinstance(activity, dict) else []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        start = parse_time(session.get("start"))
        end = parse_time(session.get("end"))
        if not start or not end or start.date().isoformat() != target:
            continue
        source = str(session.get("source") or "AI 会话")
        project = str(session.get("project") or "")
        if project.lower().startswith("scratch-"):
            continue
        title = " ".join(str(session.get("title") or "").split())
        if not title:
            continue
        result.append(
            {
                "start": iso_minute(start),
                "end": iso_minute(end),
                "duration_minutes": duration_minutes(start, end),
                "app": source,
                "project": project,
                "action": title[:220],
                "source": f"{source} 本地会话",
                "evidence": ["local_session"],
                "confidence": "high",
                "kind": session.get("kind", "conversation"),
                "message_count": session.get("message_count", 0),
            }
        )
    return result


def screenshot_summary(path: Path, target: str) -> dict[str, Any]:
    evidence = read_json(path, {})
    selected = evidence.get("selected_images", []) if isinstance(evidence, dict) else []
    selected = selected if isinstance(selected, list) else []
    times = [str(item.get("time")) for item in selected if isinstance(item, dict) and item.get("time")]
    return {
        "date": target,
        "total_count": evidence.get("total_count", 0) if isinstance(evidence, dict) else 0,
        "selected_count": len(times),
        "selected_times": times,
        "source": "截图证据",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=Path.home() / "xiaohei-daily")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    raw_day = args.root.expanduser().resolve() / "raw" / args.date
    rows: list[dict[str, Any]] = []
    activity_path = raw_day / "activity.jsonl"
    try:
        with activity_path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        pass

    ai_activity = read_json(raw_day / "ai_activity.json", {})
    payload = {
        "date": args.date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        "observed_activity": activity_blocks(rows, args.date),
        "ai_sessions": session_blocks(ai_activity, args.date),
        "screenshots": screenshot_summary(raw_day / "screenshot_evidence.json", args.date),
    }
    payload["timeline"] = sorted(
        payload["observed_activity"] + payload["ai_sessions"],
        key=lambda item: (item.get("start", ""), item.get("source", "")),
    )
    output = args.output or raw_day / "activity_timeline.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"activity timeline written: {output}")
    print(f"observed blocks: {len(payload['observed_activity'])}")
    print(f"AI sessions: {len(payload['ai_sessions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
