"""
Tool Executor
=============
Executes every tool the agent can call.
Returns (result_string, is_terminal).
"""

from __future__ import annotations
import os
import json
import time
import shutil
import subprocess
import glob
from pathlib import Path
from typing import Optional
import uiautomation as auto

from config import APP_LAUNCH_WAIT, STEP_DELAY
from tree_utils import find_element_by, get_window_list
from safety import normalize_app_name
from browser import get_browser


# ──────────────────────────────────────────────────────────────
# APP RESOLUTION
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

_KEY_MAP = {
    "enter": "{ENTER}",      "return": "{ENTER}",
    "escape": "{ESCAPE}",    "esc": "{ESCAPE}",
    "tab": "{TAB}",          "space": "{SPACE}",
    "delete": "{DELETE}",    "del": "{DELETE}",
    "backspace": "{BACKSPACE}",
    "up": "{UP}",   "down": "{DOWN}",
    "left": "{LEFT}", "right": "{RIGHT}",
    "home": "{HOME}", "end": "{END}",
    "pageup": "{PAGEUP}", "pagedown": "{PAGEDOWN}",
    "f1":"{F1}","f2":"{F2}","f3":"{F3}","f4":"{F4}",
    "f5":"{F5}","f6":"{F6}","f11":"{F11}","f12":"{F12}",
    "ctrl+c": "^c",  "ctrl+v": "^v",  "ctrl+x": "^x",
    "ctrl+z": "^z",  "ctrl+a": "^a",  "ctrl+s": "^s",
    "ctrl+n": "^n",  "ctrl+o": "^o",  "ctrl+w": "^w",
    "ctrl+f": "^f",  "ctrl+p": "^p",  "ctrl+r": "^r",
    "alt+f4": "%{F4}",
    "win+d":  "#{d}",
    "win+e":  "#{e}",
}


