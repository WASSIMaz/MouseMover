"""
Hierarchical Planner
=====================
For goals that require 20+ steps across multiple apps.

Structure:
  Goal
  └── Phase 1: "Gather data"
      ├── Subtask 1.1: Open Excel
      ├── Subtask 1.2: Read revenue figures
      └── Subtask 1.3: Save to scratchpad
  └── Phase 2: "Write report"
      ├── Subtask 2.1: Open Word
      ├── Subtask 2.2: Write summary
      └── Subtask 2.3: Save document
  └── Phase 3: "Distribute"
      ├── Subtask 3.1: Open Outlook
      └── Subtask 3.2: Send email

Each phase has a clear checkpoint — if phase 1 fails,
the agent doesn't start phase 2. If phase 2 fails, it
can retry just phase 2 without redoing phase 1.

Rolling context: each phase gets a fresh chat session.
The working memory scratchpad carries data across phases.
History is summarized at phase boundaries.
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from datetime import datetime

import google.generativeai as genai
from config import GOOGLE_API_KEY, GEMINI_PLANNER_MODEL

genai.configure(api_key=GOOGLE_API_KEY)
_model = genai.GenerativeModel(GEMINI_PLANNER_MODEL)


# ──────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────────────────────
class PhaseStatus(Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    FAILED   = "failed"
    SKIPPED  = "skipped"


@dataclass
class MicroTask:
    """Atomic action — corresponds to one or a few UI interactions."""
    id:          int
    description: str
    tool_hint:   str = ""   # suggested tool: "click", "type_text", etc.


@dataclass
class SubTask:
    id:               int
    title:            str
    description:      str
    apps_needed:      list[str]
    success_criterion:str
    depends_on:       list[int]
    is_reversible:    bool = True
    status:           PhaseStatus = PhaseStatus.PENDING
    result:           Optional[str] = None
    steps_taken:      int = 0


@dataclass
class Phase:
    id:               int
    title:            str
    description:      str
    checkpoint:       str           # what should be true when this phase ends
    subtasks:         list[SubTask]
    depends_on:       list[int]     # phase IDs
    status:           PhaseStatus = PhaseStatus.PENDING
    result:           Optional[str] = None

    def next_subtask(self) -> Optional[SubTask]:
        complete_ids = {s.id for s in self.subtasks if s.status == PhaseStatus.COMPLETE}
        for s in self.subtasks:
            if s.status == PhaseStatus.PENDING:
                if all(d in complete_ids for d in s.depends_on):
                    return s
        return None

    def is_complete(self) -> bool:
        return all(s.status in (PhaseStatus.COMPLETE, PhaseStatus.SKIPPED)
                   for s in self.subtasks)

    def has_failures(self) -> bool:
        return any(s.status == PhaseStatus.FAILED for s in self.subtasks)

    def progress(self) -> str:
        done  = sum(1 for s in self.subtasks if s.status == PhaseStatus.COMPLETE)
        total = len(self.subtasks)
        return f"{done}/{total} subtasks"


@dataclass
class HierarchicalPlan:
    goal:      str
    phases:    list[Phase]
    created_at:str = ""

    def next_phase(self) -> Optional[Phase]:
        complete_ids = {p.id for p in self.phases if p.status == PhaseStatus.COMPLETE}
        for p in self.phases:
            if p.status == PhaseStatus.PENDING:
                if all(d in complete_ids for d in p.depends_on):
                    return p
        return None

    def is_complete(self) -> bool:
        return all(p.status in (PhaseStatus.COMPLETE, PhaseStatus.SKIPPED)
                   for p in self.phases)

    def has_failures(self) -> bool:
        return any(p.status == PhaseStatus.FAILED for p in self.phases)

    def summary(self) -> str:
        icons = {
            PhaseStatus.PENDING:  "⏳",
            PhaseStatus.RUNNING:  "▶️ ",
            PhaseStatus.COMPLETE: "✅",
            PhaseStatus.FAILED:   "❌",
            PhaseStatus.SKIPPED:  "⏭️ ",
        }
        lines = []
        for p in self.phases:
            icon = icons.get(p.status, "?")
            lines.append(f"  {icon} Phase {p.id}: {p.title} [{p.progress()}]")
            for s in p.subtasks:
                sicon = icons.get(s.status, "?")
                res   = f" → {s.result[:50]}" if s.result else ""
                lines.append(f"      {sicon} [{s.id}] {s.title}{res}")
        return "\n".join(lines)

    def total_subtasks(self) -> int:
        return sum(len(p.subtasks) for p in self.phases)

    def completed_subtasks(self) -> int:
        return sum(
            1 for p in self.phases
            for s in p.subtasks
            if s.status == PhaseStatus.COMPLETE
        )


# ──────────────────────────────────────────────────────────────
# COMPLEXITY ASSESSMENT
# ──────────────────────────────────────────────────────────────
_COMPLEXITY_PROMPT = """Estimate the complexity of this Windows automation goal.
Respond ONLY with JSON:
{
  "estimated_subtasks": <integer>,
  "needs_multiple_apps": true/false,
  "needs_phases": true/false,
  "reasoning": "<one sentence>"
}

