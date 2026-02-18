"""
Working Memory Scratchpad
==========================
A structured key-value store that lives for the duration of one task execution.
Survives app switches — when the agent moves from Excel to Outlook, it can still
read values it extracted from Excel.

Also handles:
  - Prompt compression  (summarize old history to keep prompts small)
  - Cross-subtask data  (pass outputs from subtask 2 to subtask 5)
  - Agent notes         (free-form observations the agent writes to itself)
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Optional


class WorkingMemory:
    """
    In-memory scratchpad scoped to a single task execution.
    The agent writes to this using the scratchpad_write tool,
    and it's automatically injected into every prompt.
    """

    def __init__(self, goal: str):
        self.goal       = goal
        self.created_at = datetime.now().isoformat()
        self._data:  dict[str, Any]  = {}     # key-value store
        self._notes: list[str]       = []     # free-form observations
        self._history_full: list[dict] = []   # complete action history
        self._history_compressed: Optional[str] = None
        self._compress_threshold = 12         # compress after this many steps

    # ── Key-Value Store ───────────────────────────────────────

    def write(self, key: str, value: Any) -> None:
        """Store a named value. Overwrites if key exists."""
        self._data[key] = {
            "value":      value,
            "written_at": datetime.now().isoformat(),
        }

    def read(self, key: str) -> Optional[Any]:
        """Read a stored value. Returns None if not found."""
        entry = self._data.get(key)
        return entry["value"] if entry else None

    def read_all(self) -> dict:
        """Return all stored key-value pairs."""
        return {k: v["value"] for k, v in self._data.items()}

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    # ── Notes ─────────────────────────────────────────────────

    def add_note(self, note: str) -> None:
        """Add a free-form observation (e.g. 'The Save button is greyed out')."""
        self._notes.append(f"[{datetime.now().strftime('%H:%M:%S')}] {note}")

    def get_notes(self) -> list[str]:
        return self._notes.copy()

    # ── History Management ────────────────────────────────────

    def add_action(self, step: int, action: str, args: dict, result: str) -> None:
        self._history_full.append({
            "step":   step,
            "action": action,
            "args":   args,
            "result": result,
        })
        # Auto-compress when history gets long
        if len(self._history_full) >= self._compress_threshold:
            self._compress_history()

    def get_recent_history(self, n: int = 6) -> list[dict]:
        """Return the last N raw action records."""
        return self._history_full[-n:]

    def _compress_history(self) -> None:
        """
        Summarize old history into a compact string.
        Keeps only the last 6 steps raw; everything older is compressed.
        """
        if len(self._history_full) <= 6:
            return

        old    = self._history_full[:-6]
        recent = self._history_full[-6:]

        # Build a compact summary of old steps
        lines = []
        for h in old:
            args_str = json.dumps(h["args"])[:60]
            res_str  = h["result"][:80]
            lines.append(f"  Step {h['step']}: {h['action']}({args_str}) → {res_str}")

        summary = f"[COMPRESSED — {len(old)} earlier steps]:\n" + "\n".join(lines)

        if self._history_compressed:
            self._history_compressed += "\n" + summary
        else:
            self._history_compressed = summary

        # Replace full history with only recent steps
        self._history_full = recent

    # ── Prompt Injection ─────────────────────────────────────

    def to_prompt_section(self) -> str:
        """
        Render the working memory as a section to inject into the agent prompt.
        Keeps prompts small by summarizing old history.
        """
        sections = []

        # Stored values (cross-app data)
        if self._data:
            kv_lines = [
                f"  {k}: {json.dumps(v['value'])[:100]}"
                for k, v in self._data.items()
            ]
            sections.append("WORKING MEMORY (persists across app switches):\n" + "\n".join(kv_lines))

        # Notes
        if self._notes:
            sections.append("AGENT NOTES:\n" + "\n".join(f"  {n}" for n in self._notes[-5:]))

        # Compressed old history
        if self._history_compressed:
            sections.append(self._history_compressed)

        return "\n\n".join(sections) if sections else ""

    def format_history_for_prompt(self) -> str:
        """Format recent actions for the prompt."""
        recent = self.get_recent_history(6)
        if not recent:
            return "  (none yet)"
        return "\n".join(
            f"  [{h['step']}] {h['action']}({json.dumps(h['args'])[:70]}) → {h['result'][:100]}"
            for h in recent
        )

    # ── Serialization ─────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "goal":       self.goal,
            "data":       self.read_all(),
            "notes":      self._notes,
            "history_len":len(self._history_full),
        }