# ──────────────────────────────────────────────────────────────
# MAIN DISPATCHER
# ──────────────────────────────────────────────────────────────
def execute_action(action_name: str, arguments: dict,
                   memory=None, vision=None) -> tuple[str, bool]:
    """
    Execute an action and return (result_message, is_terminal).
    is_terminal=True → agent loop should stop.
    memory / vision are injected from the agent loop.
    """

    # ── Agent control ──────────────────────────────────────────
    if action_name == "task_complete":
        return f"✅ TASK COMPLETE: {arguments.get('summary', '')}", True

    if action_name == "task_failed":
        return f"❌ TASK FAILED: {arguments.get('reason', '')}", True

    if action_name == "ask_user":
        question = arguments.get("question", "Agent needs input:")
        print(f"\n🙋 Agent asks: {question}")
        answer = input("Your answer: ").strip()
        return f"User answered: {answer}", False

    # ── Environment ────────────────────────────────────────────
    if action_name == "open_application":
        return _open_application(arguments)

    if action_name == "close_application":
        return _close_application(arguments)

    if action_name == "switch_to_window":
        return _switch_to_window(arguments)

    if action_name == "list_open_windows":
        wins = get_window_list()
        return f"Open windows: {json.dumps([w['title'] for w in wins])}", False

    if action_name == "take_screenshot":
        if vision:
            img = vision.capture.capture_full_screen()
            path = vision.capture.save(img, "manual")
            return f"Screenshot saved: {path}", False
        return "Vision not available.", False

    # ── UI Interaction ─────────────────────────────────────────
    root = auto.GetForegroundControl()

    if action_name == "click":
        return _click(root, arguments)

    if action_name == "right_click":
        return _click(root, arguments, mode="right")

    if action_name == "double_click":
        return _click(root, arguments, mode="double")

    if action_name == "hover":
        return _click(root, arguments, mode="hover")

    if action_name == "set_value":
        return _set_value(root, arguments)

    if action_name == "type_text":
        auto.SendKeys(arguments.get("text", ""), interval=0.04)
        return f"Typed: {arguments.get('text','')}", False

    if action_name == "press_key":
        key    = arguments.get("key", "").lower()
        mapped = _KEY_MAP.get(key, f"{{{key.upper()}}}")
        auto.SendKeys(mapped)
        return f"Pressed: {key}", False

    if action_name == "scroll":
        return _scroll(root, arguments)

    if action_name == "drag_and_drop":
        return _drag_and_drop(arguments)

    # ── Observation ────────────────────────────────────────────
    if action_name == "get_element_value":
        el = find_element_by(root,
            automation_id=arguments.get("automation_id"),
            name=arguments.get("name"))
        if el and el.Exists(0, 0):
            try:
                return f"Value: '{el.GetValuePattern().Value}'", False
            except:
                return f"Name/Text: '{el.Name}'", False
        return "Element not found.", False

    if action_name == "wait_for_element":
        return _wait_for_element(arguments)

    if action_name == "find_element":
        el = find_element_by(root,
            automation_id=arguments.get("automation_id"),
            name=arguments.get("name"),
            control_type=arguments.get("control_type"))
        if el and el.Exists(0, 0):
            return f"Found: name='{el.Name}' id='{el.AutomationId}'", False
        return "Element not found.", False

    # ── Vision ─────────────────────────────────────────────────
    if action_name == "describe_screen":
        if vision:
            result = vision.describe_screen(focus=arguments.get("focus", ""))
            return f"Screen description: {result}", False
        return "Vision not available.", False

    # ── File System ────────────────────────────────────────────
    if action_name == "read_file":
        return _read_file(arguments)

    if action_name == "write_file":
        return _write_file(arguments)

    if action_name == "create_file":
        return _create_file(arguments)

    if action_name == "delete_file":
        return _delete_file(arguments)

    if action_name == "move_file":
        return _move_file(arguments)

    if action_name == "copy_file":
        return _copy_file(arguments)

    if action_name == "list_directory":
        return _list_directory(arguments)

    if action_name == "create_directory":
        path = arguments.get("path", "")
        Path(path).mkdir(parents=True, exist_ok=True)
        return f"Directory created: {path}", False

    if action_name == "open_file":
        path = arguments.get("file_path", "")
        os.startfile(path)
        time.sleep(1)
        return f"Opened: {path}", False

    if action_name == "search_files":
        return _search_files(arguments)

    # ── Browser ────────────────────────────────────────────────
    if action_name.startswith("browser_"):
        return _browser_action(action_name, arguments)

    # ── System ─────────────────────────────────────────────────
    if action_name == "get_clipboard":
        import tkinter as tk
        root_tk = tk.Tk(); root_tk.withdraw()
        try:
            text = root_tk.clipboard_get()
        except:
            text = ""
        root_tk.destroy()
        return f"Clipboard: '{text}'", False

    if action_name == "set_clipboard":
        import tkinter as tk
        root_tk = tk.Tk(); root_tk.withdraw()
        root_tk.clipboard_clear()
        root_tk.clipboard_append(arguments.get("text", ""))
        root_tk.update()
        root_tk.destroy()
        return "Clipboard set.", False

    if action_name == "get_running_processes":
        import psutil
        procs = [p.info["name"] for p in
                 __import__("psutil").process_iter(["name"])
                 if p.info["name"]]
        return f"Running processes: {json.dumps(sorted(set(procs))[:50])}", False

    if action_name == "get_screen_resolution":
        with __import__("mss").mss() as sct:
            mon = sct.monitors[1]
            return f"Resolution: {mon['width']}x{mon['height']}", False

    # ── Memory ─────────────────────────────────────────────────
    if action_name == "memory_save" and memory:
        memory.save_fact(arguments.get("key",""), arguments.get("value",""))
        return f"Saved to memory: {arguments.get('key')}", False

    if action_name == "memory_search" and memory:
        results = memory.search_similar_tasks(arguments.get("query",""))
        return f"Similar past tasks: {json.dumps(results, indent=2)}", False

    if action_name == "memory_list_sessions" and memory:
        sessions = memory.list_recent_sessions()
        return f"Recent sessions: {json.dumps(sessions, indent=2)}", False

    return f"Unknown action: {action_name}", False


