"""Structured session and action logger."""

import json
import os
from datetime import datetime
from pathlib import Path
from config import LOG_DIR


class AgentLogger:
    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id   = ts
        self._json_path   = LOG_DIR / f"session_{ts}.json"
        self._text_path   = LOG_DIR / f"session_{ts}.txt"
        self._data        = {
            "session_id": ts,
            "start_time": datetime.now().isoformat(),
            "goal": None,
            "actions": [],
            "outcome": None,
            "end_time": None,
        }

    def log_session_start(self, goal: str) -> None:
        self._data["goal"] = goal
        self._write(f"{'='*60}\n🤖 SESSION {self.session_id}\n🎯 GOAL: {goal}\n{'='*60}\n")

    def log_action(self, step: int, action: str, args: dict,
                   result: str, blocked: bool = False) -> None:
        entry = {
            "step": step, "timestamp": datetime.now().isoformat(),
            "action": action, "args": args,
            "result": result[:500], "blocked": blocked,
        }
        self._data["actions"].append(entry)
        self._save_json()
        icon = "🚫" if blocked else "🔧"
        self._write(f"\nStep {step} {icon} {action}\n  Args: {json.dumps(args)}\n  Result: {result[:200]}\n")

    def log_session_end(self, outcome: str) -> None:
        self._data["outcome"]  = outcome
        self._data["end_time"] = datetime.now().isoformat()
        self._save_json()
        self._write(f"\n{'='*60}\n⏹️ END: {outcome}\n{'='*60}\n")
        print(f"📄 Log: {self._json_path}")

    def _save_json(self) -> None:
        with open(self._json_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def _write(self, text: str) -> None:
        with open(self._text_path, "a", encoding="utf-8") as f:
            f.write(text)