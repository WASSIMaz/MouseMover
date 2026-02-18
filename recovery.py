"""
Recovery Layer — Full Stack
============================
Three-tier recovery activated in order:

  Tier 1  Semantic retry       Re-reason with failure context injected into
                                next prompt. Does NOT just repeat. Builds
                                targeted hints explaining what went wrong.

  Tier 2  Vision fallback      When UIA returns "not found" repeatedly,
                                take a Qwen2-VL screenshot and inject the
                                visual description into the next prompt so
                                the model can see the actual screen state.

  Tier 3  Human escalation     When stuck threshold exceeded or total
                                failures too high, pause and ask the user
                                for a hint before continuing.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Callable
from config import (
    RECOVERY_VISION_FALLBACK,
    RECOVERY_SEMANTIC_RETRY,
    RECOVERY_HUMAN_ESCALATION,
    RECOVERY_STUCK_THRESHOLD,
    RECOVERY_ESCALATE_AFTER,
)


# ──────────────────────────────────────────────────────────────
# DATA
# ──────────────────────────────────────────────────────────────
@dataclass
class FailureRecord:
    step:    int
    action:  str
    args:    dict
    result:  str
    attempt: int = 1


@dataclass
class RecoveryState:
    failures:           list[FailureRecord] = field(default_factory=list)
    no_tool_call_count: int = 0
    last_action:        Optional[str] = None
    same_action_count:  int = 0
    vision_used_at:     list[int] = field(default_factory=list)
    human_hints:        list[str] = field(default_factory=list)
    total_failures:     int = 0


# ──────────────────────────────────────────────────────────────
# MANAGER
# ──────────────────────────────────────────────────────────────
class RecoveryManager:
    """
    Full recovery stack:
    semantic retry → vision fallback → human escalation
    """

    def __init__(self):
        self.state = RecoveryState()

    # ── Recording ─────────────────────────────────────────────

    def record_failure(self, action: str, args: dict, result: str, step: int) -> FailureRecord:
        """Record an action that produced an error result."""
        attempt = sum(
            1 for f in self.state.failures
            if f.action == action and f.args == args
        ) + 1
        record = FailureRecord(step=step, action=action, args=args,
                               result=result, attempt=attempt)
        self.state.failures.append(record)
        self.state.total_failures += 1
        return record

    def record_no_tool_call(self) -> None:
        """LLM returned text instead of a function call."""
        self.state.no_tool_call_count += 1
        self.state.total_failures     += 1

    def record_action(self, action: str) -> None:
        """Track repetition of the same action."""
        if action == self.state.last_action:
            self.state.same_action_count += 1
        else:
            self.state.same_action_count = 0
            self.state.last_action       = action

    def reset_stuck(self) -> None:
        self.state.no_tool_call_count = 0
        self.state.same_action_count  = 0

    # ── Detection ─────────────────────────────────────────────

    def is_stuck(self) -> bool:
        return (
            self.state.no_tool_call_count >= RECOVERY_STUCK_THRESHOLD or
            self.state.same_action_count  >= RECOVERY_STUCK_THRESHOLD
        )

    def should_use_vision(self, result: str) -> bool:
        """True when UIA is repeatedly failing to find elements."""
        if not RECOVERY_VISION_FALLBACK:
            return False
        triggers = [
            "element not found", "not found", "does not exist",
            "timed out", "failed", "error",
        ]
        return any(t in result.lower() for t in triggers)

    def should_escalate(self) -> bool:
        """True when recovery options are exhausted."""
        if not RECOVERY_HUMAN_ESCALATION:
            return False
        return self.state.total_failures >= RECOVERY_ESCALATE_AFTER or self.is_stuck()

    # ── Tier 1: Semantic Retry ─────────────────────────────────

    def build_semantic_hint(self, failure: FailureRecord) -> str:
        """
        Build a targeted, actionable hint explaining what failed and
        suggesting a specific different approach. Never says "try again".
        """
        if not RECOVERY_SEMANTIC_RETRY:
            return ""

        result_lower = failure.result.lower()
        hints = []

        # Element not found
        if "element not found" in result_lower or "not found" in result_lower:
            hints.append(
                f"⚠️  FAILURE: '{failure.action}' — element not found.\n"
                f"   What to try instead:\n"
                f"   1. Call describe_screen() to see what's actually on screen\n"
                f"   2. Try automation_id instead of name (or vice versa)\n"
                f"   3. Call wait_for_element() — the app may still be loading\n"
                f"   4. Call list_open_windows() — maybe the window isn't focused"
            )

        # App launch failed
        elif "failed to launch" in result_lower or "no such file" in result_lower:
            hints.append(
                f"⚠️  FAILURE: App launch failed for '{failure.args.get('app_name')}'.\n"
                f"   Try: use the exact .exe name, or check ALLOWED_APPS in config.py"
            )

        # Browser not open
        elif "no browser" in result_lower or "not running" in result_lower:
            hints.append(
                "⚠️  FAILURE: Browser not running.\n"
                "   Fix: call browser_navigate with a URL — it auto-launches the browser"
            )

        # Value pattern failed
        elif "valuepatt" in result_lower or "pattern" in result_lower:
            hints.append(
                f"⚠️  FAILURE: SetValue pattern failed on '{failure.args.get('automation_id','?')}'.\n"
                "   Try: click the element first, then use type_text instead of set_value"
            )

        # Scroll failed
        elif "scroll failed" in result_lower:
            hints.append(
                "⚠️  FAILURE: Scroll pattern not available.\n"
                "   Try: use press_key('PageDown') or press_key('Down') instead"
            )

        # Repeated same failure
        elif failure.attempt >= 3:
            hints.append(
                f"⚠️  CRITICAL: '{failure.action}' has failed {failure.attempt} times.\n"
                f"   You MUST try a completely different approach to achieve the same goal.\n"
                f"   Do NOT call '{failure.action}' again with similar arguments."
            )

        elif failure.attempt >= 2:
            hints.append(
                f"⚠️  '{failure.action}' failed twice. Try a different method."
            )

        else:
            hints.append(f"⚠️  Previous failure: {failure.result[:120]}")

        return "\n".join(hints)

    # ── Tier 2: Vision Fallback ────────────────────────────────

    def build_vision_hint(self, vision_description: str, step: int) -> str:
        """Wrap the Qwen2-VL screen description into a prompt hint."""
        self.state.vision_used_at.append(step)
        return (
            f"👁️  VISION ANALYSIS (Qwen2-VL screenshot at step {step}):\n"
            f"{'─'*50}\n"
            f"{vision_description}\n"
            f"{'─'*50}\n"
            "Use this visual information to identify the correct element names, "
            "IDs, or positions to interact with."
        )

    # ── Tier 3: Human Escalation ──────────────────────────────

    def escalate_to_human(self, context: str = "") -> Optional[str]:
        """
        Pause and ask the user for help.
        Returns the user's hint string, or None if they want to quit.
        """
        print(f"\n{'━'*60}")
        print("  🆘  AGENT NEEDS HELP")
        print(f"{'━'*60}")
        print(f"  The agent is stuck after {self.state.total_failures} failures.")
        if context:
            print(f"\n  Context: {context[:200]}")
        print(f"\n  Recovery summary:")
        for f in self.state.failures[-3:]:
            print(f"    Step {f.step}: {f.action} → {f.result[:80]}")
        print(f"{'━'*60}")
        print("  Options:")
        print("    [hint]  Type a hint for the agent")
        print("    [quit]  Stop the agent")
        print("    [skip]  Let the agent continue without a hint")

        while True:
            try:
                answer = input("\n  Your response: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None

            if answer.lower() == "quit":
                return None
            elif answer.lower() == "skip":
                return ""
            elif answer:
                hint = f"Human operator hint: {answer}"
                self.state.human_hints.append(hint)
                self.reset_stuck()
                return hint
            else:
                print("  Please type a hint, 'quit', or 'skip'.")

    # ── Summaries ─────────────────────────────────────────────

    def get_failure_summary(self, last_n: int = 5) -> str:
        if not self.state.failures:
            return "No failures recorded."
        lines = [
            f"  Step {f.step}: {f.action}({list(f.args.keys())}) → {f.result[:80]}"
            for f in self.state.failures[-last_n:]
        ]
        return "Recent failures:\n" + "\n".join(lines)

    def stats(self) -> dict:
        return {
            "total_failures":  self.state.total_failures,
            "same_action_streak": self.state.same_action_count,
            "no_tool_streak":  self.state.no_tool_call_count,
            "vision_calls":    len(self.state.vision_used_at),
            "human_hints":     len(self.state.human_hints),
        }