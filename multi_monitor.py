"""
Multi-Monitor Support
======================
Handles multi-monitor setups:
  - Detect all monitors and their positions/resolutions
  - Capture any monitor or all monitors as one image
  - Find which monitor a window is on
  - Move windows between monitors
  - Focus windows on any monitor
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional
import mss
from PIL import Image
import uiautomation as auto


@dataclass
class Monitor:
    index:  int
    left:   int
    top:    int
    width:  int
    height: int
    is_primary: bool = False

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def __str__(self) -> str:
        primary = " [PRIMARY]" if self.is_primary else ""
        return f"Monitor {self.index}{primary}: {self.width}x{self.height} at ({self.left},{self.top})"


class MultiMonitorManager:
    """
    Full multi-monitor awareness and control.
    """

    def __init__(self):
        self._monitors: list[Monitor] = []
        self._refresh()

    def _refresh(self) -> None:
        """Detect all connected monitors."""
        self._monitors = []
        with mss.mss() as sct:
            for i, mon in enumerate(sct.monitors):
                if i == 0:
                    continue  # skip "all monitors" virtual entry
                self._monitors.append(Monitor(
                    index      = i,
                    left       = mon["left"],
                    top        = mon["top"],
                    width      = mon["width"],
                    height     = mon["height"],
                    is_primary = (mon["left"] == 0 and mon["top"] == 0),
                ))

    # ── Monitor Info ──────────────────────────────────────────

    def get_monitors(self) -> list[Monitor]:
        self._refresh()
        return self._monitors.copy()

    def get_primary(self) -> Optional[Monitor]:
        return next((m for m in self._monitors if m.is_primary), None)

    def get_monitor_at(self, x: int, y: int) -> Optional[Monitor]:
        """Return which monitor contains the given coordinates."""
        for m in self._monitors:
            if m.contains(x, y):
                return m
        return None

    def monitor_count(self) -> int:
        return len(self._monitors)

    def describe(self) -> str:
        lines = [f"  {m}" for m in self._monitors]
        return f"Detected {len(self._monitors)} monitor(s):\n" + "\n".join(lines)

    # ── Screen Capture ────────────────────────────────────────

    def capture_monitor(self, monitor_index: int) -> Optional[Image.Image]:
        """Capture a specific monitor by index (1-based)."""
        mon = next((m for m in self._monitors if m.index == monitor_index), None)
        if not mon:
            return None
        with mss.mss() as sct:
            region = {
                "left": mon.left, "top": mon.top,
                "width": mon.width, "height": mon.height,
            }
            shot = sct.grab(region)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def capture_all_monitors(self) -> Image.Image:
        """
        Capture all monitors stitched into one wide image.
        Useful for vision analysis across a multi-monitor setup.
        """
        if not self._monitors:
            return Image.new("RGB", (1920, 1080))

        # Calculate total bounding box
        left   = min(m.left   for m in self._monitors)
        top    = min(m.top    for m in self._monitors)
        right  = max(m.right  for m in self._monitors)
        bottom = max(m.bottom for m in self._monitors)

        total_w = right  - left
        total_h = bottom - top

        # Create canvas
        canvas = Image.new("RGB", (total_w, total_h), (30, 30, 30))

        # Paste each monitor
        for mon in self._monitors:
            img = self.capture_monitor(mon.index)
            if img:
                paste_x = mon.left - left
                paste_y = mon.top  - top
                canvas.paste(img, (paste_x, paste_y))

        return canvas

    def capture_primary(self) -> Optional[Image.Image]:
        primary = self.get_primary()
        return self.capture_monitor(primary.index) if primary else None

    # ── Window Management ─────────────────────────────────────

    def find_window_monitor(self, window_title: str) -> Optional[Monitor]:
        """
        Find which monitor a window is currently on.
        Uses UIA to get window position, then maps to monitor.
        """
        try:
            wins = auto.GetRootControl().GetChildren()
            for w in wins:
                if window_title.lower() in w.Name.lower():
                    rect = w.BoundingRectangle
                    cx   = rect.left + (rect.right - rect.left) // 2
                    cy   = rect.top  + (rect.bottom - rect.top) // 2
                    return self.get_monitor_at(cx, cy)
        except Exception:
            pass
        return None

    def move_window_to_monitor(self, window_title: str, target_monitor: int) -> str:
        """Move a window to a specific monitor."""
        mon = next((m for m in self._monitors if m.index == target_monitor), None)
        if not mon:
            return f"Monitor {target_monitor} not found."

        try:
            wins = auto.GetRootControl().GetChildren()
            for w in wins:
                if window_title.lower() in w.Name.lower():
                    # Move to target monitor center
                    target_x = mon.left + 100
                    target_y = mon.top  + 100
                    w.SetFocus()
                    time.sleep(0.2)

                    # Use Win+Shift+Arrow or move via UIA move pattern
                    try:
                        wp = w.GetWindowPattern()
                        wp.Move(target_x, target_y)
                        return f"Moved '{window_title}' to monitor {target_monitor}"
                    except Exception:
                        # Fallback: drag title bar
                        rect = w.BoundingRectangle
                        title_x = rect.left + (rect.right - rect.left) // 2
                        title_y = rect.top + 15
                        import pyautogui
                        pyautogui.moveTo(title_x, title_y)
                        pyautogui.dragTo(target_x, target_y, duration=0.5)
                        return f"Dragged '{window_title}' to monitor {target_monitor}"

        except Exception as e:
            return f"Move failed: {e}"

        return f"Window '{window_title}' not found."

    def focus_window_on_monitor(self, monitor_index: int) -> str:
        """
        Find and focus any window on the specified monitor.
        """
        mon = next((m for m in self._monitors if m.index == monitor_index), None)
        if not mon:
            return f"Monitor {monitor_index} not found."

        try:
            wins = auto.GetRootControl().GetChildren()
            for w in wins:
                if not w.Name.strip():
                    continue
                try:
                    rect = w.BoundingRectangle
                    cx   = rect.left + (rect.right - rect.left) // 2
                    cy   = rect.top  + (rect.bottom - rect.top) // 2
                    if mon.contains(cx, cy):
                        w.SetFocus()
                        return f"Focused '{w.Name}' on monitor {monitor_index}"
                except Exception:
                    continue
        except Exception as e:
            return f"Focus failed: {e}"

        return f"No window found on monitor {monitor_index}."

    def get_all_window_locations(self) -> list[dict]:
        """Return all windows and which monitor they're on."""
        result = []
        try:
            wins = auto.GetRootControl().GetChildren()
            for w in wins:
                if not w.Name.strip():
                    continue
                try:
                    rect = w.BoundingRectangle
                    cx   = rect.left + (rect.right - rect.left) // 2
                    cy   = rect.top  + (rect.bottom - rect.top) // 2
                    mon  = self.get_monitor_at(cx, cy)
                    result.append({
                        "title":   w.Name,
                        "monitor": mon.index if mon else None,
                        "x":       rect.left,
                        "y":       rect.top,
                        "width":   rect.right - rect.left,
                        "height":  rect.bottom - rect.top,
                    })
                except Exception:
                    continue
        except Exception:
            pass
        return result


# ──────────────────────────────────────────────────────────────
# SINGLETON
# ──────────────────────────────────────────────────────────────
_monitor_manager: Optional[MultiMonitorManager] = None

def get_monitor_manager() -> MultiMonitorManager:
    global _monitor_manager
    if _monitor_manager is None:
        _monitor_manager = MultiMonitorManager()
    return _monitor_manager