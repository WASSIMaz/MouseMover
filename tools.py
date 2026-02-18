"""
All tool definitions for Gemini tool-calling mode.
This is what the LLM sees — descriptions must be clear and precise.
"""

TOOLS = [{"function_declarations": [

    # ══════════════════════════════════════════
    # AGENT CONTROL
    # ══════════════════════════════════════════
    {
        "name": "task_complete",
        "description": "Call this ONLY when the goal has been fully achieved. Provide a clear summary.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string", "description": "What was accomplished"}
        }, "required": ["summary"]}
    },
    {
        "name": "task_failed",
        "description": "Call this when the goal cannot be achieved. Explain why clearly.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}
        }, "required": ["reason"]}
    },
    {
        "name": "ask_user",
        "description": "Ask the user a question when you need information to proceed.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string"}
        }, "required": ["question"]}
    },

    # ══════════════════════════════════════════
    # ENVIRONMENT
    # ══════════════════════════════════════════
    {
        "name": "open_application",
        "description": (
            "Launch a Windows application. Use FIRST if the app is not already open. "
            "Examples: 'calculator', 'notepad', 'chrome', 'excel', 'explorer'. "
            "After calling this, call wait_for_element to confirm it loaded."
        ),
        "parameters": {"type": "object", "properties": {
            "app_name": {"type": "string", "description": "App name like 'calculator', 'notepad', 'chrome'"}
        }, "required": ["app_name"]}
    },
    {
        "name": "close_application",
        "description": "Close a running application by name.",
        "parameters": {"type": "object", "properties": {
            "app_name": {"type": "string"}
        }, "required": ["app_name"]}
    },
    {
        "name": "switch_to_window",
        "description": "Bring an already-open window into focus by its title.",
        "parameters": {"type": "object", "properties": {
            "window_title": {"type": "string"}
        }, "required": ["window_title"]}
    },
    {
        "name": "list_open_windows",
        "description": "List all currently open windows. Use to check what's running before opening something.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the current screen and save it.",
        "parameters": {"type": "object", "properties": {
            "label": {"type": "string", "description": "Optional label for the file"}
        }}
    },

    # ══════════════════════════════════════════
    # UI INTERACTION
    # ══════════════════════════════════════════
    {
        "name": "click",
        "description": (
            "Click a UI element. Prefer automation_id (more reliable). "
            "Calculator button IDs: 'num0'-'num9', 'plus', 'minus', 'multiply', 'divide', "
            "'equals', 'clearEntry', 'clear', 'negate', 'decimalSeparator'. "
            "If automation_id unknown, use name."
        ),
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string", "description": "AutomationId (preferred)"},
            "name":          {"type": "string", "description": "Element name (fallback)"},
            "control_type":  {"type": "string", "description": "Optional: 'Button', 'MenuItem', etc."}
        }}
    },
    {
        "name": "right_click",
        "description": "Right-click a UI element to open its context menu.",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"}
        }}
    },
    {
        "name": "double_click",
        "description": "Double-click a UI element (to open files, folders, etc.).",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"}
        }}
    },
    {
        "name": "hover",
        "description": "Move mouse over a UI element without clicking.",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"}
        }}
    },
    {
        "name": "set_value",
        "description": "Set the value of a text field directly (faster than typing).",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"},
            "value":         {"type": "string"}
        }, "required": ["value"]}
    },
    {
        "name": "type_text",
        "description": "Type text into the currently focused element using keyboard simulation.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}
        }, "required": ["text"]}
    },
    {
        "name": "press_key",
        "description": (
            "Press a keyboard key or shortcut. "
            "Examples: 'Enter', 'Escape', 'Tab', 'Delete', 'Ctrl+C', 'Ctrl+V', "
            "'Ctrl+S', 'Ctrl+A', 'Alt+F4', 'Win+D', 'F5'."
        ),
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"}
        }, "required": ["key"]}
    },
    {
        "name": "scroll",
        "description": "Scroll a UI element or the screen up/down.",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"},
            "direction":     {"type": "string", "enum": ["up", "down"]},
            "amount":        {"type": "integer", "description": "Steps (default 3)"}
        }, "required": ["direction"]}
    },
    {
        "name": "drag_and_drop",
        "description": "Drag from one screen position to another.",
        "parameters": {"type": "object", "properties": {
            "from_x": {"type": "integer"},
            "from_y": {"type": "integer"},
            "to_x":   {"type": "integer"},
            "to_y":   {"type": "integer"}
        }, "required": ["from_x", "from_y", "to_x", "to_y"]}
    },

    # ══════════════════════════════════════════
    # OBSERVATION
    # ══════════════════════════════════════════
    {
        "name": "get_element_value",
        "description": "Read the current text/value of a UI element (label, text box, display).",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"}
        }}
    },
    {
        "name": "wait_for_element",
        "description": "Wait until a UI element appears. Use after launching apps or navigating.",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"},
            "timeout":       {"type": "integer", "description": "Seconds to wait (default 5)"}
        }}
    },
    {
        "name": "find_element",
        "description": "Check if a UI element exists and return its properties.",
        "parameters": {"type": "object", "properties": {
            "automation_id": {"type": "string"},
            "name":          {"type": "string"},
            "control_type":  {"type": "string"}
        }}
    },
    {
        "name": "describe_screen",
        "description": (
            "Take a screenshot and use vision AI to describe what's on screen. "
            "Use when UIA tree is empty/confusing or when you need to verify the current state."
        ),
        "parameters": {"type": "object", "properties": {
            "focus": {"type": "string", "description": "What to focus on in the description"}
        }}
    },

    # ══════════════════════════════════════════
    # FILE SYSTEM
    # ══════════════════════════════════════════
    {
        "name": "read_file",
        "description": "Read the text contents of a file.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"}
        }, "required": ["file_path"]}
    },
    {
        "name": "write_file",
        "description": "Write or append text to a file.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"},
            "content":   {"type": "string"},
            "append":    {"type": "boolean", "description": "If true, append instead of overwrite"}
        }, "required": ["file_path", "content"]}
    },
    {
        "name": "create_file",
        "description": "Create a new file with content.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"},
            "content":   {"type": "string"}
        }, "required": ["file_path"]}
    },
    {
        "name": "delete_file",
        "description": "Delete a file or directory. REQUIRES user confirmation.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"}
        }, "required": ["file_path"]}
    },
    {
        "name": "move_file",
        "description": "Move or rename a file. REQUIRES user confirmation.",
        "parameters": {"type": "object", "properties": {
            "source_path": {"type": "string"},
            "dest_path":   {"type": "string"}
        }, "required": ["source_path", "dest_path"]}
    },
    {
        "name": "copy_file",
        "description": "Copy a file or directory.",
        "parameters": {"type": "object", "properties": {
            "source_path": {"type": "string"},
            "dest_path":   {"type": "string"}
        }, "required": ["source_path", "dest_path"]}
    },
    {
        "name": "list_directory",
        "description": "List files and folders in a directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]}
    },
    {
        "name": "create_directory",
        "description": "Create a new folder.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]}
    },
    {
        "name": "open_file",
        "description": "Open a file with its default application.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"}
        }, "required": ["file_path"]}
    },
    {
        "name": "search_files",
        "description": "Search for files matching a pattern in a directory.",
        "parameters": {"type": "object", "properties": {
            "pattern":   {"type": "string", "description": "Glob pattern, e.g. '*.txt', 'report*'"},
            "directory": {"type": "string", "description": "Where to search"}
        }, "required": ["pattern"]}
    },

    # ══════════════════════════════════════════
    # BROWSER
    # ══════════════════════════════════════════
    {
        "name": "browser_navigate",
        "description": "Navigate to a URL. Auto-launches browser if not open.",
        "parameters": {"type": "object", "properties": {
            "url":     {"type": "string"},
            "browser": {"type": "string", "description": "'chrome' or 'edge' (default: chrome)"}
        }, "required": ["url"]}
    },
    {
        "name": "browser_click",
        "description": "Click an element in the browser by CSS selector, visible text, or coordinates.",
        "parameters": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "CSS selector"},
            "text":     {"type": "string", "description": "Visible text of the element"},
            "x":        {"type": "integer"},
            "y":        {"type": "integer"}
        }}
    },
    {
        "name": "browser_type",
        "description": "Type text into a browser input field.",
        "parameters": {"type": "object", "properties": {
            "selector":    {"type": "string"},
            "text":        {"type": "string"},
            "clear_first": {"type": "boolean"}
        }, "required": ["selector", "text"]}
    },
    {
        "name": "browser_scroll",
        "description": "Scroll the browser page up or down.",
        "parameters": {"type": "object", "properties": {
            "direction": {"type": "string", "enum": ["up", "down"]},
            "amount":    {"type": "integer", "description": "Pixels (default 300)"}
        }, "required": ["direction"]}
    },
    {
        "name": "browser_get_text",
        "description": "Get visible text content from the browser page or a specific element.",
        "parameters": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "CSS selector (default: 'body' for whole page)"}
        }}
    },
    {
        "name": "browser_wait",
        "description": "Wait for a browser element to appear.",
        "parameters": {"type": "object", "properties": {
            "selector": {"type": "string"},
            "timeout":  {"type": "integer", "description": "Milliseconds (default 5000)"}
        }, "required": ["selector"]}
    },
    {
        "name": "browser_screenshot",
        "description": "Take a screenshot of the browser window.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "browser_execute_js",
        "description": "Execute JavaScript in the browser. Use for complex interactions.",
        "parameters": {"type": "object", "properties": {
            "script": {"type": "string"}
        }, "required": ["script"]}
    },
    {
        "name": "browser_submit_form",
        "description": "Submit a form. REQUIRES user confirmation.",
        "parameters": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "Form selector (default: 'form')"}
        }}
    },
    {
        "name": "browser_get_page_source",
        "description": "Get the HTML source of the current page.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "browser_new_tab",
        "description": "Open a new browser tab.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}
        }}
    },
    {
        "name": "browser_back",
        "description": "Navigate back in browser history.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "browser_press_key",
        "description": "Press a key in the browser (Enter, Escape, Tab, etc.).",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"}
        }, "required": ["key"]}
    },

    # ══════════════════════════════════════════
    # SYSTEM
    # ══════════════════════════════════════════
    {
        "name": "get_clipboard",
        "description": "Read the current clipboard contents.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "set_clipboard",
        "description": "Write text to the clipboard.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}
        }, "required": ["text"]}
    },
    {
        "name": "get_running_processes",
        "description": "List all currently running processes.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "get_screen_resolution",
        "description": "Get the current screen resolution.",
        "parameters": {"type": "object", "properties": {}}
    },

    # ══════════════════════════════════════════
    # MEMORY
    # ══════════════════════════════════════════
    {
        "name": "memory_save",
        "description": "Save a named fact to persistent memory for future sessions.",
        "parameters": {"type": "object", "properties": {
            "key":   {"type": "string"},
            "value": {"type": "string"}
        }, "required": ["key", "value"]}
    },
    {
        "name": "memory_search",
        "description": "Search for similar past tasks in memory.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}
        }, "required": ["query"]}
    },
    {
        "name": "memory_list_sessions",
        "description": "List recent past sessions and their outcomes.",
        "parameters": {"type": "object", "properties": {}}
    },

]}]

