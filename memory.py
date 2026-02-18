"""
Persistent Memory Layer
========================
SQLite-backed memory with:
  - Session history (every action ever taken)
  - Task memory  (what goals were attempted + outcomes)
  - Key-value store (agent can save/recall facts)
  - Semantic search (find similar past tasks using TF-IDF)
"""

from __future__ import annotations
import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from math import log, sqrt
from config import MEMORY_DB, MEMORY_MAX_SIMILAR


# ──────────────────────────────────────────────────────────────
# DATABASE SETUP
# ──────────────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(MEMORY_DB))
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT UNIQUE NOT NULL,
            goal        TEXT,
            outcome     TEXT,
            steps       INTEGER DEFAULT 0,
            started_at  TEXT,
            ended_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            step        INTEGER,
            action      TEXT,
            args        TEXT,
            result      TEXT,
            blocked     INTEGER DEFAULT 0,
            timestamp   TEXT
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            goal        TEXT NOT NULL,
            outcome     TEXT,
            success     INTEGER DEFAULT 0,
            steps_taken INTEGER DEFAULT 0,
            session_id  TEXT,
            created_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS facts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key         TEXT UNIQUE NOT NULL,
            value       TEXT,
            updated_at  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_actions_session ON actions(session_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_goal      ON tasks(goal);
    """)
    conn.commit()


# ──────────────────────────────────────────────────────────────
# SESSION MANAGEMENT
# ──────────────────────────────────────────────────────────────
class AgentMemory:
    def __init__(self, session_id: str, goal: str):
        self.session_id = session_id
        self.goal       = goal
        self._conn      = _get_conn()
        self._start_session()

    def _start_session(self) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions(session_id, goal, started_at) VALUES(?,?,?)",
            (self.session_id, self.goal, datetime.now().isoformat())
        )
        self._conn.commit()

    def log_action(self, step: int, action: str, args: dict,
                   result: str, blocked: bool = False) -> None:
        self._conn.execute(
            """INSERT INTO actions(session_id, step, action, args, result, blocked, timestamp)
               VALUES(?,?,?,?,?,?,?)""",
            (self.session_id, step, action, json.dumps(args),
             result, int(blocked), datetime.now().isoformat())
        )
        self._conn.commit()

    def end_session(self, outcome: str, success: bool) -> None:
        self._conn.execute(
            """UPDATE sessions SET outcome=?, ended_at=?, steps=(
                   SELECT COUNT(*) FROM actions WHERE session_id=?
               ) WHERE session_id=?""",
            (outcome, datetime.now().isoformat(), self.session_id, self.session_id)
        )
        self._conn.execute(
            """INSERT INTO tasks(goal, outcome, success, steps_taken, session_id, created_at)
               VALUES(?,?,?,?,?,?)""",
            (self.goal, outcome, int(success),
             self.get_step_count(), self.session_id, datetime.now().isoformat())
        )
        self._conn.commit()

    def save_fact(self, key: str, value: str) -> None:
        """Store a named fact the agent wants to remember."""
        self._conn.execute(
            """INSERT INTO facts(key, value, updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, datetime.now().isoformat())
        )
        self._conn.commit()

    def get_fact(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM facts WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_step_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as c FROM actions WHERE session_id=?",
            (self.session_id,)
        ).fetchone()
        return row["c"] if row else 0

    def get_session_history(self, last_n: int = 10) -> list[dict]:
        """Return last N actions from this session."""
        rows = self._conn.execute(
            """SELECT step, action, args, result, blocked FROM actions
               WHERE session_id=? ORDER BY step DESC LIMIT ?""",
            (self.session_id, last_n)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def search_similar_tasks(self, query: str, limit: int = MEMORY_MAX_SIMILAR) -> list[dict]:
        """Find past tasks similar to the current goal using simple TF-IDF."""
        rows = self._conn.execute(
            "SELECT goal, outcome, success, steps_taken, created_at FROM tasks ORDER BY id DESC LIMIT 200"
        ).fetchall()

        if not rows:
            return []

        scored = []
        query_tokens = _tokenize(query)

        for row in rows:
            goal_tokens = _tokenize(row["goal"])
            score = _tfidf_similarity(query_tokens, goal_tokens)
            if score > 0.1:
                scored.append({
                    "goal":       row["goal"],
                    "outcome":    row["outcome"],
                    "success":    bool(row["success"]),
                    "steps_taken": row["steps_taken"],
                    "created_at": row["created_at"],
                    "similarity": round(score, 3),
                })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]

    def list_recent_sessions(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            """SELECT session_id, goal, outcome, steps, started_at, ended_at
               FROM sessions ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()


# ──────────────────────────────────────────────────────────────
# SIMPLE TF-IDF SIMILARITY  (no external deps)
# ──────────────────────────────────────────────────────────────
def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _tfidf_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Cosine similarity between two token lists (bag-of-words)."""
    if not tokens_a or not tokens_b:
        return 0.0

    vocab = set(tokens_a) | set(tokens_b)

    def vec(tokens):
        freq = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        n = len(tokens)
        return {t: c / n for t, c in freq.items()}

    va = vec(tokens_a)
    vb = vec(tokens_b)

    dot    = sum(va.get(t, 0) * vb.get(t, 0) for t in vocab)
    norm_a = sqrt(sum(v**2 for v in va.values()))
    norm_b = sqrt(sum(v**2 for v in vb.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)