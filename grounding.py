"""
Vision Grounding Engine
========================
Connects vision → pixel coordinates → pyautogui clicks.

Dual-backend grounding:
  Primary : Moondream2 via Ollama  (fast, local, private)
  Fallback: Gemini Vision          (cloud, if Ollama offline)

Each backend gets a tailored prompt format because they respond differently.
Moondream2 returns structured JSON naturally.
Gemini needs explicit JSON instruction and handles ambiguous descriptions better.

Works on ANY app:
  ✅ Electron (VS Code, Slack, Discord, Notion, Figma)
  ✅ Traditional Win32/WPF apps
  ✅ Browser content
  ✅ Any rendered UI that appears on screen
"""

from __future__ import annotations
import time, json, re, hashlib, io, base64
from dataclasses import dataclass
from typing import Optional
import pyautogui as pg
from PIL import Image

from config import VISION_WAIT, VERIFY_CONFIDENCE_THRESHOLD, GOOGLE_API_KEY


# ──────────────────────────────────────────────────────────────
# DATA
# ──────────────────────────────────────────────────────────────
@dataclass
class GroundingResult:
    found:       bool
    x:           int   = 0
    y:           int   = 0
    confidence:  float = 0.0
    description: str   = ""
    backend:     str   = ""   # "moondream" | "gemini" | "fallback"


@dataclass
class ScreenState:
    hash:      str
    timestamp: float


# ──────────────────────────────────────────────────────────────
# PROMPTS — tailored per backend
# ──────────────────────────────────────────────────────────────
_MOONDREAM_PROMPT = """\
Locate the UI element: '{description}'
Screen size: {w}x{h} pixels.
Respond ONLY with JSON:
{{"found": true/false, "x": <center_x_int>, "y": <center_y_int>, "confidence": 0.0-1.0, "description": "<what you see>"}}
"""

_GEMINI_PROMPT = """\
You are a Windows UI automation assistant analyzing a screenshot.
Screen size: {w}x{h} pixels.

Task: Find the UI element matching this description: '{description}'

Rules:
- x and y must be INTEGER pixel coordinates of the element's CENTER
- confidence: 0.0 (not found) to 1.0 (certain)
- If multiple matches, return the most prominent one

Respond with ONLY this JSON (no markdown, no explanation):
{{"found": true or false, "x": integer, "y": integer, "confidence": float, "description": "what you see"}}
"""


