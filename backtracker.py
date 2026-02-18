"""
Backtracking Engine
====================
When a subtask or phase fails verification, instead of blindly moving forward
or just retrying the same thing, this module decides:

  1. Can we retry just this subtask? (most common)
  2. Do we need to redo the previous subtask first? (dependency failure)
  3. Do we need to restart the entire phase? (state corruption)
  4. Is the failure unrecoverable? (escalate to human)

Backtrack levels:
  RETRY_SUBTASK     — try the same subtask again with a new hint
  REDO_PREVIOUS     — mark previous subtask as pending, redo from there
  RESTART_PHASE     — mark entire phase as pending, restart
  ESCALATE          — give up and ask the user
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BacktrackLevel(Enum):
    RETRY_SUBTASK  = "retry_subtask"
    REDO_PREVIOUS  = "redo_previous"
    RESTART_PHASE  = "restart_phase"
    ESCALATE       = "escalate"


@dataclass
class BacktrackDecision:
    level:        BacktrackLevel
    reason:       str
    hint:         str              # injected into the retry prompt
    subtask_id:   Optional[int] = None
    phase_id:     Optional[int] = None


class BacktrackEngine:
    """
    Decides recovery strategy based on failure context.
    """

    def __init__(self, max_subtask_retries: int = 2, max_phase_retries: int = 1):
        self._subtask_attempts: dict[int, int] = {}   # subtask_id → attempt count
        self._phase_attempts:   dict[int, int] = {}   # phase_id → attempt count
        self._max_subtask      = max_subtask_retries
        self._max_phase        = max_phase_retries

    def decide(
        self,
        failed_subtask_id: int,
        failed_phase_id: int,
        failure_reason: str,
        verification_observation: str = "",
        has_previous_subtask: bool = False,
    ) -> BacktrackDecision:
        """
        Analyze the failure and decide the best recovery strategy.
        """
        reason_lower  = failure_reason.lower()
        obs_lower     = verification_observation.lower()
        attempt_count = self._subtask_attempts.get(failed_subtask_id, 0) + 1
        self._subtask_attempts[failed_subtask_id] = attempt_count

        # ── Pattern matching on failure ────────────────────────

        # Data dependency failure — need to redo a previous step
        dependency_signals = [
            "no data", "empty", "not found in scratchpad",
            "missing value", "scratchpad", "no such key",
        ]
        if has_previous_subtask and any(s in reason_lower or s in obs_lower
                                        for s in dependency_signals):
            return BacktrackDecision(
                level      = BacktrackLevel.REDO_PREVIOUS,
                reason     = f"Data dependency failure: {failure_reason[:80]}",
                hint       = (
                    "The previous subtask may not have saved the required data. "
                    "When redoing it, make sure to call scratchpad_write() with the "
                    "extracted value before calling subtask_complete()."
                ),
                subtask_id = failed_subtask_id,
            )

        # App in wrong state — may need to restart phase
        state_corruption_signals = [
            "wrong screen", "unexpected state", "dialog blocking",
            "app crashed", "not responding", "frozen",
        ]
        phase_attempt_count = self._phase_attempts.get(failed_phase_id, 0)
        if (any(s in reason_lower or s in obs_lower for s in state_corruption_signals)
                and phase_attempt_count < self._max_phase):
            self._phase_attempts[failed_phase_id] = phase_attempt_count + 1
            return BacktrackDecision(
                level    = BacktrackLevel.RESTART_PHASE,
                reason   = f"State corruption: {failure_reason[:80]}",
                hint     = (
                    "The application appears to be in an unexpected state. "
                    "Close and reopen the app, then restart this phase from the beginning."
                ),
                phase_id = failed_phase_id,
            )

        # Simple retry — within attempt limit
        if attempt_count <= self._max_subtask:
            return BacktrackDecision(
                level      = BacktrackLevel.RETRY_SUBTASK,
                reason     = f"Attempt {attempt_count}/{self._max_subtask}: {failure_reason[:80]}",
                hint       = self._build_retry_hint(
                    failure_reason, verification_observation, attempt_count
                ),
                subtask_id = failed_subtask_id,
            )

        # Exhausted all retries — escalate
        return BacktrackDecision(
            level      = BacktrackLevel.ESCALATE,
            reason     = (
                f"Subtask {failed_subtask_id} failed {attempt_count} times. "
                f"Last failure: {failure_reason[:80]}"
            ),
            hint       = "",
            subtask_id = failed_subtask_id,
        )

    def _build_retry_hint(
        self,
        failure_reason: str,
        observation: str,
        attempt: int,
    ) -> str:
        """Build a targeted retry hint based on the failure pattern."""
        hints = []

        r = failure_reason.lower()
        o = observation.lower()

        if "element not found" in r or "not found" in r:
            hints.append(
                "Element not found. Try:\n"
                "  1. Call describe_screen() to see what's actually visible\n"
                "  2. Use vision_click() instead of UIA click\n"
                "  3. The element name or ID may be different than expected"
            )
        elif "timeout" in r or "timed out" in r:
            hints.append(
                "Timed out waiting. The app may be slow to respond.\n"
                "  1. Increase wait time with wait_for_element(timeout=10)\n"
                "  2. Take a screenshot to verify the app state"
            )
        elif "verification failed" in r or "criterion" in r:
            hints.append(
                f"Verification failed. Moondream2 observed: '{observation[:100]}'\n"
                "The action may have worked but the result looks different than expected.\n"
                "Try the action again and check if the criterion needs to be interpreted differently."
            )
        elif attempt >= 2:
            hints.append(
                f"Failed {attempt} times. Use a completely different approach:\n"
                "  - If using UIA click, try vision_click() instead\n"
                "  - If typing, try set_value() instead\n"
                "  - Call describe_screen() to re-assess the current state"
            )

        return "\n".join(hints) if hints else f"Previous attempt failed: {failure_reason[:100]}"

    def apply_backtrack(self, plan, decision: BacktrackDecision) -> str:
        """
        Apply the backtrack decision to the plan by resetting subtask/phase statuses.
        Returns a description of what was reset.
        """
        from planner.hierarchical_planner import PhaseStatus

        if decision.level == BacktrackLevel.RETRY_SUBTASK:
            for phase in plan.phases:
                for subtask in phase.subtasks:
                    if subtask.id == decision.subtask_id:
                        subtask.status = PhaseStatus.PENDING
                        subtask.result = None
                        return f"Reset subtask {subtask.id} ({subtask.title}) for retry"

        elif decision.level == BacktrackLevel.REDO_PREVIOUS:
            # Find and reset both the failed subtask and the one before it
            all_subtasks = [s for p in plan.phases for s in p.subtasks]
            for i, s in enumerate(all_subtasks):
                if s.id == decision.subtask_id:
                    s.status = PhaseStatus.PENDING
                    s.result = None
                    if i > 0:
                        prev = all_subtasks[i - 1]
                        prev.status = PhaseStatus.PENDING
                        prev.result = None
                        return f"Reset subtask {s.id} and previous subtask {prev.id}"
                    return f"Reset subtask {s.id}"

        elif decision.level == BacktrackLevel.RESTART_PHASE:
            for phase in plan.phases:
                if phase.id == decision.phase_id:
                    for subtask in phase.subtasks:
                        subtask.status = PhaseStatus.PENDING
                        subtask.result = None
                    phase.status = PhaseStatus.PENDING
                    phase.result = None
                    return f"Restarted entire phase {phase.id} ({phase.title})"

        return "No state reset performed"

    def get_stats(self) -> dict:
        return {
            "subtask_retries": dict(self._subtask_attempts),
            "phase_retries":   dict(self._phase_attempts),
            "total_backtracks":sum(self._subtask_attempts.values()),
        }