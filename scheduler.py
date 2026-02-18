"""
Trigger Scheduler — Event-Based
=================================
Fires agent tasks when real-world events occur:

  FILE      — new file appears matching a pattern in a watched directory
  APP_OPEN  — a specific process starts (e.g. Chrome opens)
  CLIPBOARD — clipboard content changes and matches a regex
  TIME      — at a specific clock time (daily or specific days)
  INTERVAL  — every N minutes

All triggers run in a background daemon thread.
The agent continues to accept manual goals while triggers are active.
"""

from __future__ import annotations
import time, threading, hashlib, re, os, glob
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from enum import Enum


class TriggerType(Enum):
    FILE      = "file"
    APP_OPEN  = "app_open"
    CLIPBOARD = "clipboard"
    TIME      = "time"
    INTERVAL  = "interval"


@dataclass
class Trigger:
    id:         str
    type:       TriggerType
    goal:       str
    enabled:    bool  = True
    last_fired: Optional[float] = None
    fire_count: int   = 0

    # Time / interval
    time_str:   Optional[str]   = None      # "09:00"
    days:       list[str]       = field(default_factory=list)
    interval_s: Optional[float] = None

    # File
    watch_path:   Optional[str] = None
    file_pattern: Optional[str] = None
    _seen_files:  set = field(default_factory=set, repr=False)

    # App-open
    app_process:  Optional[str] = None      # e.g. "chrome.exe"
    _app_was_running: bool = False

    # Clipboard
    clip_pattern: Optional[str] = None
    _last_clip_hash: Optional[str] = None


