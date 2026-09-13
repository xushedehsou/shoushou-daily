#!/usr/bin/env python3
"""Snapshot of Apple Reminders for a given date, written as JSON:
  - completed_today: reminders whose completion date falls on that day
  - created_today: reminders whose creation date falls on that day (open or done)
  - currently_open: all reminders not yet completed, AS OF WHEN THIS SCRIPT RUNS
    (not a historical point-in-time snapshot — Reminders doesn't keep that
    history. Fine when run the next morning; can drift if run days late
    during a sleep-catch-up, since items may have been completed/deleted
    since the target date).

Uses EventKit (via PyObjC) rather than AppleScript: Reminders.app's
AppleScript "whose completed is false" query is reliably slow/hangs
(observed firsthand — a known Reminders.app scripting bridge issue),
while "whose completed is true" and date-range filters are fine.
EventKit is the framework Reminders.app itself is built on and has none
of that flakiness.

Usage: python3 reminders_snapshot.py YYYY-MM-DD > out.json
"""
import sys
import json
import time
from datetime import datetime

import EventKit
import Foundation


def wait_for(flag_dict, timeout_s=15):
    deadline = time.time() + timeout_s
    while not flag_dict["done"] and time.time() < deadline:
        Foundation.NSRunLoop.currentRunLoop().runMode_beforeDate_(
            Foundation.NSDefaultRunLoopMode,
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1),
        )
    return flag_dict["done"]


def request_access(store):
    result = {"done": False, "ok": False}

    def cb(ok, err):
        result["ok"] = ok
        result["done"] = True

    if hasattr(store, "requestFullAccessToRemindersWithCompletion_"):
        store.requestFullAccessToRemindersWithCompletion_(cb)
    else:
        store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeReminder, cb)

    wait_for(result)
    return result["ok"]


def fetch(store, predicate):
    result = {"done": False, "reminders": None}

    def cb(reminders):
        result["reminders"] = reminders
        result["done"] = True

    store.fetchRemindersMatchingPredicate_completion_(predicate, cb)
    wait_for(result)
    return list(result["reminders"] or [])


def ns_date_to_iso(ns_date):
    if ns_date is None:
        return None
    # NSDate -> Python datetime via timeIntervalSince1970
    ts = ns_date.timeIntervalSince1970()
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def due_str(reminder):
    comps = reminder.dueDateComponents()
    if comps is None:
        return None
    try:
        y, m, d = comps.year(), comps.month(), comps.day()
        if y == Foundation.NSDateComponentUndefined or not y:
            return None
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None


def main():
    if len(sys.argv) != 2:
        print("usage: reminders_snapshot.py YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)
    target_day = sys.argv[1]
    day_start = datetime.strptime(target_day, "%Y-%m-%d")
    day_end_ts = day_start.timestamp() + 86400

    store = EventKit.EKEventStore.alloc().init()
    if not request_access(store):
        print(json.dumps({"error": "reminders_access_denied"}))
        sys.exit(1)

    calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)

    ns_start = Foundation.NSDate.dateWithTimeIntervalSince1970_(day_start.timestamp())
    ns_end = Foundation.NSDate.dateWithTimeIntervalSince1970_(day_end_ts)

    completed_pred = store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(
        ns_start, ns_end, calendars
    )
    completed_today = fetch(store, completed_pred)

    incomplete_pred = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None, None, calendars
    )
    currently_open = fetch(store, incomplete_pred)

    # created_today needs scanning both buckets plus the rest of completed
    # history isn't needed — creationDate is on EKCalendarItem, available on
    # anything we already fetched, plus we separately fetch ALL completed
    # (unbounded) only if needed... to keep it cheap, just check creationDate
    # on the two sets we already have (open + completed-today); items created
    # today AND completed on some other day (rare) are missed, acceptable.
    created_today = []
    for r in list(currently_open) + list(completed_today):
        cd = r.creationDate()
        if cd is None:
            continue
        cd_dt = datetime.fromtimestamp(cd.timeIntervalSince1970())
        if target_day == cd_dt.strftime("%Y-%m-%d"):
            created_today.append(r)

    def summarize(r):
        return {
            "title": r.title(),
            "list": r.calendar().title() if r.calendar() else None,
            "due": due_str(r),
            "completed": bool(r.isCompleted()),
        }

    out = {
        "date": target_day,
        "completed_today": [summarize(r) for r in completed_today],
        "created_today": [summarize(r) for r in created_today],
        "currently_open": [summarize(r) for r in currently_open],
        "note": "currently_open 是脚本运行时刻的未完成事项快照，不是 date 那天的历史状态；如果报告是隔了好几天才补跑的，可能和 date 当天实际情况有出入。",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