# ──────────────────────────────────────────────────────────────
# GROUNDING ENGINE
# ──────────────────────────────────────────────────────────────
class GroundingEngine:
    """
    Dual-backend vision grounding engine.
    Primary: Moondream2 (local). Fallback: Gemini Vision (cloud).
    """

    def __init__(self, vision_engine):
        self.vision = vision_engine
        pg.FAILSAFE = True
        pg.PAUSE    = 0.05

        # Gemini vision client (used as fallback)
        self._gemini_model = None
        if GOOGLE_API_KEY:
            try:
                import google.generativeai as genai
                from config import GEMINI_VISION_MODEL
                genai.configure(api_key=GOOGLE_API_KEY)
                self._gemini_model = genai.GenerativeModel(GEMINI_VISION_MODEL)
            except Exception:
                pass

    # ── Public API ────────────────────────────────────────────

    def find_element(
        self,
        description: str,
        screenshot: Optional[Image.Image] = None,
    ) -> GroundingResult:
        """
        Find a UI element by visual description.
        Tries Moondream2 first, then Gemini if Moondream2 fails or is offline.
        """
        if screenshot is None:
            time.sleep(VISION_WAIT)
            screenshot = self.vision.capture.capture_full_screen()

        w, h = screenshot.size
        b64  = self.vision.capture.to_base64(screenshot)

        # ── Try Moondream2 first ───────────────────────────────
        if self.vision._ollama_ok is None:
            self.vision._ollama_ok = self.vision._test_ollama()

        if self.vision._ollama_ok:
            prompt = _MOONDREAM_PROMPT.format(description=description, w=w, h=h)
            raw    = self.vision._query_ollama(b64, prompt)
            if raw:
                result = self._parse(raw, w, h, backend="moondream")
                if result.found and result.confidence >= 0.3:
                    return result
                # Moondream responded but with low confidence — try Gemini
                print(f"    👁️  Moondream2 low confidence ({result.confidence:.2f}), trying Gemini...")

        # ── Fallback: Gemini Vision ────────────────────────────
        if self._gemini_model:
            result = self._query_gemini_grounding(description, screenshot, w, h)
            if result.found:
                return result

        # ── Nothing worked ─────────────────────────────────────
        return GroundingResult(
            found=False,
            confidence=0.0,
            description=f"Element '{description}' not found by either backend.",
            backend="none",
        )

    def find_element_with_retry(
        self,
        description: str,
        max_attempts: int = 3,
        scroll_between: bool = False,
    ) -> GroundingResult:
        """Find with retries and optional scrolling between attempts."""
        for attempt in range(1, max_attempts + 1):
            img    = self.vision.capture.capture_full_screen()
            result = self.find_element(description, img)

            if result.found and result.confidence >= VERIFY_CONFIDENCE_THRESHOLD:
                return result

            if attempt < max_attempts:
                if scroll_between:
                    pg.scroll(-300)
                    time.sleep(0.5)

        return GroundingResult(
            found=False,
            description=f"'{description}' not found after {max_attempts} attempts",
        )

    # ── Clicking ──────────────────────────────────────────────

    def click_element(
        self,
        description: str,
        click_type: str = "single",
        screenshot: Optional[Image.Image] = None,
    ) -> tuple[bool, str]:
        """Find and click an element by visual description. Works on any app."""
        result = self.find_element(description, screenshot)

        if not result.found:
            return False, (
                f"Not found visually: '{description}'. "
                f"({result.backend}) Seen: {result.description[:80]}"
            )

        if result.confidence < 0.25:
            return False, (
                f"Very low confidence ({result.confidence:.2f}) for '{description}'. "
                f"Seen: {result.description[:80]}"
            )

        sw, sh = pg.size()
        if not (0 <= result.x <= sw and 0 <= result.y <= sh):
            return False, f"Coordinates ({result.x},{result.y}) outside screen ({sw}x{sh})"

        try:
            if click_type == "double":
                pg.doubleClick(result.x, result.y)
                verb = "Double-clicked"
            elif click_type == "right":
                pg.rightClick(result.x, result.y)
                verb = "Right-clicked"
            else:
                pg.click(result.x, result.y)
                verb = "Clicked"

            return True, (
                f"{verb} '{description}' at ({result.x},{result.y}) "
                f"[{result.backend}, conf={result.confidence:.2f}]"
            )
        except Exception as e:
            return False, f"Click failed at ({result.x},{result.y}): {e}"

    def click_at(self, x: int, y: int, click_type: str = "single") -> tuple[bool, str]:
        """Click at exact pixel coordinates."""
        try:
            sw, sh = pg.size()
            if not (0 <= x <= sw and 0 <= y <= sh):
                return False, f"({x},{y}) outside screen ({sw}x{sh})"
            if click_type == "double":
                pg.doubleClick(x, y)
            elif click_type == "right":
                pg.rightClick(x, y)
            else:
                pg.click(x, y)
            return True, f"Clicked at ({x},{y})"
        except Exception as e:
            return False, f"Click at ({x},{y}) failed: {e}"

    def drag_to(
        self, from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.5
    ) -> tuple[bool, str]:
        try:
            pg.moveTo(from_x, from_y, duration=0.2)
            pg.dragTo(to_x, to_y, duration=duration, button="left")
            return True, f"Dragged ({from_x},{from_y}) → ({to_x},{to_y})"
        except Exception as e:
            return False, f"Drag failed: {e}"

    # ── Screen-Change Detection ───────────────────────────────

    def capture_state(self) -> ScreenState:
        img   = self.vision.capture.capture_full_screen()
        small = img.resize((160, 90))
        h     = hashlib.md5(small.tobytes()).hexdigest()
        return ScreenState(hash=h, timestamp=time.time())

    def has_screen_changed(
        self, previous: Optional[ScreenState] = None
    ) -> tuple[bool, ScreenState]:
        current = self.capture_state()
        if previous is None:
            return True, current
        return current.hash != previous.hash, current

    def wait_for_screen_change(
        self,
        baseline: Optional[ScreenState] = None,
        timeout: float = 5.0,
        poll: float = 0.25,
    ) -> tuple[bool, ScreenState]:
        if baseline is None:
            baseline = self.capture_state()
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll)
            changed, state = self.has_screen_changed(baseline)
            if changed:
                return True, state
        return False, self.capture_state()

    def wait_for_stable_screen(
        self, stable_for: float = 0.8, timeout: float = 8.0, poll: float = 0.25
    ) -> ScreenState:
        deadline     = time.time() + timeout
        last         = self.capture_state()
        stable_since = time.time()
        while time.time() < deadline:
            time.sleep(poll)
            changed, new = self.has_screen_changed(last)
            if changed:
                last         = new
                stable_since = time.time()
            elif time.time() - stable_since >= stable_for:
                return last
        return self.capture_state()

    # ── App Detection ─────────────────────────────────────────

    def detect_current_app(self) -> dict:
        img = self.vision.capture.capture_full_screen()
        b64 = self.vision.capture.to_base64(img)
        prompt = (
            "What Windows application is currently open and in focus?\n"
            "Respond ONLY with JSON:\n"
            '{"app_name":"<n>","app_type":"electron|win32|browser|game|other",'
            '"current_state":"<brief>","uia_likely_works":true/false}'
        )
        raw   = self.vision._query(b64, prompt)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {"app_name":"unknown","app_type":"other",
                "current_state":raw[:150],"uia_likely_works":True}

    def read_text_at(self, x: int, y: int, width: int = 300, height: int = 50) -> str:
        img = self.vision.capture.capture_region(
            left=max(0,x-width//2), top=max(0,y-height//2),
            width=width, height=height,
        )
        b64 = self.vision.capture.to_base64(img)
        return self.vision._query(b64, "Transcribe all text visible in this image exactly.")

    def is_uia_empty(self, tree: dict) -> bool:
        if not tree:
            return True
        children  = tree.get("children", [])
        meaningful = [c for c in children if c.get("name","").strip() or c.get("id","").strip()]
        return len(meaningful) < 3

    # ── Gemini Grounding ──────────────────────────────────────

    def _query_gemini_grounding(
        self, description: str, screenshot: Image.Image, w: int, h: int
    ) -> GroundingResult:
        """
        Query Gemini Vision with a coordinate-grounding prompt.
        Gemini is better at understanding ambiguous descriptions and
        returns more reliable coordinates for complex UIs.
        """
        if not self._gemini_model:
            return GroundingResult(found=False, description="Gemini not configured", backend="gemini")

        try:
            prompt = _GEMINI_PROMPT.format(description=description, w=w, h=h)
            # Gemini needs the PIL image directly
            response = self._gemini_model.generate_content([prompt, screenshot])
            raw      = response.text.strip()
            result   = self._parse(raw, w, h, backend="gemini")
            return result
        except Exception as e:
            return GroundingResult(
                found=False, description=f"Gemini grounding error: {e}", backend="gemini"
            )

    # ── Parsing ───────────────────────────────────────────────

    def _parse(self, raw: str, w: int, h: int, backend: str) -> GroundingResult:
        """Parse JSON coordinate response from either backend."""
        try:
            clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if not data.get("found", False):
                    return GroundingResult(
                        found=False,
                        confidence=float(data.get("confidence", 0.0)),
                        description=data.get("description", ""),
                        backend=backend,
                    )
                x = max(0, min(int(data.get("x", 0)), w - 1))
                y = max(0, min(int(data.get("y", 0)), h - 1))
                return GroundingResult(
                    found=True, x=x, y=y,
                    confidence=float(data.get("confidence", 0.6)),
                    description=data.get("description", ""),
                    backend=backend,
                )
        except Exception:
            pass

        # Last resort: extract raw coordinates
        m = re.search(r"(\d{2,4})[,\s]+(\d{2,4})", raw)
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            if 0 <= x <= w and 0 <= y <= h:
                return GroundingResult(
                    found=True, x=x, y=y, confidence=0.35,
                    description="Parsed from raw response", backend=backend,
                )

        return GroundingResult(
            found=False, confidence=0.0,
            description=raw[:150], backend=backend,
        )