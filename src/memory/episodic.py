import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .working import TaskState

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS task_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    issue_number INTEGER,
    task_type TEXT,
    files_modified TEXT,
    outcome TEXT NOT NULL,
    duration_s REAL,
    created_at REAL NOT NULL
);
"""


class EpisodicMemory:
    def __init__(self, db_path: str):
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # the TUI will call this from worker threads, hence the flag + lock
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
        self.session_id: str | None = None

    def start_session(self) -> str:
        self.session_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
                (self.session_id, time.time()),
            )
            self._conn.commit()
        return self.session_id

    def record_task(self, state: TaskState) -> None:
        if not state.is_terminal:
            raise ValueError("Record a task only after it reaches DONE or FAILED")
        with self._lock:
            self._conn.execute(
                "INSERT INTO task_attempts (session_id, issue_number, task_type, "
                "files_modified, outcome, duration_s, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    self.session_id,
                    state.issue_number,
                    state.task_type,
                    json.dumps(state.files_modified),
                    state.status.value,
                    state.duration_s,
                    time.time(),
                ),
            )
            self._conn.commit()

    def end_session(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM task_attempts WHERE session_id = ?", (self.session_id,)
            ).fetchall()
            summary = {
                "tasks": len(rows),
                "done": sum(r["outcome"] == "DONE" for r in rows),
                "failed": sum(r["outcome"] == "FAILED" for r in rows),
                "failed_issues": [
                    r["issue_number"]
                    for r in rows
                    if r["outcome"] == "FAILED" and r["issue_number"] is not None
                ],
                "items": [
                    {
                        "issue": r["issue_number"],
                        "type": r["task_type"],
                        "outcome": r["outcome"],
                        "files": json.loads(r["files_modified"]),
                        "duration_s": round(r["duration_s"] or 0, 1),
                    }
                    for r in rows
                ],
            }
            self._conn.execute(
                "UPDATE sessions SET ended_at = ?, summary = ? WHERE id = ?",
                (time.time(), json.dumps(summary), self.session_id),
            )
            self._conn.commit()
        return summary

    def recent_summaries(self, n: int = 3) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT summary FROM sessions WHERE ended_at IS NOT NULL "
                "ORDER BY ended_at DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [json.loads(r["summary"]) for r in rows]

    def recently_failed_issues(self, n_sessions: int = 3) -> set[int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT issue_number FROM task_attempts "
                "WHERE outcome = 'FAILED' AND issue_number IS NOT NULL "
                "AND session_id IN (SELECT id FROM sessions ORDER BY started_at DESC LIMIT ?)",
                (n_sessions,),
            ).fetchall()
        return {r["issue_number"] for r in rows}

    def done_issues(self) -> set[int]:
        """Returns set of issue numbers that were completed successfully."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT issue_number FROM task_attempts "
                "WHERE outcome = 'DONE' AND issue_number IS NOT NULL"
            ).fetchall()
        return {r["issue_number"] for r in rows}

    def done_count(self) -> int:
        """Returns total count of completed task attempts."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) as count FROM task_attempts WHERE outcome = 'DONE'"
            ).fetchone()
        return row["count"] if row else 0

    def failed_count(self) -> int:
        """Returns total count of failed task attempts."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) as count FROM task_attempts WHERE outcome = 'FAILED'"
            ).fetchone()
        return row["count"] if row else 0

    def recent_attempts(self, limit: int = 20) -> list[tuple]:
        """Return recent attempts for the interactive console history command."""
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            rows = self._conn.execute(
                "SELECT created_at, issue_number, task_type, outcome, duration_s "
                "FROM task_attempts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            (
                row["created_at"],
                row["issue_number"],
                row["task_type"],
                row["outcome"],
                row["duration_s"],
            )
            for row in rows
        ]