Goal: """

def assess_complexity(goal: str) -> dict:
    """Quick complexity check to decide flat vs hierarchical planning."""
    try:
        r     = _model.generate_content(_COMPLEXITY_PROMPT + goal)
        clean = re.sub(r"```(?:json)?", "", r.text).strip().rstrip("`")
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {"estimated_subtasks": 5, "needs_multiple_apps": False, "needs_phases": False}


# ──────────────────────────────────────────────────────────────
# HIERARCHICAL DECOMPOSER
# ──────────────────────────────────────────────────────────────
_HIERARCHICAL_PROMPT = """You are a Windows OS task planner.
Decompose this complex goal into phases, where each phase is a logical group of subtasks.

Rules:
- 2-5 phases maximum
- Each phase should be completable independently
- Each phase has a clear checkpoint (what must be true when it ends)
- Each subtask within a phase should take 2-8 UI actions
- Use scratchpad_write in subtasks that produce data needed by later phases
- Mark is_reversible: false for delete/send/submit/overwrite

Respond ONLY with valid JSON. No markdown, no explanation.

Format:
{
  "phases": [
    {
      "id": 1,
      "title": "Short phase title",
      "description": "What this phase accomplishes",
      "checkpoint": "What must be true when this phase completes",
      "depends_on": [],
      "subtasks": [
        {
          "id": 1,
          "title": "Short subtask title",
          "description": "Detailed instruction for the automation agent",
          "apps_needed": ["app_name"],
          "success_criterion": "What Moondream2 should see to confirm done",
          "depends_on": [],
          "is_reversible": true
        }
      ]
    }
  ]
}

Goal: """

def decompose_hierarchical(goal: str, context: str = "") -> HierarchicalPlan:
    """Decompose into phases → subtasks for complex long-horizon goals."""
    prompt = _HIERARCHICAL_PROMPT + goal
    if context:
        prompt += f"\n\nContext: {context}"

    try:
        r     = _model.generate_content(prompt)
        clean = re.sub(r"```(?:json)?", "", r.text).strip().rstrip("`").strip()
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in response")

        data   = json.loads(match.group())
        phases = []

        for pd in data["phases"]:
            subtasks = [
                SubTask(
                    id               = sd["id"],
                    title            = sd["title"],
                    description      = sd["description"],
                    apps_needed      = sd.get("apps_needed", []),
                    success_criterion= sd.get("success_criterion", "Task done"),
                    depends_on       = sd.get("depends_on", []),
                    is_reversible    = sd.get("is_reversible", True),
                )
                for sd in pd["subtasks"]
            ]
            phases.append(Phase(
                id          = pd["id"],
                title       = pd["title"],
                description = pd["description"],
                checkpoint  = pd.get("checkpoint", "Phase complete"),
                subtasks    = subtasks,
                depends_on  = pd.get("depends_on", []),
            ))

        return HierarchicalPlan(
            goal       = goal,
            phases     = phases,
            created_at = datetime.now().isoformat(),
        )

    except Exception as e:
        print(f"  ⚠️  Hierarchical decomposition failed ({e}), falling back to flat plan")
        # Fallback: import flat planner
        from planner.planner import decompose_goal
        flat = decompose_goal(goal)
        # Wrap all subtasks in a single phase
        subtasks = [
            SubTask(
                id               = s.id,
                title            = s.title,
                description      = s.description,
                apps_needed      = s.apps_needed,
                success_criterion= s.success_criterion,
                depends_on       = s.depends_on,
                is_reversible    = s.is_reversible,
            )
            for s in flat.subtasks
        ]
        return HierarchicalPlan(
            goal   = goal,
            phases = [Phase(
                id=1, title="Execute goal", description=goal,
                checkpoint="Goal completed", subtasks=subtasks, depends_on=[],
            )],
        )


def choose_plan_type(goal: str) -> str:
    """
    Decide whether to use flat or hierarchical planning.
    Returns "flat" or "hierarchical".
    """
    complexity = assess_complexity(goal)
    if (complexity.get("estimated_subtasks", 0) > 8 or
            complexity.get("needs_phases", False) or
            complexity.get("needs_multiple_apps", False)):
        return "hierarchical"
    return "flat"


def display_hierarchical_plan(plan: HierarchicalPlan) -> None:
    """Pretty-print the hierarchical plan for user approval."""
    W = 64
    print(f"\n{'╔' + '═'*(W-2) + '╗'}")
    print(f"║  📋 HIERARCHICAL EXECUTION PLAN{' '*(W-34)}║")
    print(f"╠{'═'*(W-2)}╣")
    print(f"║  Goal: {plan.goal[:W-10]:<{W-10}}║")
    print(f"║  Total subtasks: {plan.total_subtasks():<{W-20}}║")
    print(f"╠{'═'*(W-2)}╣")

    for phase in plan.phases:
        deps = f" (needs Phase {phase.depends_on})" if phase.depends_on else ""
        print(f"║  PHASE {phase.id}: {phase.title}{deps}{' '*(W-14-len(phase.title)-len(deps))}║")
        print(f"║    → {phase.checkpoint[:W-8]:<{W-8}}║")
        for s in phase.subtasks:
            rev  = " ⚠️" if not s.is_reversible else ""
            apps = f"[{','.join(s.apps_needed)}]" if s.apps_needed else ""
            line = f"    [{s.id}] {s.title} {apps}{rev}"
            print(f"║  {line:<{W-4}}║")
        print(f"╠{'═'*(W-2)}╣")

    print(f"╚{'═'*(W-2)}╝")