# ──────────────────────────────────────────────────────────────
# ENVIRONMENT HELPERS
# ──────────────────────────────────────────────────────────────
def _open_application(args: dict) -> tuple[str, bool]:
    app_name = args.get("app_name", "").lower().strip()
    exe      = _APP_MAP.get(app_name, app_name)
    if not exe.endswith(".exe") and not exe.startswith("ms-"):
        exe = exe + ".exe"
    try:
        subprocess.Popen(exe, shell=True)
        time.sleep(APP_LAUNCH_WAIT)
        return f"Launched '{exe}'", False
    except Exception as e:
        return f"Failed to launch '{exe}': {e}", False


def _close_application(args: dict) -> tuple[str, bool]:
    import psutil
    name = args.get("app_name", "").lower()
    for proc in psutil.process_iter(["pid", "name"]):
        if name in proc.info["name"].lower():
            proc.kill()
            return f"Killed process: {proc.info['name']}", False
    # Try by window title
    for w in auto.GetRootControl().GetChildren():
        if name.lower() in w.Name.lower():
            w.SetFocus()
            auto.SendKeys("%{F4}")
            return f"Closed window: {w.Name}", False
    return f"No process/window found: '{name}'", False


def _switch_to_window(args: dict) -> tuple[str, bool]:
    title = args.get("window_title", "").lower()
    for w in auto.GetRootControl().GetChildren():
        if title in w.Name.lower():
            w.SetFocus()
            time.sleep(0.5)
            return f"Switched to: {w.Name}", False
    return f"Window not found: '{title}'", False


# ──────────────────────────────────────────────────────────────
# UI HELPERS
# ──────────────────────────────────────────────────────────────
def _click(root, args: dict, mode: str = "click") -> tuple[str, bool]:
    el = find_element_by(root,
        automation_id=args.get("automation_id"),
        name=args.get("name"),
        control_type=args.get("control_type"))

    if el and el.Exists(0, 0):
        label = args.get("name") or args.get("automation_id") or "element"
        if mode == "right":
            el.RightClick()
            return f"Right-clicked: '{label}'", False
        elif mode == "double":
            el.DoubleClick()
            return f"Double-clicked: '{label}'", False
        elif mode == "hover":
            el.MoveCursorToMyCenter()
            return f"Hovered: '{label}'", False
        else:
            el.Click()
            return f"Clicked: '{label}'", False

    return f"Element not found: {args}", False


def _set_value(root, args: dict) -> tuple[str, bool]:
    el = find_element_by(root,
        automation_id=args.get("automation_id"),
        name=args.get("name"))
    if el and el.Exists(0, 0):
        try:
            el.GetValuePattern().SetValue(args.get("value", ""))
            return f"Set value to: '{args.get('value')}'", False
        except Exception as e:
            # Fallback: click and type
            el.Click()
            auto.SendKeys("^a")
            auto.SendKeys(args.get("value", ""), interval=0.04)
            return f"Typed value (fallback): '{args.get('value')}'", False
    return "Element not found for set_value.", False


def _scroll(root, args: dict) -> tuple[str, bool]:
    direction = args.get("direction", "down")
    amount    = args.get("amount", 3)
    el = find_element_by(root,
        automation_id=args.get("automation_id"),
        name=args.get("name"))
    if el and el.Exists(0, 0):
        try:
            sp = el.GetScrollPattern()
            for _ in range(amount):
                if direction == "down":
                    sp.Scroll(auto.ScrollAmount.NoAmount, auto.ScrollAmount.SmallIncrement)
                else:
                    sp.Scroll(auto.ScrollAmount.NoAmount, auto.ScrollAmount.SmallDecrement)
            return f"Scrolled {direction} {amount}x", False
        except Exception as e:
            return f"Scroll failed: {e}", False
    # Fallback: use wheel on cursor position
    for _ in range(amount):
        auto.WheelDown(wheelTimes=3) if direction == "down" else auto.WheelUp(wheelTimes=3)
    return f"Scrolled (wheel fallback) {direction} {amount}x", False


