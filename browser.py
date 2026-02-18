"""
Browser Control Layer
======================
Controls Chrome and Edge via Chrome DevTools Protocol (CDP).
Uses playwright for robust cross-browser automation.

Install: pip install playwright && playwright install chromium
"""

from __future__ import annotations
import json
import time
import subprocess
from pathlib import Path
from typing import Optional

from config import CHROME_PATH, EDGE_PATH, PREFERRED_BROWSER


# ──────────────────────────────────────────────────────────────
# BROWSER MANAGER
# ──────────────────────────────────────────────────────────────
class BrowserManager:
    """
    Manages Chrome/Edge via Playwright.
    Supports switching between browsers, multiple tabs, JS execution.
    """

    def __init__(self):
        self._playwright  = None
        self._browser     = None
        self._context     = None
        self._page        = None
        self._browser_type = None

    # ── Lifecycle ─────────────────────────────────────────────

    def launch(self, browser: str = PREFERRED_BROWSER) -> str:
        """
        Launch Chrome or Edge.
        browser: "chrome" | "edge" | "auto"
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ("❌ Playwright not installed.\n"
                    "Run: pip install playwright && playwright install chromium")

        if self._browser:
            return f"Browser already running: {self._browser_type}"

        try:
            p = sync_playwright().start()
            self._playwright = p

            if browser == "edge":
                self._browser = p.chromium.launch(
                    executable_path=EDGE_PATH,
                    headless=False,
                    args=["--start-maximized"]
                )
                self._browser_type = "edge"
            else:
                # Chrome (or auto-detect chromium)
                try:
                    self._browser = p.chromium.launch(
                        executable_path=CHROME_PATH,
                        headless=False,
                        args=["--start-maximized"]
                    )
                    self._browser_type = "chrome"
                except Exception:
                    # Fallback to playwright's built-in chromium
                    self._browser = p.chromium.launch(headless=False)
                    self._browser_type = "chromium"

            self._context = self._browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            self._page = self._context.new_page()
            return f"✅ Launched {self._browser_type}"

        except Exception as e:
            return f"❌ Failed to launch browser: {e}"

    def close(self) -> str:
        """Close the browser."""
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
            self._browser    = None
            self._context    = None
            self._page       = None
            self._playwright = None
            return "Browser closed."
        except Exception as e:
            return f"Close failed: {e}"

    def _ensure_launched(self) -> Optional[str]:
        """Auto-launch if not already running."""
        if not self._page:
            result = self.launch()
            if "❌" in result:
                return result
            time.sleep(1)
        return None

    # ── Navigation ────────────────────────────────────────────

    def navigate(self, url: str) -> str:
        err = self._ensure_launched()
        if err:
            return err
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            self._page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return f"Navigated to: {self._page.url}"
        except Exception as e:
            return f"Navigation failed: {e}"

    def get_current_url(self) -> str:
        if not self._page:
            return "No browser open."
        return self._page.url

    def go_back(self) -> str:
        if not self._page:
            return "No browser open."
        self._page.go_back()
        return f"Went back to: {self._page.url}"

    def go_forward(self) -> str:
        if not self._page:
            return "No browser open."
        self._page.go_forward()
        return f"Went forward to: {self._page.url}"

    # ── Interaction ───────────────────────────────────────────

    def click(self, selector: str = "", text: str = "", x: int = 0, y: int = 0) -> str:
        """
        Click a browser element.
        Can use CSS selector, visible text, or x/y coordinates.
        """
        err = self._ensure_launched()
        if err:
            return err
        try:
            if selector:
                self._page.click(selector, timeout=5000)
                return f"Clicked selector: {selector}"
            elif text:
                self._page.get_by_text(text, exact=False).first.click(timeout=5000)
                return f"Clicked text: {text}"
            elif x and y:
                self._page.mouse.click(x, y)
                return f"Clicked position: ({x}, {y})"
            return "No click target provided."
        except Exception as e:
            return f"Click failed: {e}"

    def type_text(self, selector: str, text: str, clear_first: bool = True) -> str:
        """Type text into a browser input field."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            el = self._page.locator(selector).first
            if clear_first:
                el.clear()
            el.type(text, delay=30)
            return f"Typed into {selector}: '{text}'"
        except Exception as e:
            return f"Type failed: {e}"

    def scroll(self, direction: str = "down", amount: int = 300) -> str:
        """Scroll the page."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            delta = amount if direction == "down" else -amount
            self._page.mouse.wheel(0, delta)
            return f"Scrolled {direction} by {amount}px"
        except Exception as e:
            return f"Scroll failed: {e}"

    def press_key(self, key: str) -> str:
        """Press a key in the browser (Enter, Escape, Tab, etc.)."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            self._page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key press failed: {e}"

    def submit_form(self, selector: str = "form") -> str:
        """Submit a form."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            self._page.locator(selector).first.evaluate("el => el.submit()")
            return "Form submitted."
        except Exception as e:
            return f"Submit failed: {e}"

    # ── Observation ───────────────────────────────────────────

    def get_text(self, selector: str = "body") -> str:
        """Get visible text from the page or a specific element."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            if selector == "body":
                text = self._page.inner_text("body")
                return text[:3000] + ("..." if len(text) > 3000 else "")
            else:
                el   = self._page.locator(selector).first
                text = el.inner_text()
                return text[:3000]
        except Exception as e:
            return f"Get text failed: {e}"

    def get_page_source(self) -> str:
        """Get the HTML source of the current page (truncated)."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            html = self._page.content()
            return html[:5000] + ("..." if len(html) > 5000 else "")
        except Exception as e:
            return f"Get source failed: {e}"

    def get_all_links(self) -> str:
        """Get all links on the page."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            links = self._page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))"
            )
            return json.dumps(links[:50], indent=2)
        except Exception as e:
            return f"Get links failed: {e}"

    def execute_js(self, script: str) -> str:
        """Execute JavaScript on the page."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            result = self._page.evaluate(script)
            return f"JS result: {json.dumps(result)}"
        except Exception as e:
            return f"JS execution failed: {e}"

    def take_screenshot(self) -> tuple[str, bytes]:
        """Take a screenshot of the browser window. Returns (path, bytes)."""
        err = self._ensure_launched()
        if err:
            return err, b""
        try:
            from config import SCREENSHOT_DIR
            from datetime import datetime
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(SCREENSHOT_DIR / f"browser_{ts}.png")
            self._page.screenshot(path=path)
            with open(path, "rb") as f:
                data = f.read()
            return path, data
        except Exception as e:
            return f"Screenshot failed: {e}", b""

    def wait_for_element(self, selector: str, timeout: int = 5000) -> str:
        """Wait for an element to appear in the browser."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            self._page.wait_for_selector(selector, timeout=timeout)
            return f"Element appeared: {selector}"
        except Exception as e:
            return f"Wait timeout for '{selector}': {e}"

    def new_tab(self, url: str = "") -> str:
        """Open a new browser tab."""
        err = self._ensure_launched()
        if err:
            return err
        try:
            self._page = self._context.new_page()
            if url:
                return self.navigate(url)
            return "New tab opened."
        except Exception as e:
            return f"New tab failed: {e}"

    @property
    def is_open(self) -> bool:
        return self._page is not None


# ──────────────────────────────────────────────────────────────
# SINGLETON
# ──────────────────────────────────────────────────────────────
_browser_manager: Optional[BrowserManager] = None

def get_browser() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager