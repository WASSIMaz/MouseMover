"""
Safety Layer
============
Four tiers of enforcement:

  Tier 1  HARDBLOCK     — permanently blocked, no override possible
  Tier 2  ALLOWLIST     — action must be in the permitted set
  Tier 3  SANDBOX       — file/path/app operations are boundary-checked
  Tier 4  CONFIRMATION  — human gate before execution

User configuration (from config.py):
  CONFIRM_ALL_ACTIONS = True   → pause before every non-trivial action
  ALWAYS_CONFIRM = {...}       → always paused regardless
  NEVER_CONFIRM  = {...}       → read-only/observation — never paused
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from config import (
    ACTION_ALLOWLIST, HARDBLOCKED_ACTIONS,
    CONFIRM_ALL_ACTIONS, ALWAYS_CONFIRM, NEVER_CONFIRM,
    ALLOWED_APPS, ALLOWED_READ_PATHS, ALLOWED_WRITE_PATHS, BLOCKED_PATHS,
)


# ──────────────────────────────────────────────────────────────
# EXCEPTIONS
# ──────────────────────────────────────────────────────────────
class SafetyError(Exception):
    """Raised when an action violates a safety policy (non-recoverable)."""
    pass


class ConfirmationRequired(Exception):
    """Raised when an action needs human confirmation before proceeding."""
    def __init__(self, action: str, args: dict, description: str, risk: str):
        self.action      = action
        self.args        = args
        self.description = description
        self.risk        = risk
        super().__init__(description)


# ──────────────────────────────────────────────────────────────
# RISK LEVELS
# ──────────────────────────────────────────────────────────────
_RISK_MAP = {
    "delete_file":          ("HIGH   🔴", "Permanently deletes a file or directory"),
    "move_file":            ("MEDIUM 🟠", "Moves or renames a file"),
    "overwrite_file":       ("MEDIUM 🟠", "Overwrites existing file content"),
    "run_shell_command":    ("HIGH   🔴", "Runs a system shell command"),
    "close_application":    ("LOW    🟡", "Closes a running application"),
    "browser_submit_form":  ("MEDIUM 🟠", "Submits a web form (may send data)"),
    "browser_execute_js":   ("MEDIUM 🟠", "Executes JavaScript in the browser"),
    "write_file":           ("LOW    🟡", "Writes text to a file"),
    "create_file":          ("LOW    🟡", "Creates a new file"),
    "copy_file":            ("INFO   🟢", "Copies a file"),
    "create_directory":     ("INFO   🟢", "Creates a new folder"),
    "click":                ("INFO   🟢", "Clicks a UI element"),
    "right_click":          ("INFO   🟢", "Right-clicks a UI element"),
    "double_click":         ("INFO   🟢", "Double-clicks a UI element"),
    "drag_and_drop":        ("INFO   🟢", "Drags from one position to another"),
    "scroll":               ("INFO   🟢", "Scrolls a UI element"),
    "type_text":            ("LOW    🟡", "Types text via keyboard"),
    "set_value":            ("LOW    🟡", "Sets a field value directly"),
    "press_key":            ("LOW    🟡", "Presses a keyboard key"),
    "open_application":     ("INFO   🟢", "Launches an application"),
    "set_clipboard":        ("INFO   🟢", "Sets clipboard content"),
    "browser_navigate":     ("INFO   🟢", "Navigates to a URL"),
    "browser_click":        ("INFO   🟢", "Clicks in the browser"),
    "browser_type":         ("LOW    🟡", "Types in a browser field"),
    "browser_scroll":       ("INFO   🟢", "Scrolls the browser page"),
}
_DEFAULT_RISK = ("INFO   🟢", "Performs an agent action")


# ──────────────────────────────────────────────────────────────
# APP MAP
# ──────────────────────────────────────────────────────────────
_APP_MAP = {
    "calculator": "calc.exe",   "calc": "calc.exe",
    "notepad":    "notepad.exe",
    "paint":      "mspaint.exe",
    "wordpad":    "wordpad.exe",
    "explorer":   "explorer.exe",
    "edge":       "msedge.exe",
    "chrome":     "chrome.exe",
    "firefox":    "firefox.exe",
    "word":       "winword.exe",
    "excel":      "excel.exe",
    "powerpoint": "powerpnt.exe",
    "vlc":        "vlc.exe",
    "code":       "code.exe",
    "notepad++":  "notepad++.exe",
    "taskmgr":    "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "snipping tool": "snippingtool.exe",
    "terminal":   "wt.exe",
    "cmd":        "cmd.exe",
    "powershell": "powershell.exe",
}

def normalize_app_name(app_name: str) -> str:
    key = app_name.lower().strip().replace(".exe", "")
    return _APP_MAP.get(key, app_name if app_name.endswith(".exe") else app_name + ".exe")


# ──────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ──────────────────────────────────────────────────────────────
def check_action(action_name: str, arguments: dict) -> None:
    _check_hardblock(action_name)
    _check_allowlist(action_name)
    _check_app_sandbox(action_name, arguments)
    _check_path_sandbox(action_name, arguments)
    _check_confirmation(action_name, arguments)


# ──────────────────────────────────────────────────────────────
# TIER 1 — HARDBLOCK
# ──────────────────────────────────────────────────────────────
def _check_hardblock(action_name: str) -> None:
    if action_name in HARDBLOCKED_ACTIONS:
        raise SafetyError(
            f"HARDBLOCKED: '{action_name}' is permanently disabled.\n"
            "This action can never be enabled regardless of configuration."
        )


# ──────────────────────────────────────────────────────────────
# TIER 2 — ALLOWLIST
# ──────────────────────────────────────────────────────────────
def _check_allowlist(action_name: str) -> None:
    if action_name not in ACTION_ALLOWLIST:
        raise SafetyError(
            f"NOT ALLOWED: '{action_name}' is not in ACTION_ALLOWLIST.\n"
            "Add it to config.py to enable it."
        )


# ──────────────────────────────────────────────────────────────
# TIER 3 — SANDBOX
# ──────────────────────────────────────────────────────────────
def _check_app_sandbox(action_name: str, arguments: dict) -> None:
    if action_name != "open_application":
        return
    app = arguments.get("app_name", "").lower().strip()
    normalized = app.replace(".exe", "").replace(" ", "")
    allowed_normalized = [a.lower().replace(".exe","").replace(" ","") for a in ALLOWED_APPS]
    if normalized not in allowed_normalized:
        raise SafetyError(
            f"APP NOT ALLOWED: '{app}' is not in ALLOWED_APPS in config.py."
        )


def _check_path_sandbox(action_name: str, arguments: dict) -> None:
    write_actions = {
        "write_file","create_file","delete_file","move_file",
        "copy_file","create_directory","overwrite_file",
    }
    read_actions = {"read_file","open_file","list_directory","search_files"}

    path_arg = (
        arguments.get("file_path") or arguments.get("path") or
        arguments.get("source_path") or arguments.get("directory")
    )
    if not path_arg:
        return
    try:
        path = str(Path(path_arg).resolve())
    except Exception:
        return

    for blocked in BLOCKED_PATHS:
        if path.lower().startswith(blocked.lower()):
            raise SafetyError(
                f"SYSTEM PATH BLOCKED: '{path}'\n"
                f"Blocked prefix: '{blocked}'"
            )

    if action_name in write_actions:
        if not any(path.lower().startswith(str(Path(p).resolve()).lower()) for p in ALLOWED_WRITE_PATHS):
            raise SafetyError(f"WRITE BLOCKED: '{path}' is outside allowed write directories.")

    elif action_name in read_actions:
        if not any(path.lower().startswith(str(Path(p).resolve()).lower()) for p in ALLOWED_READ_PATHS):
            raise SafetyError(f"READ BLOCKED: '{path}' is outside allowed read directories.")


# ──────────────────────────────────────────────────────────────
# TIER 4 — CONFIRMATION
# ──────────────────────────────────────────────────────────────
def _check_confirmation(action_name: str, arguments: dict) -> None:
    # Safe read-only observation tools — never need confirmation
    if action_name in NEVER_CONFIRM:
        return

    # Confirm if in ALWAYS_CONFIRM set OR if CONFIRM_ALL_ACTIONS is enabled
    needs_confirm = action_name in ALWAYS_CONFIRM or CONFIRM_ALL_ACTIONS
    if not needs_confirm:
        return

    risk_label, risk_desc = _RISK_MAP.get(action_name, _DEFAULT_RISK)
    action_desc           = _build_action_description(action_name, arguments)

    raise ConfirmationRequired(
        action=action_name,
        args=arguments,
        description=action_desc,
        risk=f"{risk_label} — {risk_desc}",
    )


def _build_action_description(action: str, a: dict) -> str:
    templates = {
        "click":            lambda: f"Click: name='{a.get('name','')}' id='{a.get('automation_id','')}'",
        "right_click":      lambda: f"Right-click: name='{a.get('name','')}' id='{a.get('automation_id','')}'",
        "double_click":     lambda: f"Double-click: name='{a.get('name','')}' id='{a.get('automation_id','')}'",
        "type_text":        lambda: f"Type: '{a.get('text','')}'",
        "set_value":        lambda: f"Set value '{a.get('value','')}' on id='{a.get('automation_id','')}' name='{a.get('name','')}'",
        "press_key":        lambda: f"Press key: '{a.get('key','')}'",
        "scroll":           lambda: f"Scroll {a.get('direction','?')} x{a.get('amount',3)} on '{a.get('name','') or 'screen'}'",
        "drag_and_drop":    lambda: f"Drag ({a.get('from_x')},{a.get('from_y')}) to ({a.get('to_x')},{a.get('to_y')})",
        "open_application": lambda: f"Launch: '{a.get('app_name','')}'",
        "close_application":lambda: f"Close app: '{a.get('app_name','')}'",
        "write_file":       lambda: f"Write {len(a.get('content',''))} chars to: '{a.get('file_path','')}'",
        "create_file":      lambda: f"Create file: '{a.get('file_path','')}' ({len(a.get('content',''))} chars)",
        "delete_file":      lambda: f"DELETE: '{a.get('file_path','')}'",
        "move_file":        lambda: f"Move: '{a.get('source_path','')}' -> '{a.get('dest_path','')}'",
        "copy_file":        lambda: f"Copy: '{a.get('source_path','')}' -> '{a.get('dest_path','')}'",
        "create_directory": lambda: f"Create dir: '{a.get('path','')}'",
        "set_clipboard":    lambda: f"Set clipboard: '{str(a.get('text',''))[:60]}'",
        "browser_navigate": lambda: f"Navigate to: '{a.get('url','')}'",
        "browser_click":    lambda: f"Browser click: selector='{a.get('selector','')}' text='{a.get('text','')}'",
        "browser_type":     lambda: f"Browser type '{a.get('text','')}' into '{a.get('selector','')}'",
        "browser_scroll":   lambda: f"Browser scroll {a.get('direction','?')} {a.get('amount',300)}px",
        "browser_submit_form": lambda: f"Submit form: '{a.get('selector','form')}'",
        "browser_execute_js":  lambda: f"Execute JS: '{str(a.get('script',''))[:80]}'",
    }
    builder = templates.get(action)
    if builder:
        try:
            return builder()
        except Exception:
            pass
    return f"{action}({json.dumps(a)})"


# ──────────────────────────────────────────────────────────────
# CONFIRMATION UI
# ──────────────────────────────────────────────────────────────
def request_confirmation(exc: ConfirmationRequired) -> bool:
    """
    Display a rich confirmation prompt and wait for user y/n.
    Returns True if approved, False if denied or skipped.
    """
    W = 62
    border_top    = "┌" + "─"*(W-2) + "┐"
    border_mid    = "├" + "─"*(W-2) + "┤"
    border_bot    = "└" + "─"*(W-2) + "┘"
    row           = lambda s: f"│ {s:<{W-3}}│"

    print(f"\n{border_top}")
    print(row("  ⚠️  ACTION CONFIRMATION REQUIRED"))
    print(border_mid)
    print(row(f"  Action  : {exc.action}"))
    print(row(f"  Risk    : {exc.risk}"))
    print(border_mid)

    # Wrap description at 57 chars
    desc = exc.description
    chunk = W - 5
    for i in range(0, max(1, len(desc)), chunk):
        print(row(f"  {desc[i:i+chunk]}"))

    print(border_bot)
    print("  [y] Approve   [n] Deny   [skip] Skip this step")

    while True:
        try:
            answer = input("  Your choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return False

        if answer in ("y", "yes"):
            print("  ✅ Approved.\n")
            return True
        elif answer in ("", "n", "no"):
            print("  ❌ Denied — agent will try a different approach.\n")
            return False
        elif answer == "skip":
            print("  ⏭️  Skipped.\n")
            return False
        else:
            print("  Please enter y, n, or skip.")