def _drag_and_drop(args: dict) -> tuple[str, bool]:
    try:
        x1, y1 = args.get("from_x", 0), args.get("from_y", 0)
        x2, y2 = args.get("to_x", 0),   args.get("to_y", 0)
        auto.DragDrop(x1, y1, x2, y2)
        return f"Dragged ({x1},{y1}) → ({x2},{y2})", False
    except Exception as e:
        return f"Drag failed: {e}", False


def _wait_for_element(args: dict) -> tuple[str, bool]:
    timeout = args.get("timeout", 5)
    aid  = args.get("automation_id")
    name = args.get("name")
    deadline = time.time() + timeout
    while time.time() < deadline:
        root = auto.GetForegroundControl()
        el   = find_element_by(root, automation_id=aid, name=name)
        if el and el.Exists(0, 0):
            return f"Element appeared: {aid or name}", False
        time.sleep(0.5)
    return f"Timed out waiting for: {aid or name}", False


# ──────────────────────────────────────────────────────────────
# FILE SYSTEM HELPERS
# ──────────────────────────────────────────────────────────────
def _read_file(args: dict) -> tuple[str, bool]:
    path = args.get("file_path", "")
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(8000)
        return f"File content ({path}):\n{content}", False
    except Exception as e:
        return f"Read failed: {e}", False


def _write_file(args: dict) -> tuple[str, bool]:
    path    = args.get("file_path", "")
    content = args.get("content", "")
    mode    = "a" if args.get("append", False) else "w"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        return f"Written to: {path}", False
    except Exception as e:
        return f"Write failed: {e}", False


def _create_file(args: dict) -> tuple[str, bool]:
    path    = args.get("file_path", "")
    content = args.get("content", "")
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Created: {path}", False
    except Exception as e:
        return f"Create failed: {e}", False


def _delete_file(args: dict) -> tuple[str, bool]:
    path = args.get("file_path", "")
    try:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(path)
            return f"Deleted directory: {path}", False
        else:
            p.unlink()
            return f"Deleted file: {path}", False
    except Exception as e:
        return f"Delete failed: {e}", False


def _move_file(args: dict) -> tuple[str, bool]:
    src  = args.get("source_path", "")
    dest = args.get("dest_path", "")
    try:
        shutil.move(src, dest)
        return f"Moved {src} → {dest}", False
    except Exception as e:
        return f"Move failed: {e}", False


def _copy_file(args: dict) -> tuple[str, bool]:
    src  = args.get("source_path", "")
    dest = args.get("dest_path", "")
    try:
        if Path(src).is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        return f"Copied {src} → {dest}", False
    except Exception as e:
        return f"Copy failed: {e}", False


def _list_directory(args: dict) -> tuple[str, bool]:
    path  = args.get("path", ".")
    try:
        entries = list(Path(path).iterdir())
        result  = []
        for e in entries[:100]:
            result.append({
                "name": e.name,
                "type": "dir" if e.is_dir() else "file",
                "size": e.stat().st_size if e.is_file() else None,
            })
        return f"Directory listing ({path}):\n{json.dumps(result, indent=2)}", False
    except Exception as e:
        return f"List failed: {e}", False


def _search_files(args: dict) -> tuple[str, bool]:
    pattern   = args.get("pattern", "*")
    directory = args.get("directory", str(Path.home()))
    try:
        matches = glob.glob(
            str(Path(directory) / "**" / pattern),
            recursive=True
        )
        return f"Found {len(matches)} files:\n{json.dumps(matches[:50])}", False
    except Exception as e:
        return f"Search failed: {e}", False