class TriggerScheduler:
    """
    Background event-based trigger scheduler.
    Polls every `poll_interval` seconds for any of the registered events.
    """

    def __init__(self, agent_runner: Callable[[str], str], poll_interval: float = 2.0):
        self._runner   = agent_runner
        self._poll     = poll_interval
        self._triggers: list[Trigger] = []
        self._thread:   Optional[threading.Thread] = None
        self._running   = False
        self._lock      = threading.Lock()

    # ── Add triggers ──────────────────────────────────────────

    def add_file_trigger(
        self,
        watch_path: str,
        file_pattern: str,
        goal_template: str,
        trigger_id: Optional[str] = None,
    ) -> str:
        """
        Fire when a NEW file appears matching `file_pattern` in `watch_path`.
        Use {file_path} in goal_template — it's replaced with the new file's path.
        """
        tid = trigger_id or f"file_{len(self._triggers)+1}"
        existing = set(glob.glob(
            str(Path(watch_path) / "**" / file_pattern), recursive=True
        ))
        t = Trigger(
            id=tid, type=TriggerType.FILE, goal=goal_template,
            watch_path=watch_path, file_pattern=file_pattern,
            _seen_files=existing,
        )
        self._triggers.append(t)
        print(f"  📁 Trigger [{tid}]: watch '{watch_path}' for '{file_pattern}'")
        return tid

    def add_app_trigger(
        self,
        app_process: str,
        goal_template: str,
        trigger_id: Optional[str] = None,
    ) -> str:
        """
        Fire when a process starts (e.g. 'chrome.exe', 'slack.exe').
        Use {app_name} in goal_template.

        Note: requires psutil (`pip install psutil`).
        """
        tid = trigger_id or f"app_{len(self._triggers)+1}"
        # Check if already running at registration time
        already = self._is_process_running(app_process)
        t = Trigger(
            id=tid, type=TriggerType.APP_OPEN, goal=goal_template,
            app_process=app_process.lower(),
            _app_was_running=already,
        )
        self._triggers.append(t)
        print(f"  🚀 Trigger [{tid}]: fires when '{app_process}' opens")
        return tid

    def add_clipboard_trigger(
        self,
        pattern: str,
        goal_template: str,
        trigger_id: Optional[str] = None,
    ) -> str:
        """
        Fire when clipboard content changes AND matches `pattern` (regex).
        Use {clipboard} in goal_template — replaced with clipboard text.
        """
        tid = trigger_id or f"clip_{len(self._triggers)+1}"
        t   = Trigger(
            id=tid, type=TriggerType.CLIPBOARD, goal=goal_template,
            clip_pattern=pattern,
        )
        self._triggers.append(t)
        print(f"  📋 Trigger [{tid}]: fires when clipboard matches '{pattern}'")
        return tid

    def add_time_trigger(
        self,
        time_str: str,
        goal: str,
        days: Optional[list[str]] = None,
        trigger_id: Optional[str] = None,
    ) -> str:
        """Fire at HH:MM daily (or specific days like ['Mon','Wed','Fri'])."""
        tid = trigger_id or f"time_{len(self._triggers)+1}"
        t   = Trigger(
            id=tid, type=TriggerType.TIME, goal=goal,
            time_str=time_str, days=days or [],
        )
        self._triggers.append(t)
        print(f"  ⏰ Trigger [{tid}]: run at {time_str}" +
              (f" on {days}" if days else " daily"))
        return tid

    def add_interval_trigger(
        self,
        interval_minutes: float,
        goal: str,
        trigger_id: Optional[str] = None,
    ) -> str:
        """Fire every N minutes."""
        tid = trigger_id or f"interval_{len(self._triggers)+1}"
        t   = Trigger(
            id=tid, type=TriggerType.INTERVAL, goal=goal,
            interval_s=interval_minutes * 60,
        )
        self._triggers.append(t)
        print(f"  🔄 Trigger [{tid}]: run every {interval_minutes} min")
        return tid

    def remove_trigger(self, trigger_id: str) -> bool:
        with self._lock:
            before = len(self._triggers)
            self._triggers = [t for t in self._triggers if t.id != trigger_id]
            return len(self._triggers) < before

    def list_triggers(self) -> list[dict]:
        return [
            {
                "id":         t.id,
                "type":       t.type.value,
                "goal":       t.goal[:60],
                "enabled":    t.enabled,
                "fire_count": t.fire_count,
                "last_fired": (datetime.fromtimestamp(t.last_fired).strftime("%Y-%m-%d %H:%M:%S")
                               if t.last_fired else None),
            }
            for t in self._triggers
        ]

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="TriggerScheduler")
        self._thread.start()
        print(f"  🟢 Trigger scheduler started ({len(self._triggers)} trigger(s) registered)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("  🔴 Trigger scheduler stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Poll loop ─────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            now = datetime.now()
            for trigger in list(self._triggers):
                if not trigger.enabled:
                    continue
                try:
                    fired, goal = self._check(trigger, now)
                    if fired and goal:
                        trigger.fire_count += 1
                        trigger.last_fired  = time.time()
                        self._fire(trigger, goal)
                except Exception as e:
                    print(f"  ⚠️  Trigger [{trigger.id}] check error: {e}")
            time.sleep(self._poll)

    def _check(self, t: Trigger, now: datetime) -> tuple[bool, str]:
        if t.type == TriggerType.FILE:
            return self._check_file(t)
        elif t.type == TriggerType.APP_OPEN:
            return self._check_app(t)
        elif t.type == TriggerType.CLIPBOARD:
            return self._check_clipboard(t)
        elif t.type == TriggerType.TIME:
            return self._check_time(t, now)
        elif t.type == TriggerType.INTERVAL:
            return self._check_interval(t)
        return False, ""

    # ── Checkers ──────────────────────────────────────────────

    def _check_file(self, t: Trigger) -> tuple[bool, str]:
        if not t.watch_path or not t.file_pattern:
            return False, ""
        try:
            current  = set(glob.glob(
                str(Path(t.watch_path) / "**" / t.file_pattern), recursive=True
            ))
            new_files = current - t._seen_files
            t._seen_files = current
            if new_files:
                new_file = sorted(new_files, key=os.path.getctime)[-1]  # newest
                goal = t.goal.replace("{file_path}", new_file)
                return True, goal
        except Exception as e:
            pass
        return False, ""

    def _check_app(self, t: Trigger) -> tuple[bool, str]:
        """
        Fire when an app STARTS (transition from not-running to running).
        Uses psutil to scan process list.
        """
        if not t.app_process:
            return False, ""
        try:
            is_running = self._is_process_running(t.app_process)
            # Fire on the rising edge: was NOT running, now IS running
            if is_running and not t._app_was_running:
                t._app_was_running = True
                goal = t.goal.replace("{app_name}", t.app_process)
                return True, goal
            # Update state for next check
            if not is_running:
                t._app_was_running = False
        except Exception:
            pass
        return False, ""

    def _check_clipboard(self, t: Trigger) -> tuple[bool, str]:
        if not t.clip_pattern:
            return False, ""
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            try:
                clip = root.clipboard_get()
            except Exception:
                clip = ""
            root.destroy()

            if not clip:
                return False, ""

            # Only fire if clipboard actually changed
            clip_hash = hashlib.md5(clip.encode()).hexdigest()
            if clip_hash == t._last_clip_hash:
                return False, ""
            t._last_clip_hash = clip_hash

            if re.search(t.clip_pattern, clip, re.IGNORECASE):
                goal = t.goal.replace("{clipboard}", clip[:300])
                return True, goal
        except Exception:
            pass
        return False, ""

    def _check_time(self, t: Trigger, now: datetime) -> tuple[bool, str]:
        if not t.time_str:
            return False, ""
        try:
            h, m = map(int, t.time_str.split(":"))
        except Exception:
            return False, ""
        if t.days and now.strftime("%a") not in t.days:
            return False, ""
        if now.hour == h and now.minute == m:
            if t.last_fired is None or time.time() - t.last_fired > 55:
                return True, t.goal
        return False, ""

    def _check_interval(self, t: Trigger) -> tuple[bool, str]:
        if t.interval_s is None:
            return False, ""
        if t.last_fired is None or time.time() - t.last_fired >= t.interval_s:
            return True, t.goal
        return False, ""

    # ── Fire ──────────────────────────────────────────────────

    def _fire(self, trigger: Trigger, goal: str) -> None:
        print(f"\n{'━'*60}")
        print(f"  🔔 TRIGGER FIRED [{trigger.id}] ({trigger.type.value})")
        print(f"  Goal: {goal[:80]}")
        print(f"{'━'*60}")
        threading.Thread(
            target=self._run_safe,
            args=(goal,),
            daemon=True,
            name=f"trigger-{trigger.id}",
        ).start()

    def _run_safe(self, goal: str) -> None:
        try:
            result = self._runner(goal)
            print(f"\n  ✅ Trigger task done: {result[:80]}")
        except Exception as e:
            print(f"\n  ❌ Trigger task error: {e}")

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _is_process_running(process_name: str) -> bool:
        """Check if a process is currently running. Requires psutil."""
        try:
            import psutil
            name_lower = process_name.lower()
            return any(
                name_lower in p.info["name"].lower()
                for p in psutil.process_iter(["name"])
                if p.info.get("name")
            )
        except Exception:
            return False