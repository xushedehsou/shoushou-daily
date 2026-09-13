#!/usr/bin/env python3
"""Select representative screenshots and write a local evidence manifest.

The report job attaches the selected images to Codex with ``codex exec -i``.
The full file list is kept in the manifest so the report model can distinguish
what was sampled from how many screenshots existed that day.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


MAX_ATTACHMENTS = 12


def timestamp_from_name(path: Path) -> str:
    value = path.stem
    if len(value) == 6 and value.isdigit():
        return f"{value[:2]}:{value[2:4]}:{value[4:]}"
    return value


def choose(paths: list[Path], limit: int = MAX_ATTACHMENTS) -> list[Path]:
    if len(paths) <= limit:
        return paths
    if limit <= 1:
        return [paths[0]]
    indexes = {
        round(index * (len(paths) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [path for index, path in enumerate(paths) if index in indexes]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", help="YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=Path.home() / "xiaohei-daily")
    parser.add_argument("--paths-only", action="store_true")
    args = parser.parse_args()

    screenshot_dir = args.root.expanduser() / "raw" / args.day / "screenshots"
    paths = sorted(screenshot_dir.glob("*.png")) if screenshot_dir.is_dir() else []
    selected = choose(paths)
    manifest = {
        "date": args.day,
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        "total_count": len(paths),
        "selected_count": len(selected),
        "selection": "均匀抽取全天截图，最多 12 张作为 Codex 图像附件",
        "all_images": [
            {"path": str(path), "time": timestamp_from_name(path)} for path in paths
        ],
        "selected_images": [
            {"path": str(path), "time": timestamp_from_name(path)} for path in selected
        ],
    }
    output = args.root.expanduser() / "raw" / args.day / "screenshot_evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.paths_only:
        for path in selected:
            print(path)
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