# ──────────────────────────────────────────────────────────────
# BROWSER ROUTING
# ──────────────────────────────────────────────────────────────
def _browser_action(action_name: str, args: dict) -> tuple[str, bool]:
    b = get_browser()
    try:
        if action_name == "browser_navigate":
            url = args.get("url", "")
            # Auto-launch browser if not open
            if not b.is_open:
                browser_pref = args.get("browser", "chrome")
                b.launch(browser_pref)
            return b.navigate(url), False

        elif action_name == "browser_click":
            return b.click(
                selector=args.get("selector", ""),
                text=args.get("text", ""),
                x=args.get("x", 0),
                y=args.get("y", 0)
            ), False

        elif action_name == "browser_type":
            return b.type_text(
                selector=args.get("selector", "input"),
                text=args.get("text", ""),
                clear_first=args.get("clear_first", True)
            ), False

        elif action_name == "browser_scroll":
            return b.scroll(
                direction=args.get("direction", "down"),
                amount=args.get("amount", 300)
            ), False

        elif action_name == "browser_get_text":
            return b.get_text(args.get("selector", "body")), False

        elif action_name == "browser_wait":
            return b.wait_for_element(
                selector=args.get("selector", ""),
                timeout=args.get("timeout", 5000)
            ), False

        elif action_name == "browser_screenshot":
            path, _ = b.take_screenshot()
            return f"Browser screenshot: {path}", False

        elif action_name == "browser_execute_js":
            return b.execute_js(args.get("script", "")), False

        elif action_name == "browser_submit_form":
            return b.submit_form(args.get("selector", "form")), False

        elif action_name == "browser_get_page_source":
            return b.get_page_source(), False

        elif action_name == "browser_new_tab":
            return b.new_tab(args.get("url", "")), False

        elif action_name == "browser_back":
            return b.go_back(), False

        elif action_name == "browser_forward":
            return b.go_forward(), False

        elif action_name == "browser_press_key":
            return b.press_key(args.get("key", "Enter")), False

        else:
            return f"Unknown browser action: {action_name}", False

    except Exception as e:
        return f"Browser error: {e}", False


# ──────────────────────────────────────────────────────────────
# SCRATCHPAD ACTIONS  (injected into execute_action dispatcher)
# ──────────────────────────────────────────────────────────────
def execute_scratchpad_action(
    action_name: str,
    arguments: dict,
    working_mem,
) -> tuple[str, bool]:
    """
    Handle scratchpad and subtask-control actions.
    Returns (result, is_subtask_terminal).
    is_subtask_terminal=True means the current SUBTASK is done (not the whole task).
    """

    if action_name == "scratchpad_write":
        key   = arguments.get("key", "")
        value = arguments.get("value", "")
        working_mem.write(key, value)
        return f"Saved to scratchpad: {key} = {repr(value)[:80]}", False

    if action_name == "scratchpad_read":
        key   = arguments.get("key", "")
        value = working_mem.read(key)
        if value is None:
            return f"Key '{key}' not found in scratchpad.", False
        return f"Scratchpad[{key}] = {repr(value)[:200]}", False

    if action_name == "scratchpad_read_all":
        data = working_mem.read_all()
        if not data:
            return "Scratchpad is empty.", False
        return f"Scratchpad contents:\n{json.dumps(data, indent=2)}", False

    if action_name == "add_note":
        note = arguments.get("note", "")
        working_mem.add_note(note)
        return f"Note added: {note}", False

    if action_name == "subtask_complete":
        return f"SUBTASK_COMPLETE: {arguments.get('summary','')}", True

    if action_name == "subtask_failed":
        return f"SUBTASK_FAILED: {arguments.get('reason','')}", True

    return None, False  # Not a scratchpad action


