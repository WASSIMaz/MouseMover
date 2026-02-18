"""
Vision Layer — Moondream2 / Qwen2.5-VL 3B via Ollama
======================================================
Fast, lightweight, local. No cloud required.
Gemini Vision is fallback only.

Model sizes:
  moondream   1.7 GB  — fastest, great UI grounding
  qwen2.5-vl:3b 3 GB  — better text reading, still fast

Change VISION_MODEL in config.py to switch.
"""

from __future__ import annotations
import base64
import io
import time
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

import mss
import mss.tools
from PIL import Image
import requests
import google.generativeai as genai

from config import (
    OLLAMA_BASE_URL, VISION_MODEL, VISION_ENABLED,
    VISION_FALLBACK_TO_GEMINI, GEMINI_VISION_MODEL,
    GOOGLE_API_KEY, SCREENSHOT_DIR, VISION_WAIT,
    VISION_MAX_TOKENS,
)


# ──────────────────────────────────────────────────────────────
# SCREEN CAPTURE
# ──────────────────────────────────────────────────────────────
class ScreenCapture:

    def capture_full_screen(self) -> Image.Image:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sshot   = sct.grab(monitor)
            return Image.frombytes("RGB", sshot.size, sshot.bgra, "raw", "BGRX")

    def capture_region(self, left: int, top: int, width: int, height: int) -> Image.Image:
        with mss.mss() as sct:
            region = {"left": left, "top": top, "width": width, "height": height}
            sshot  = sct.grab(region)
            return Image.frombytes("RGB", sshot.size, sshot.bgra, "raw", "BGRX")

    def save(self, img: Image.Image, label: str = "shot") -> Path:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = SCREENSHOT_DIR / f"{label}_{ts}.png"
        img.save(str(path))
        return path

    def to_base64(self, img: Image.Image, max_size=(1280, 800)) -> str:
        """Resize to reduce tokens, encode as base64 PNG."""
        img_copy = img.copy()
        img_copy.thumbnail(max_size, Image.LANCZOS)
        buf = io.BytesIO()
        img_copy.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


