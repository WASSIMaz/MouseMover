"""
Task Planner
============
Decomposes a high-level goal into an ordered list of subtasks,
each with:
  - A clear action description
  - Which apps it needs
  - A success criterion (what Qwen2-VL should see to confirm it worked)
  - Dependencies (which subtask must complete before this one)

This is a separate LLM call that runs ONCE before the execution loop starts.
The agent then executes subtasks one at a time, verifying each before moving on.
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

import google.generativeai as genai
from config import GOOGLE_API_KEY, GEMINI_PLANNER_MODEL

genai.configure(api_key=GOOGLE_API_KEY)
_model = genai.GenerativeModel(GEMINI_PLANNER_MODEL)


# ──────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────────────────────
class SubtaskStatus(Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETE   = "complete"
    FAILED     = "failed"
    SKIPPED    = "skipped"


@dataclass
class Subtask:
    id:               int
    title:            str           # Short name: "Open Calculator"
    description:      str           # Full instruction for the executor
    apps_needed:      list[str]     # e.g. ["calculator", "notepad"]
    success_criterion:str           # What Qwen2-VL should see to confirm done
    depends_on:       list[int]     # Subtask IDs that must complete first
    is_reversible:    bool = True   # False = needs extra confirmation
    status:           SubtaskStatus = SubtaskStatus.PENDING
    result:           Optional[str] = None
    steps_taken:      int           = 0
    working_memory:   dict          = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "title":            self.title,
            "description":      self.description,
            "apps_needed":      self.apps_needed,
            "success_criterion":self.success_criterion,
            "depends_on":       self.depends_on,
            "is_reversible":    self.is_reversible,
            "status":           self.status.value,
            "result":           self.result,
            "steps_taken":      self.steps_taken,
        }


@dataclass
class ExecutionPlan:
    goal:      str
    subtasks:  list[Subtask]
    created_at:str = ""

    # ── Navigation ─────────────────────────────────────────
    def next_subtask(self) -> Optional[Subtask]:
        """Return the next PENDING subtask whose dependencies are all COMPLETE."""
        complete_ids = {
            s.id for s in self.subtasks
            if s.status == SubtaskStatus.COMPLETE
        }
        for subtask in self.subtasks:
            if subtask.status != SubtaskStatus.PENDING:
                continue
            if all(dep in complete_ids for dep in subtask.depends_on):
                return subtask
        return None

    def mark_complete(self, subtask_id: int, result: str) -> None:
        s = self._get(subtask_id)
        if s:
            s.status = SubtaskStatus.COMPLETE
            s.result = result

    def mark_failed(self, subtask_id: int, reason: str) -> None:
        s = self._get(subtask_id)
        if s:
            s.status = SubtaskStatus.FAILED
            s.result = reason

    def mark_running(self, subtask_id: int) -> None:
        s = self._get(subtask_id)
        if s:
            s.status = SubtaskStatus.RUNNING

    def is_complete(self) -> bool:
        return all(
            s.status in (SubtaskStatus.COMPLETE, SubtaskStatus.SKIPPED)
            for s in self.subtasks
        )

    def has_failures(self) -> bool:
        return any(s.status == SubtaskStatus.FAILED for s in self.subtasks)

    def summary(self) -> str:
        lines = []
        icons = {
            SubtaskStatus.PENDING:  "⏳",
            SubtaskStatus.RUNNING:  "▶️ ",
            SubtaskStatus.COMPLETE: "✅",
            SubtaskStatus.FAILED:   "❌",
            SubtaskStatus.SKIPPED:  "⏭️ ",
        }
        for s in self.subtasks:
            icon = icons.get(s.status, "?")
            result_str = f" → {s.result[:60]}" if s.result else ""
            lines.append(f"  {icon} [{s.id}] {s.title}{result_str}")
        return "\n".join(lines)

    def _get(self, subtask_id: int) -> Optional[Subtask]:
        return next((s for s in self.subtasks if s.id == subtask_id), None)


# ──────────────────────────────────────────────────────────────
# PLANNER
# ──────────────────────────────────────────────────────────────
_PLANNER_PROMPT = """You are a Windows OS task planner. 
Given a high-level goal, decompose it into a clear ordered list of subtasks.

