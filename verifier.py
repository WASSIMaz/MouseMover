"""
Subtask Verifier
================
After each subtask completes (agent calls task_complete),
this module takes a screenshot and asks the vision model:
"Did this subtask actually succeed?"

If confidence is below threshold, the subtask is retried once.
If it fails twice, the agent escalates to the user.

Uses Moondream2 / Qwen2.5-VL for fast local inference.
"""

from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from config import VISION_WAIT


@dataclass
class VerificationResult:
    passed:      bool
    confidence:  float   # 0.0 – 1.0
    observation: str     # What the vision model saw
    suggestion:  str     # What to try if it failed


_VERIFY_PROMPT_TEMPLATE = """You are verifying whether a Windows automation subtask succeeded.

Subtask: {title}
Success criterion: {criterion}

Look at this screenshot carefully.

Respond ONLY with JSON (no markdown, no explanation):
{{
  "passed": true or false,
  "confidence": 0.0 to 1.0,
  "observation": "what you see on screen that tells you pass/fail",
  "suggestion": "if failed, what should be tried differently (empty string if passed)"
}}
"""


class SubtaskVerifier:
    """
    Verifies subtask completion using the vision model.
    """

    def __init__(self, vision_engine):
        self.vision = vision_engine

    def verify(
        self,
        subtask_title: str,
        success_criterion: str,
        wait: float = VISION_WAIT,
    ) -> VerificationResult:
        """
        Take a screenshot and verify whether the subtask succeeded.
        """
        time.sleep(wait)  # Let the screen settle

        # Build focused prompt for the vision model
        prompt = _VERIFY_PROMPT_TEMPLATE.format(
            title    = subtask_title,
            criterion= success_criterion,
        )

        # Use the vision engine's describe_screen with our specific prompt
        raw_response = self.vision._query_for_verification(prompt)

        return self._parse_response(raw_response, subtask_title)

    def _parse_response(self, raw: str, subtask_title: str) -> VerificationResult:
        """Parse the JSON response from the vision model."""
        try:
            # Strip markdown fences
            clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return VerificationResult(
                    passed     = bool(data.get("passed", False)),
                    confidence = float(data.get("confidence", 0.5)),
                    observation= str(data.get("observation", "")),
                    suggestion = str(data.get("suggestion", "")),
                )
        except Exception as e:
            pass

        # Fallback: crude keyword check on raw text
        passed = any(w in raw.lower() for w in ["success", "completed", "visible", "done", "true"])
        return VerificationResult(
            passed     = passed,
            confidence = 0.4,
            observation= raw[:200],
            suggestion = "Could not parse vision response — try describing_screen manually",
        )

    def quick_check(self, question: str) -> bool:
        """
        Simple yes/no check using the vision model.
        e.g. "Is the calculator currently open and visible?"
        """
        prompt = (
            f"{question}\n\n"
            "Respond ONLY with JSON: {\"yes\": true/false, \"reason\": \"one sentence\"}"
        )
        raw    = self.vision._query_for_verification(prompt)
        try:
            clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return bool(data.get("yes", False))
        except Exception:
            pass
        return "yes" in raw.lower()