# Append scratchpad and plan tools to TOOLS list
TOOLS[0]["function_declarations"].extend([

    # ══════════════════════════════════════════
    # WORKING MEMORY / SCRATCHPAD
    # ══════════════════════════════════════════
    {
        "name": "scratchpad_write",
        "description": (
            "Save a value to working memory so it persists across app switches. "
            "Use this to remember data extracted from one app before switching to another. "
            "Example: save a number from Excel before opening Outlook."
        ),
        "parameters": {"type": "object", "properties": {
            "key":   {"type": "string",  "description": "Name for this value, e.g. 'revenue_q3', 'email_address'"},
            "value": {"type": "string",  "description": "The value to remember"},
        }, "required": ["key", "value"]}
    },
    {
        "name": "scratchpad_read",
        "description": "Read a value previously saved to working memory.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"}
        }, "required": ["key"]}
    },
    {
        "name": "scratchpad_read_all",
        "description": "Read all values currently in working memory.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "add_note",
        "description": (
            "Write a free-form observation to yourself that will appear in future prompts. "
            "Use for things like: 'The Save button is greyed out', 'Login failed once already'."
        ),
        "parameters": {"type": "object", "properties": {
            "note": {"type": "string"}
        }, "required": ["note"]}
    },

    # ══════════════════════════════════════════
    # SUBTASK CONTROL
    # ══════════════════════════════════════════
    {
        "name": "subtask_complete",
        "description": (
            "Call this when the CURRENT SUBTASK (not the whole goal) is done. "
            "The agent will verify completion with Moondream2 before moving to the next subtask. "
            "Provide a clear summary of what was accomplished."
        ),
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string", "description": "What was accomplished in this subtask"}
        }, "required": ["summary"]}
    },
    {
        "name": "subtask_failed",
        "description": "Call this when the current subtask cannot be completed. Explain why.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}
        }, "required": ["reason"]}
    },
])

