"""
UI Tree Utilities
=================
Deep extraction, smart compression, multi-strategy element search.
"""

from __future__ import annotations
import uiautomation as auto
from typing import Optional
from config import UIA_MAX_DEPTH, UIA_MAX_CHILDREN


# Control types worth including in compressed view
ACTIONABLE_TYPES = {
    "Button", "MenuItem", "MenuBar", "Menu",
    "Edit", "Document", "ComboBox", "ListItem", "List",
    "CheckBox", "RadioButton", "Slider", "Tab", "TabItem",
    "TreeItem", "DataItem", "Hyperlink", "ToolBar",
    "Text", "Image", "SplitButton", "ToggleButton",
}

SKIP_NAMES = {"", " ", "SystemMenuBar"}


# ──────────────────────────────────────────────────────────────
# EXTRACTION
# ──────────────────────────────────────────────────────────────
def extract_tree(control,
                 depth: int = 0,
                 max_depth: int = UIA_MAX_DEPTH,
                 max_children: int = UIA_MAX_CHILDREN) -> dict:
    """Recursively extract the full UI tree."""
    if depth > max_depth:
        return None

    try:
        node = {
            "type":          control.ControlTypeName,
            "name":          control.Name,
            "automation_id": control.AutomationId,
            "class_name":    control.ClassName,
            "children":      []
        }
    except Exception:
        return None

    try:
        children = control.GetChildren()
        for child in children[:max_children]:
            child_node = extract_tree(child, depth + 1, max_depth, max_children)
            if child_node:
                node["children"].append(child_node)
    except Exception:
        pass

    return node


def compress_tree(tree: dict) -> dict:
    """
    Remove noise from the UI tree before sending to LLM.
    Keeps only actionable elements and elements with IDs.
    Reduces token usage by ~60%.
    """
    if not tree:
        return {}

    def _compress(node: dict, is_root: bool = False) -> Optional[dict]:
        if not node:
            return None

        control_type = node.get("type", "")
        name         = node.get("name", "").strip()
        aid          = node.get("automation_id", "").strip()

        compressed_children = []
        for child in node.get("children", []):
            c = _compress(child)
            if c:
                compressed_children.append(c)

        is_actionable   = control_type in ACTIONABLE_TYPES
        has_id          = bool(aid)
        has_name        = name and name not in SKIP_NAMES
        has_children    = len(compressed_children) > 0

        if not (is_root or is_actionable or has_id or has_children):
            return None

        result = {}
        if name and name not in SKIP_NAMES:
            result["name"] = name
        if control_type:
            result["type"] = control_type
        if aid:
            result["id"] = aid
        if compressed_children:
            result["children"] = compressed_children

        return result

    return _compress(tree, is_root=True) or {}


def get_window_list() -> list[dict]:
    """Return all top-level windows with their titles."""
    root = auto.GetRootControl()
    windows = []
    try:
        for w in root.GetChildren():
            name = w.Name.strip()
            if name:
                windows.append({
                    "title":         name,
                    "class":         w.ClassName,
                    "automation_id": w.AutomationId,
                })
    except Exception:
        pass
    return windows


# ──────────────────────────────────────────────────────────────
# ELEMENT FINDING
# ──────────────────────────────────────────────────────────────
def find_element_by(root,
                    automation_id: Optional[str] = None,
                    name:          Optional[str] = None,
                    control_type:  Optional[str] = None) -> Optional[object]:
    """
    Multi-strategy element finder.
    1. automation_id (fastest, most reliable)
    2. name + control_type
    3. name only
    4. Deep recursive search (fallback)
    """
    if not root:
        return None

    # Strategy 1: automation_id
    if automation_id:
        try:
            el = root.Control(AutomationId=automation_id)
            if el.Exists(0, 0):
                return el
        except Exception:
            pass

    # Strategy 2: name + control_type
    if name and control_type:
        try:
            ct = _control_type_const(control_type)
            el = root.Control(Name=name, ControlType=ct)
            if el.Exists(0, 0):
                return el
        except Exception:
            pass

    # Strategy 3: name only
    if name:
        try:
            el = root.Control(Name=name)
            if el.Exists(0, 0):
                return el
        except Exception:
            pass

    # Strategy 4: deep recursive
    return _deep_find(root, automation_id=automation_id, name=name)


def _deep_find(control, automation_id=None, name=None,
               depth=0, max_depth=12) -> Optional[object]:
    """Recursive tree walk to find an element."""
    if depth > max_depth:
        return None
    try:
        if automation_id and control.AutomationId == automation_id:
            return control
        if name and control.Name == name:
            return control
        for child in control.GetChildren():
            result = _deep_find(child, automation_id, name, depth+1, max_depth)
            if result:
                return result
    except Exception:
        pass
    return None


def _control_type_const(type_name: str):
    type_map = {
        "Button":      auto.ControlType.ButtonControl,
        "Edit":        auto.ControlType.EditControl,
        "Text":        auto.ControlType.TextControl,
        "MenuItem":    auto.ControlType.MenuItemControl,
        "Menu":        auto.ControlType.MenuControl,
        "ComboBox":    auto.ControlType.ComboBoxControl,
        "ListItem":    auto.ControlType.ListItemControl,
        "List":        auto.ControlType.ListControl,
        "CheckBox":    auto.ControlType.CheckBoxControl,
        "RadioButton": auto.ControlType.RadioButtonControl,
        "Tab":         auto.ControlType.TabControl,
        "TabItem":     auto.ControlType.TabItemControl,
        "TreeItem":    auto.ControlType.TreeItemControl,
        "Hyperlink":   auto.ControlType.HyperlinkControl,
        "Document":    auto.ControlType.DocumentControl,
    }
    return type_map.get(type_name, auto.ControlType.ButtonControl)