Each subtask must be:
- Atomic: accomplishable in 1-8 UI actions
- Verifiable: you can describe what the screen should look like when it's done
- Specific: clear enough that an automation agent can execute it without ambiguity

Respond ONLY with a JSON array. No explanation, no markdown, no backticks.
Format:
[
  {
    "id": 1,
    "title": "Short action title",
    "description": "Detailed instruction for the automation agent",
    "apps_needed": ["app1", "app2"],
    "success_criterion": "What Qwen2-VL should see on screen to confirm this subtask succeeded",
    "depends_on": [],
    "is_reversible": true
  },
  ...
]

Rules:
- depends_on: list of subtask IDs that must complete before this one starts
- is_reversible: false for delete/overwrite/send/submit — anything that can't be undone
- apps_needed: lowercase app names like "calculator", "notepad", "chrome", "excel"
- Keep subtasks small — max 8 UI actions each
- Always end with a verification subtask if the goal produces an output

Goal:
"""


def decompose_goal(goal: str, context: str = "") -> ExecutionPlan:
    """
    Call the LLM to decompose a goal into an ExecutionPlan.
    Falls back to a single-subtask plan if decomposition fails.
    """
    from datetime import datetime

    prompt = _PLANNER_PROMPT + goal
    if context:
        prompt += f"\n\nAdditional context: {context}"

    try:
        response = _model.generate_content(prompt)
        raw      = response.text.strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$",          "", raw, flags=re.MULTILINE)
        raw = raw.strip()

        data     = json.loads(raw)
        subtasks = [
            Subtask(
                id               = item["id"],
                title            = item["title"],
                description      = item["description"],
                apps_needed      = item.get("apps_needed", []),
                success_criterion= item.get("success_criterion", "Task completed successfully"),
                depends_on       = item.get("depends_on", []),
                is_reversible    = item.get("is_reversible", True),
            )
            for item in data
        ]

        return ExecutionPlan(
            goal      = goal,
            subtasks  = subtasks,
            created_at= datetime.now().isoformat(),
        )

    except Exception as e:
        # Fallback: treat the entire goal as one subtask
        print(f"  ⚠️  Plan decomposition failed ({e}), using single-subtask fallback")
        return ExecutionPlan(
            goal     = goal,
            subtasks = [Subtask(
                id               = 1,
                title            = "Execute goal",
                description      = goal,
                apps_needed      = [],
                success_criterion= "Goal appears to be completed on screen",
                depends_on       = [],
            )],
            created_at = "",
        )


def show_plan(plan: ExecutionPlan) -> None:
    """Print the plan to the user before execution starts."""
    print(f"\n{'╔' + '═'*60 + '╗'}")
    print(f"║  📋 EXECUTION PLAN                                           ║")
    print(f"╠{'═'*60}╣")
    print(f"║  Goal: {plan.goal[:54]:<54}║")
    print(f"╠{'═'*60}╣")
    for s in plan.subtasks:
        apps = ", ".join(s.apps_needed) or "any"
        rev  = "" if s.is_reversible else "  ⚠️ IRREVERSIBLE"
        print(f"║  [{s.id}] {s.title:<52}║")
        print(f"║      Apps: {apps:<51}║")
        print(f"║      Done when: {s.success_criterion[:44]:<44}║")
        if not s.is_reversible:
            print(f"║      {rev:<56}║")
        if s.depends_on:
            print(f"║      Needs: subtask(s) {s.depends_on} first{' '*30}║")
        print(f"╠{'═'*60}╣")
    print(f"╚{'═'*60}╝")