# ──────────────────────────────────────────────────────────────
# V4 ACTIONS — Vision Grounding, Multi-Monitor, Triggers
# ──────────────────────────────────────────────────────────────
def execute_v4_action(
    action_name: str,
    arguments: dict,
    grounding_engine=None,
    monitor_manager=None,
    scheduler=None,
    vision=None,
    prev_screen_state=None,
) -> tuple[str, bool, object]:
    """
    Returns (result, is_terminal, new_screen_state).
    new_screen_state is updated after screen-change-sensitive actions.
    """
    import json

    # ── Vision Grounding ──────────────────────────────────────
    if action_name == "vision_click" and grounding_engine:
        desc  = arguments.get("description", "")
        ctype = arguments.get("click_type", "single")
        ok, msg = grounding_engine.click_element(desc, click_type=ctype)
        return msg, False, None

    if action_name == "vision_find" and grounding_engine:
        desc   = arguments.get("description", "")
        result = grounding_engine.find_element(desc)
        if result.found:
            return (f"Found '{desc}' at ({result.x},{result.y}) "
                    f"[confidence: {result.confidence:.2f}]"), False, None
        return f"Not found visually: '{desc}'. Seen: {result.description[:100]}", False, None

    if action_name == "click_at_coordinates" and grounding_engine:
        x     = arguments.get("x", 0)
        y     = arguments.get("y", 0)
        ctype = arguments.get("click_type", "single")
        ok, msg = grounding_engine.click_at(x, y, click_type=ctype)
        return msg, False, None

    if action_name == "wait_for_screen_change" and grounding_engine:
        timeout = arguments.get("timeout", 5.0)
        changed, new_state = grounding_engine.wait_for_screen_change(
            baseline=prev_screen_state, timeout=timeout
        )
        msg = "Screen changed." if changed else f"No change after {timeout}s."
        return msg, False, new_state

    if action_name == "wait_for_stable_screen" and grounding_engine:
        timeout   = arguments.get("timeout", 8.0)
        new_state = grounding_engine.wait_for_stable_screen(timeout=timeout)
        return "Screen is now stable.", False, new_state

    if action_name == "detect_current_app" and grounding_engine:
        info = grounding_engine.detect_current_app()
        return json.dumps(info), False, None

    if action_name == "read_text_at" and grounding_engine:
        text = grounding_engine.read_text_at(
            arguments.get("x", 0),
            arguments.get("y", 0),
            arguments.get("width", 300),
            arguments.get("height", 50),
        )
        return f"Text at region: {text}", False, None

    # ── Multi-Monitor ─────────────────────────────────────────
    if action_name == "list_monitors" and monitor_manager:
        return monitor_manager.describe(), False, None

    if action_name == "capture_monitor" and monitor_manager and vision:
        idx = arguments.get("monitor_index", 1)
        img = monitor_manager.capture_monitor(idx)
        if img:
            path = vision.capture.save(img, f"monitor{idx}")
            return f"Screenshot of monitor {idx} saved: {path}", False, None
        return f"Monitor {idx} not found.", False, None

    if action_name == "move_window_to_monitor" and monitor_manager:
        return monitor_manager.move_window_to_monitor(
            arguments.get("window_title", ""),
            arguments.get("monitor_index", 1),
        ), False, None

    if action_name == "list_window_locations" and monitor_manager:
        locs = monitor_manager.get_all_window_locations()
        return json.dumps(locs, indent=2), False, None

    # ── Triggers ──────────────────────────────────────────────
    if action_name == "schedule_time_trigger" and scheduler:
        days = [d.strip() for d in arguments.get("days", "").split(",") if d.strip()]
        tid  = scheduler.add_time_trigger(
            time_str   = arguments.get("time", "09:00"),
            goal       = arguments.get("goal", ""),
            days       = days or None,
        )
        return f"Time trigger set: [{tid}] at {arguments.get('time')}", False, None

    if action_name == "schedule_file_trigger" and scheduler:
        tid = scheduler.add_file_trigger(
            watch_path    = arguments.get("watch_path", ""),
            file_pattern  = arguments.get("file_pattern", "*"),
            goal_template = arguments.get("goal_template", ""),
        )
        return f"File trigger set: [{tid}]", False, None

    if action_name == "list_triggers" and scheduler:
        return json.dumps(scheduler.list_triggers(), indent=2), False, None

    if action_name == "remove_trigger" and scheduler:
        ok = scheduler.remove_trigger(arguments.get("trigger_id", ""))
        return f"Trigger removed: {ok}", False, None

    if action_name == "schedule_app_trigger" and scheduler:
        tid = scheduler.add_app_trigger(
            app_process   = arguments.get("app_process", ""),
            goal_template = arguments.get("goal_template", ""),
        )
        return f"App trigger set: [{tid}] fires when '{arguments.get('app_process')}' opens", False, None

    if action_name == "schedule_clipboard_trigger" and scheduler:
        tid = scheduler.add_clipboard_trigger(
            pattern       = arguments.get("pattern", ".*"),
            goal_template = arguments.get("goal_template", ""),
        )
        return f"Clipboard trigger set: [{tid}]", False, None

    return None, False, None   # Not a v4 action