# ──────────────────────────────────────────────────────────────
# VISION ENGINE
# ──────────────────────────────────────────────────────────────
class VisionEngine:
    """
    Primary: Ollama (Moondream2 or Qwen2.5-VL 3B) — local, fast, private
    Fallback: Gemini Vision — cloud, only if Ollama is offline
    """

    def __init__(self):
        self.capture      = ScreenCapture()
        self._ollama_ok   = None   # None = not tested yet
        self._gemini_ok   = False
        self._model_name  = VISION_MODEL

        if GOOGLE_API_KEY:
            try:
                genai.configure(api_key=GOOGLE_API_KEY)
                self._gemini_model = genai.GenerativeModel(GEMINI_VISION_MODEL)
                self._gemini_ok    = True
            except Exception:
                pass

    # ── Public API ────────────────────────────────────────────

    def describe_screen(self, focus: str = "") -> str:
        """
        Screenshot → describe what's on screen.
        `focus` narrows attention to a specific area or element.
        """
        time.sleep(VISION_WAIT)
        img = self.capture.capture_full_screen()
        self.capture.save(img, "describe")
        b64 = self.capture.to_base64(img)

        prompt = (
            "You are a Windows UI automation assistant.\n"
            "Describe exactly what you see:\n"
            "- Which application is in focus?\n"
            "- What is its current state?\n"
            "- What buttons, fields, menus, text are visible?\n"
            "- Any dialogs, errors, or popups?\n"
        )
        if focus:
            prompt += f"\nFocus especially on: {focus}"

        return self._query(b64, prompt)

    def find_element_visually(self, description: str) -> dict:
        """
        Find a UI element by visual description.
        Returns {found, x, y, description} — coordinates for click fallback.
        """
        img = self.capture.capture_full_screen()
        b64 = self.capture.to_base64(img)
        w, h = img.size

        prompt = (
            f"Screen size: {w}x{h} pixels.\n"
            f"Find this element: '{description}'\n"
            "If found, respond ONLY with JSON:\n"
            '{"found": true, "x": <center_x_pixels>, "y": <center_y_pixels>, '
            '"description": "<what you see>"}\n'
            "If not found:\n"
            '{"found": false, "description": "<what you see instead>"}'
        )

        raw   = self._query(b64, prompt)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {"found": False, "description": raw[:200]}

    def read_screen_text(self) -> str:
        """Extract all visible text from the screen (OCR-like)."""
        img = self.capture.capture_full_screen()
        b64 = self.capture.to_base64(img)
        return self._query(b64,
            "Read and transcribe ALL visible text on this screen exactly as displayed. "
            "Include all labels, button text, menus, and displayed content."
        )

    def check_goal_progress(self, goal: str) -> dict:
        """
        Assess whether a goal has been achieved by looking at the screen.
        Returns {done, confidence, observation}
        """
        img = self.capture.capture_full_screen()
        b64 = self.capture.to_base64(img)

        prompt = (
            f"Goal: {goal}\n\n"
            "Look at this screenshot. Has the goal been achieved?\n"
            "Respond ONLY with JSON:\n"
            '{"done": true/false, "confidence": 0.0-1.0, '
            '"observation": "<what you see that indicates pass or fail>"}'
        )

        raw   = self._query(b64, prompt)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {"done": False, "confidence": 0.0, "observation": raw[:200]}

    def _query_for_verification(self, prompt: str) -> str:
        """
        Used by the verifier — takes a fresh screenshot and runs the given prompt.
        """
        time.sleep(VISION_WAIT)
        img = self.capture.capture_full_screen()
        self.capture.save(img, "verify")
        b64 = self.capture.to_base64(img)
        return self._query(b64, prompt)

    # ── Backend routing ───────────────────────────────────────

    def _query(self, image_b64: str, prompt: str) -> str:
        if VISION_ENABLED:
            if self._ollama_ok is None:
                self._ollama_ok = self._test_ollama()
            if self._ollama_ok:
                result = self._query_ollama(image_b64, prompt)
                if result:
                    return result

        if VISION_FALLBACK_TO_GEMINI and self._gemini_ok:
            return self._query_gemini(image_b64, prompt)

        return "[Vision unavailable — Ollama offline and Gemini fallback disabled]"

    def _test_ollama(self) -> bool:
        try:
            r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                # Match model name flexibly (moondream, moondream2, qwen2.5-vl:3b, etc.)
                model_base = VISION_MODEL.split(":")[0].lower()
                available  = any(model_base in m.lower() for m in models)
                if not available:
                    print(f"\n⚠️  Ollama running but '{VISION_MODEL}' not found.")
                    print(f"   Run: ollama pull {VISION_MODEL}")
                    print(f"   Available: {models}")
                return available
        except Exception:
            pass
        print(f"\n⚠️  Ollama not reachable at {OLLAMA_BASE_URL}")
        if VISION_FALLBACK_TO_GEMINI:
            print("   Falling back to Gemini Vision.")
        return False

    def _query_ollama(self, image_b64: str, prompt: str) -> Optional[str]:
        try:
            payload = {
                "model":     self._model_name,
                "prompt":    prompt,
                "images":    [image_b64],
                "stream":    False,
                "options":   {"num_predict": VISION_MAX_TOKENS},
            }
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
                timeout=45,
            )
            if r.status_code == 200:
                return r.json().get("response", "").strip()
            print(f"  ⚠️  Ollama HTTP {r.status_code}: {r.text[:100]}")
        except requests.Timeout:
            print("  ⚠️  Ollama vision timed out (45s)")
        except Exception as e:
            print(f"  ⚠️  Ollama error: {e}")
        return None

    def _query_gemini(self, image_b64: str, prompt: str) -> str:
        try:
            img_bytes = base64.b64decode(image_b64)
            pil_img   = Image.open(io.BytesIO(img_bytes))
            response  = self._gemini_model.generate_content([prompt, pil_img])
            return response.text.strip()
        except Exception as e:
            return f"[Gemini vision error: {e}]"

    @property
    def model_name(self) -> str:
        return self._model_name

    def status(self) -> str:
        if self._ollama_ok is True:
            return f"✅ Ollama ({self._model_name})"
        elif self._ollama_ok is False and self._gemini_ok:
            return f"⚠️  Ollama offline → Gemini Vision fallback"
        elif not VISION_ENABLED:
            return "⚠️  Vision disabled"
        return "⏳ Not yet tested"