# ── V4: Vision Grounding + Monitor + Trigger tools ──────────────
TOOLS[0]["function_declarations"].extend([

    # Vision-based clicking (works on Electron, Slack, VS Code, etc.)
    {
        "name": "vision_click",
        "description": (
            "Click a UI element by VISUAL DESCRIPTION — no UIA required. "
            "Use this for Electron apps (VS Code, Slack, Discord, Notion, Figma), "
            "modern apps where UIA fails, or when click() returns 'element not found'. "
            "Moondream2 finds the element visually and clicks its pixel coordinates."
        ),
        "parameters": {"type": "object", "properties": {
            "description": {"type": "string", "description": "Visual description: 'the blue Save button', 'search bar at the top', 'File menu'"},
            "click_type":  {"type": "string", "enum": ["single","double","right"], "description": "Default: single"},
        }, "required": ["description"]}
    },
    {
        "name": "vision_find",
        "description": "Find a UI element visually and return its coordinates without clicking.",
        "parameters": {"type": "object", "properties": {
            "description": {"type": "string"},
        }, "required": ["description"]}
    },
    {
        "name": "click_at_coordinates",
        "description": "Click at exact pixel coordinates. Use after vision_find returns x,y.",
        "parameters": {"type": "object", "properties": {
            "x":          {"type": "integer"},
            "y":          {"type": "integer"},
            "click_type": {"type": "string", "enum": ["single","double","right"]},
        }, "required": ["x","y"]}
    },
    {
        "name": "wait_for_screen_change",
        "description": "Wait for the screen to visually change after an action (e.g., after clicking a button that opens a dialog).",
        "parameters": {"type": "object", "properties": {
            "timeout": {"type": "number", "description": "Max seconds to wait (default 5)"},
        }}
    },
    {
        "name": "wait_for_stable_screen",
        "description": "Wait until the screen stops changing (loading/animation finished).",
        "parameters": {"type": "object", "properties": {
            "timeout": {"type": "number", "description": "Max seconds (default 8)"},
        }}
    },
    {
        "name": "detect_current_app",
        "description": (
            "Use Moondream2 to identify what app is currently open and whether UIA works on it. "
            "Call this at the start of any subtask on an unfamiliar app."
        ),
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "read_text_at",
        "description": "Read text from a specific screen region using vision (OCR-like).",
        "parameters": {"type": "object", "properties": {
            "x":      {"type": "integer", "description": "Center X of region"},
            "y":      {"type": "integer", "description": "Center Y of region"},
            "width":  {"type": "integer", "description": "Region width (default 300)"},
            "height": {"type": "integer", "description": "Region height (default 50)"},
        }, "required": ["x","y"]}
    },

    # Multi-monitor tools
    {
        "name": "list_monitors",
        "description": "List all connected monitors with their resolutions and positions.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "capture_monitor",
        "description": "Take a screenshot of a specific monitor by index.",
        "parameters": {"type": "object", "properties": {
            "monitor_index": {"type": "integer", "description": "1 for primary, 2 for second, etc."},
        }, "required": ["monitor_index"]}
    },
    {
        "name": "move_window_to_monitor",
        "description": "Move an application window to a different monitor.",
        "parameters": {"type": "object", "properties": {
            "window_title":   {"type": "string"},
            "monitor_index":  {"type": "integer"},
        }, "required": ["window_title","monitor_index"]}
    },
    {
        "name": "list_window_locations",
        "description": "List all open windows and which monitor each is on.",
        "parameters": {"type": "object", "properties": {}}
    },

    # Trigger management
    {
        "name": "schedule_time_trigger",
        "description": "Schedule a task to run automatically at a specific time each day.",
        "parameters": {"type": "object", "properties": {
            "time":  {"type": "string", "description": "Time in HH:MM format, e.g. '09:00'"},
            "goal":  {"type": "string", "description": "What to do when trigger fires"},
            "days":  {"type": "string", "description": "Comma-separated days: 'Mon,Tue,Wed' or empty for daily"},
        }, "required": ["time","goal"]}
    },
    {
        "name": "schedule_file_trigger",
        "description": "Run a task automatically when a new file appears in a folder.",
        "parameters": {"type": "object", "properties": {
            "watch_path":    {"type": "string", "description": "Directory to watch"},
            "file_pattern":  {"type": "string", "description": "Glob pattern: '*.pdf', 'report*'"},
            "goal_template": {"type": "string", "description": "Goal to run. Use {file_path} for the new file's path"},
        }, "required": ["watch_path","file_pattern","goal_template"]}
    },
    {
        "name": "schedule_app_trigger",
        "description": "Run a task automatically when a specific application OPENS (e.g. when Chrome starts).",
        "parameters": {"type": "object", "properties": {
            "app_process":   {"type": "string", "description": "Process name: 'chrome.exe', 'slack.exe', 'code.exe'"},
            "goal_template": {"type": "string", "description": "Goal to run. Use {app_name} for the process name"},
        }, "required": ["app_process","goal_template"]}
    },
    {
        "name": "schedule_clipboard_trigger",
        "description": "Run a task automatically when clipboard content changes and matches a pattern.",
        "parameters": {"type": "object", "properties": {
            "pattern":       {"type": "string", "description": "Regex pattern to match clipboard content"},
            "goal_template": {"type": "string", "description": "Goal to run. Use {clipboard} for clipboard text"},
        }, "required": ["pattern","goal_template"]}
    },
    {
        "name": "list_triggers",
        "description": "List all active scheduled triggers.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "remove_trigger",
        "description": "Remove a scheduled trigger by its ID.",
        "parameters": {"type": "object", "properties": {
            "trigger_id": {"type": "string"},
        }, "required": ["trigger_id"]}
    },
])