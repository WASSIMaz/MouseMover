"""
Full OS Agent — Master Configuration
=====================================
User choices:
  Vision model  : Qwen2-VL via Ollama (best UI understanding)
  Confirmation  : Before ALL actions (maximum safety)
  Recovery      : Full stack — vision fallback + semantic retry + human escalation
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
MEMORY_DB      = BASE_DIR / "memory" / "agent_memory.db"
LOG_DIR        = BASE_DIR / "logs"
SCREENSHOT_DIR = BASE_DIR / "logs" / "screenshots"

# ─────────────────────────────────────────────
# LLM — PRIMARY (Gemini for planning/tool-calling)
# ─────────────────────────────────────────────
GOOGLE_API_KEY       = "AIzaSyDdpni0HdLsPXPPgSTf7Yq4sibcgvJQ6HA"
GEMINI_PLANNER_MODEL = "models/gemini-2.5-flash"
GEMINI_VISION_MODEL  = "models/gemini-2.5-flash"   # fallback only

# ─────────────────────────────────────────────
# VISION — Qwen2-VL via Ollama (runs 100% locally)
# Setup: ollama pull qwen2-vl
# ─────────────────────────────────────────────
OLLAMA_BASE_URL           = "http://localhost:11434"

# ── Vision model options ──────────────────────────────────────
# moondream        1.7 GB  fastest, great UI grounding     ← DEFAULT
# qwen2.5-vl:3b   3.0 GB  better text reading, still fast
# To switch: change VISION_MODEL and run: ollama pull <model>
VISION_MODEL              = "moondream"  # ← fast & lightweight
VISION_ENABLED            = True
VISION_FALLBACK_TO_GEMINI = True         # auto-fallback if Ollama offline
VISION_MAX_TOKENS         = 512          # moondream is fast, keep responses short
VERIFY_CONFIDENCE_THRESHOLD = 0.6        # min confidence to accept subtask as done
VERIFY_MAX_RETRIES          = 2          # retry subtask this many times if verify fails

# ─────────────────────────────────────────────
# BROWSER
# ─────────────────────────────────────────────
CHROME_PATH       = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EDGE_PATH         = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CDP_PORT_CHROME   = 9222
CDP_PORT_EDGE     = 9223
PREFERRED_BROWSER = "chrome"   # "chrome" | "edge"

# ─────────────────────────────────────────────
# AGENT LOOP
# ─────────────────────────────────────────────
MAX_STEPS       = 30
MAX_RETRIES     = 3
STEP_DELAY      = 0.8    # seconds between steps
APP_LAUNCH_WAIT = 2.5    # seconds after launching app
VISION_WAIT     = 0.5    # seconds before screenshot (let screen settle)

# ─────────────────────────────────────────────
# UI TREE
# ─────────────────────────────────────────────
UIA_MAX_DEPTH    = 10
UIA_MAX_CHILDREN = 40

# ─────────────────────────────────────────────
# MEMORY
# ─────────────────────────────────────────────
MEMORY_ENABLED              = True
MEMORY_MAX_SIMILAR          = 5
MEMORY_SIMILARITY_THRESHOLD = 0.3

# ─────────────────────────────────────────────
# RECOVERY — Full stack
# ─────────────────────────────────────────────
RECOVERY_VISION_FALLBACK    = True   # screenshot + re-reason when UIA fails
RECOVERY_SEMANTIC_RETRY     = True   # inject failure hints into next prompt
RECOVERY_HUMAN_ESCALATION   = True   # ask user when stuck after N failures
RECOVERY_STUCK_THRESHOLD    = 3      # same action N times → stuck
RECOVERY_ESCALATE_AFTER     = 9      # total failures before escalating to human

# ─────────────────────────────────────────────
# SAFETY — CONFIRMATION MODE
# ─────────────────────────────────────────────
# CONFIRM_ALL_ACTIONS = True  → pause before every non-trivial action (max safety)
# CONFIRM_ALL_ACTIONS = False → approve the PLAN upfront, then run autonomously
#                               (only HIGH-risk actions pause mid-execution)
CONFIRM_ALL_ACTIONS = True   # ← change to False for plan-approval mode

# In plan-approval mode, only these risk levels pause mid-execution:
AUTONOMOUS_HIGH_RISK_ACTIONS = {
    "delete_file",
    "move_file",
    "overwrite_file",
    "run_shell_command",
    "browser_submit_form",
    "browser_execute_js",
}

# These are always confirmed regardless of CONFIRM_ALL_ACTIONS
ALWAYS_CONFIRM = {
    "delete_file",
    "move_file",
    "overwrite_file",
    "write_file",
    "create_file",
    "copy_file",
    "create_directory",
    "run_shell_command",
    "browser_submit_form",
    "browser_execute_js",
    "close_application",
    "open_application",
    "type_text",
    "set_value",
    "press_key",
    "click",
    "right_click",
    "double_click",
    "drag_and_drop",
    "scroll",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "set_clipboard",
}

# These never need confirmation (safe read-only or observation)
NEVER_CONFIRM = {
    "list_open_windows",
    "get_element_value",
    "find_element",
    "wait_for_element",
    "get_clipboard",
    "get_running_processes",
    "get_screen_resolution",
    "list_directory",
    "read_file",
    "search_files",
    "describe_screen",
    "take_screenshot",
    "browser_get_text",
    "browser_get_page_source",
    "browser_screenshot",
    "browser_wait",
    "memory_save",
    "memory_search",
    "memory_list_sessions",
    "task_complete",
    "task_failed",
    "ask_user",
}

# Actions that are ALWAYS blocked regardless of anything
HARDBLOCKED_ACTIONS = {
    "modify_registry",
    "format_drive",
    "disable_firewall",
    "kill_system_process",
}

# ─────────────────────────────────────────────
# SAFETY — ALLOWED APPLICATIONS
# ─────────────────────────────────────────────
ALLOWED_APPS = [
    # Productivity
    "calculator", "calc", "calc.exe",
    "notepad", "notepad.exe",
    "wordpad", "wordpad.exe",
    "paint", "mspaint.exe",

    # Office (if installed)
    "word", "winword.exe",
    "excel", "excel.exe",
    "powerpoint", "powerpnt.exe",

    # Browsers
    "chrome", "chrome.exe",
    "edge", "msedge.exe",
    "firefox", "firefox.exe",

    # File management
    "explorer", "explorer.exe",

    # Media
    "vlc", "vlc.exe",
    "photos",

    # Dev tools
    "code", "code.exe",          # VS Code
    "notepad++", "notepad++.exe",

    # System (limited)
    "task manager", "taskmgr.exe",
    "snipping tool", "snippingtool.exe",
    "terminal", "wt.exe",

    # DANGER ZONE — disabled by default
    # "cmd", "cmd.exe",
    # "powershell", "powershell.exe",
    # "regedit",              # NEVER
]

# ─────────────────────────────────────────────
# SAFETY — ALLOWED FILE PATHS (sandbox)
# ─────────────────────────────────────────────
_HOME = Path.home()
ALLOWED_READ_PATHS = [
    str(_HOME / "Desktop"),
    str(_HOME / "Documents"),
    str(_HOME / "Downloads"),
    str(_HOME / "Pictures"),
    str(_HOME / "Music"),
    str(_HOME / "Videos"),
    str(BASE_DIR),               # Agent's own directory
]

ALLOWED_WRITE_PATHS = [
    str(_HOME / "Desktop"),
    str(_HOME / "Documents"),
    str(_HOME / "Downloads"),
]

# Paths the agent can NEVER touch
BLOCKED_PATHS = [
    r"C:\Windows",
    r"C:\Windows\System32",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    str(_HOME / "AppData"),
]

# ─────────────────────────────────────────────
# SAFETY — ACTION ALLOWLIST (master kill switch)
# ─────────────────────────────────────────────
ACTION_ALLOWLIST = {
    # Environment
    "open_application",
    "close_application",
    "switch_to_window",
    "list_open_windows",
    "take_screenshot",

    # UI
    "click",
    "right_click",
    "double_click",
    "set_value",
    "type_text",
    "press_key",
    "scroll",
    "drag_and_drop",
    "hover",

    # Observation
    "get_element_value",
    "wait_for_element",
    "find_element",
    "describe_screen",           # vision tool

    # File system
    "read_file",
    "write_file",
    "create_file",
    "delete_file",
    "move_file",
    "copy_file",
    "list_directory",
    "create_directory",
    "open_file",
    "search_files",

    # Browser
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_get_text",
    "browser_wait",
    "browser_screenshot",
    "browser_execute_js",
    "browser_submit_form",
    "browser_get_page_source",

    # System
    "get_clipboard",
    "set_clipboard",
    "get_running_processes",
    "get_screen_resolution",

    # Memory
    "memory_save",
    "memory_search",
    "memory_list_sessions",

    # Agent control
    "task_complete",
    "task_failed",
    "ask_user",                   # human-in-the-loop escalation

    # Disabled by default:
    # "run_shell_command",        # shell — enable only if you trust fully
    # "kill_process",             # process termination
    # "modify_registry",          # NEVER
}

# ─────────────────────────────────────────────
# V4 ADDITIONS
# ─────────────────────────────────────────────

# Vision grounding (coordinate-based control)
GROUNDING_ENABLED            = True
GROUNDING_MIN_CONFIDENCE     = 0.35   # min to attempt a vision click
GROUNDING_UIA_EMPTY_THRESHOLD = 3     # if UIA has fewer children, use vision mode

# Screen-change detection
SCREEN_CHANGE_DETECTION      = True
SCREEN_CHANGE_STABLE_WAIT    = 0.8    # seconds for screen to stabilize after action
SCREEN_CHANGE_TIMEOUT        = 6.0    # max seconds to wait for screen change

# Hierarchical planning
HIERARCHICAL_PLANNING        = True   # auto-detects complex goals
HIERARCHICAL_SUBTASK_THRESHOLD = 8    # if estimated > this, use hierarchical

# Backtracking
BACKTRACK_ENABLED            = True
MAX_SUBTASK_RETRIES          = 2
MAX_PHASE_RETRIES            = 1

# Multi-monitor
MULTI_MONITOR_ENABLED        = True
CAPTURE_ALL_MONITORS_FOR_VISION = False  # True = stitch all monitors for vision queries