#!/usr/bin/env python3
"""Read TickTick tasks created or completed on a day from the local database.

The database is opened read-only and no TickTick credentials are used.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


CORE_DATA_EPOCH_OFFSET = 978307200
DEFAULT_DB = (
    Path.home()
    / "Library/Group Containers/75TY9UT8AY.com.TickTick.task.mac"
    / "OSXCoreDataObjC.storedata"
)


def fail(target_day: str, code: str, detail: str | None = None) -> None:
    payload = {"date": target_day, "error": code}
    if detail:
        payload["detail"] = detail
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(1)


def local_iso(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value + CORE_DATA_EPOCH_OFFSET).isoformat(timespec="seconds")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ticktick_snapshot.py YYYY-MM-DD", file=sys.stderr)
        return 1
    target_day = sys.argv[1]
    try:
        day_start = datetime.strptime(target_day, "%Y-%m-%d")
    except ValueError:
        fail(target_day, "invalid_date")

    start_cf = day_start.timestamp() - CORE_DATA_EPOCH_OFFSET
    end_cf = start_cf + 86400
    db_path = Path(os.environ.get("TICKTICK_DB_PATH", str(DEFAULT_DB))).expanduser()
    if not db_path.is_file():
        fail(target_day, "ticktick_database_not_found", str(db_path))

    connection = None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {"ZTTTASK", "ZTTPROJECT"}.issubset(tables):
            fail(target_day, "unsupported_ticktick_database_schema")
        rows = connection.execute(
            """
            SELECT t.ZTITLE AS title,
                   p.ZNAME AS project,
                   t.ZCREATIONDATE AS created_at,
                   t.ZCOMPLETIONDATE AS completed_at,
                   t.ZSTATUS AS status
            FROM ZTTTASK AS t
            LEFT JOIN ZTTPROJECT AS p ON p.Z_PK = t.ZPROJECT
            WHERE t.ZDELETIONSTATUS = 0
              AND (
                    (t.ZCOMPLETIONDATE >= ? AND t.ZCOMPLETIONDATE < ?)
                    OR
                    (t.ZCREATIONDATE >= ? AND t.ZCREATIONDATE < ?)
                  )
            ORDER BY COALESCE(t.ZCOMPLETIONDATE, t.ZCREATIONDATE) ASC
            """,
            (start_cf, end_cf, start_cf, end_cf),
        ).fetchall()
    except sqlite3.Error as exc:
        fail(target_day, "ticktick_database_read_failed", str(exc))
    finally:
        if connection is not None:
            connection.close()

    def summarize(row):
        return {
            "title": row["title"],
            "list": row["project"],
            "created_at": local_iso(row["created_at"]),
            "completed_at": local_iso(row["completed_at"]),
            "completed": row["status"] == 2 or row["completed_at"] is not None,
        }

    completed_today = [
        summarize(row)
        for row in rows
        if row["completed_at"] is not None
        and start_cf <= row["completed_at"] < end_cf
    ]
    created_today = [
        summarize(row)
        for row in rows
        if row["created_at"] is not None
        and start_cf <= row["created_at"] < end_cf
    ]

    print(
        json.dumps(
            {
                "date": target_day,
                "completed_today": completed_today,
                "created_today": created_today,
                "source": "TickTick macOS local database (read-only)",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
