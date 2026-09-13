#!/usr/bin/env python3
"""Minimal work-activity recorder: logs frontmost app/window title, and
periodically takes a screenshot. Meant to be run every few minutes by launchd.

Config lives in config.json next to this script:
  {
    "exclude_apps": ["1Password", "Keychain Access"],
    "screenshot_every_n_runs": 3
  }
"""
import json
import os
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
LOG_ROOT = os.path.join(ROOT, "raw")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

DEFAULT_CONFIG = {
    "exclude_apps": ["1Password", "Keychain Access", "System Preferences", "System Settings"],
    "screenshot_every_n_runs": 3,
    "idle_skip_seconds": 240,
}

FRONTMOST_SCRIPT = '''
tell application "System Events"
    set frontProc to first application process whose frontmost is true
    set frontApp to name of frontProc
    try
        set winTitle to name of front window of frontProc
    on error
        set winTitle to ""
    end try
end tell
return frontApp & "|||" & winTitle
'''


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG


def get_idle_seconds():
    """Seconds since the last mouse/keyboard event, via IOKit HIDIdleTime
    (nanoseconds). Used to skip logging during macOS "dark wake" cycles,
    where the machine briefly wakes for background maintenance while the
    lid is closed and nobody is actually using it — without this check
    those wakes get logged as if the last-known frontmost app were active,
    and screencapture just grabs the same frozen/lock screen repeatedly.
    """
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True, text=True, timeout=5,
        )
        for line in out.stdout.splitlines():
            if "HIDIdleTime" in line:
                ns = int(line.split("=")[-1].strip())
                return ns / 1_000_000_000
    except Exception:
        pass
    return 0.0


def get_frontmost():
    try:
        out = subprocess.run(
            ["osascript", "-e", FRONTMOST_SCRIPT],
            capture_output=True, text=True, timeout=5,
        )
        app, _, title = out.stdout.strip().partition("|||")
        return app or "unknown", title
    except Exception:
        return "unknown", ""


def main():
    config = load_config()

    if get_idle_seconds() >= config["idle_skip_seconds"]:
        # Nobody has touched the machine recently (likely a dark-wake tick
        # while the lid is closed) — skip this run entirely.
        return

    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    day_dir = os.path.join(LOG_ROOT, day)
    os.makedirs(day_dir, exist_ok=True)

    app, title = get_frontmost()
    excluded = app in config["exclude_apps"]
    entry = {
        "ts": now.isoformat(timespec="seconds"),
        "app": app,
        "title": "[excluded]" if excluded else title,
    }
    with open(os.path.join(day_dir, "activity.jsonl"), "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    tick_file = os.path.join(day_dir, ".tick")
    tick = 0
    if os.path.exists(tick_file):
        try:
            tick = int(open(tick_file).read().strip() or 0)
        except ValueError:
            tick = 0
    tick += 1
    with open(tick_file, "w") as f:
        f.write(str(tick))

    if not excluded and tick % config["screenshot_every_n_runs"] == 0:
        shot_dir = os.path.join(day_dir, "screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        shot_path = os.path.join(shot_dir, now.strftime("%H%M%S") + ".png")
        subprocess.run(["screencapture", "-x", shot_path], timeout=10)


if __name__ == "__main__":
    main()
