"""
Full OS Agent v4 — Fixed
=========================
Fix: robust import bootstrap so this runs correctly regardless of
     how the user has organized their files.
"""

from __future__ import annotations
import os, sys, json, time
from datetime import datetime
from pathlib import Path

# ── Bootstrap: make sure subpackages are findable ─────────────
# Add the agent's own directory to sys.path so all subpackage
# imports (core.executor, safety.safety, etc.) resolve correctly
# no matter where Python is invoked from.
_AGENT_DIR = Path(__file__).parent.resolve()
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import google.generativeai as genai
import uiautomation as auto

from config import (
    GOOGLE_API_KEY, GEMINI_PLANNER_MODEL,
    MAX_STEPS, STEP_DELAY, MEMORY_ENABLED,
    CONFIRM_ALL_ACTIONS, AUTONOMOUS_HIGH_RISK_ACTIONS,
    RECOVERY_VISION_FALLBACK, RECOVERY_HUMAN_ESCALATION,
    VERIFY_CONFIDENCE_THRESHOLD, VERIFY_MAX_RETRIES,
    GROUNDING_ENABLED, SCREEN_CHANGE_DETECTION,
    HIERARCHICAL_PLANNING,
    BACKTRACK_ENABLED, MULTI_MONITOR_ENABLED,
)
from tools       import TOOLS
from executor    import execute_action, execute_scratchpad_action, execute_v4_action
from logger      import AgentLogger
from tree_utils  import extract_tree, compress_tree
from safety    import (
    check_action, SafetyError, ConfirmationRequired, request_confirmation
)
from recovery           import RecoveryManager
from memory                import AgentMemory
from vision                import VisionEngine
from grounding             import GroundingEngine
from planner              import decompose_goal, show_plan
from hierarchical_planner import (
    decompose_hierarchical, choose_plan_type,
    display_hierarchical_plan, PhaseStatus,
)
from working_memory       import WorkingMemory
from verifier             import SubtaskVerifier
from backtracker          import BacktrackEngine, BacktrackLevel
from multi_monitor        import get_monitor_manager
from scheduler           import TriggerScheduler

os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
genai.configure(api_key=GOOGLE_API_KEY)
_model = genai.GenerativeModel(GEMINI_PLANNER_MODEL)

# ── Action sets ────────────────────────────────────────────────
_SCRATCHPAD_ACTIONS = {
    "scratchpad_write", "scratchpad_read", "scratchpad_read_all",
    "add_note", "subtask_complete", "subtask_failed",
}
_V4_ACTIONS = {
    "vision_click", "vision_find", "click_at_coordinates",
    "wait_for_screen_change", "wait_for_stable_screen",
    "detect_current_app", "read_text_at",
    "list_monitors", "capture_monitor",
    "move_window_to_monitor", "list_window_locations",
    "schedule_time_trigger", "schedule_file_trigger",
    "schedule_app_trigger", "schedule_clipboard_trigger",
    "list_triggers", "remove_trigger",
}

# ──────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a world-class Windows OS automation agent.

TWO interaction modes:
  UIA mode    — automation_id / name  (fast for traditional apps)
  Vision mode — vision_click("description")  (works on ANY app, including Electron)

WHEN TO SWITCH:
  • Start with UIA (click, set_value, etc.)
  • If element not found OR app is Electron/modern → use vision_click()
  • After opening an app → wait_for_stable_screen()
  • Before switching apps → scratchpad_write() any values you need

━━━━━━━━━━ MANDATORY RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ONE function call per turn. NEVER output plain text.
2. list_open_windows() before opening anything new.
3. App not open → open_application() FIRST.
4. After open → wait_for_element() or wait_for_stable_screen().
5. UIA fails → vision_click() with clear visual description.
6. Before switching apps → scratchpad_write() values needed later.
7. Start each subtask → scratchpad_read_all() to recall prior data.
8. Subtask done → subtask_complete() with summary.
9. Subtask impossible → subtask_failed() with specific reason.

━━━━━━━━━━ CALCULATOR AUTOMATION IDs ━━━━━━━━━━━━━━━━━━━━━━━━━
  num0-num9, plus, minus, multiply, divide
  equals, clearEntry, clear, negate, decimalSeparator

━━━━━━━━━━ VISION CLICK EXAMPLES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  vision_click("File menu in the top menu bar")
  vision_click("blue Save button in toolbar")
  vision_click("search bar at top of window")
  vision_click("X close button top right")
"""

# ──────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ──────────────────────────────────────────────────────────────
def build_prompt(goal, subtask, num, total, wm, tree, hints, step, phase=""):
    compressed = compress_tree(tree)
    wm_section = wm.to_prompt_section()
    hints_str  = ("HINTS / RECOVERY:\n" + "\n\n".join(hints) + "\n\n") if hints else ""
    phase_line = f"  Phase    : {phase}\n" if phase else ""
    return (
        f"{SYSTEM_PROMPT}\n{'═'*62}\n"
        f"OVERALL GOAL : {goal}\n"
        f"STEP         : {step}/{MAX_STEPS}\n"
        f"{'═'*62}\n\n"
        f"CURRENT SUBTASK ({num}/{total}):\n"
        f"{phase_line}"
        f"  Title    : {subtask.title}\n"
        f"  Do this  : {subtask.description}\n"
        f"  Apps     : {', '.join(subtask.apps_needed) or 'any'}\n"
        f"  Done when: {subtask.success_criterion}\n\n"
        f"{wm_section + chr(10)*2 if wm_section else ''}"
        f"{hints_str}"
        f"RECENT ACTIONS:\n{wm.format_history_for_prompt()}\n\n"
        f"ACTIVE WINDOW UI TREE:\n{json.dumps(compressed, indent=2)}\n"
    )

# ──────────────────────────────────────────────────────────────
# SUBTASK RUNNER
# ──────────────────────────────────────────────────────────────
def run_subtask(
    goal, subtask, num, total, phase_title,
    wm, vision, grounding, verifier, memory, logger,
    recovery, chat, monitor_mgr, scheduler, gstep,
):
    hints        = []
    screen_state = grounding.capture_state() if (GROUNDING_ENABLED and grounding) else None
    max_s        = min(MAX_STEPS, 14)

    print(f"\n  {'▶'*3} Subtask {num}/{total}: {subtask.title}")

    for _ in range(max_s):
        step = gstep[0]; gstep[0] += 1
        print(f"\n    Step {step} | {subtask.title[:45]}")

        # Perception
        try:    tree = extract_tree(auto.GetForegroundControl())
        except: tree = {"type":"Unknown","name":"","children":[]}

        # Warn if UIA tree looks empty (Electron app)
        if grounding and grounding.is_uia_empty(tree) and not hints:
            hints.append(
                "⚠️  UIA tree appears empty — app may be Electron-based.\n"
                "Use vision_click() for all interactions.\n"
                "Call detect_current_app() first to confirm."
            )

        prompt = build_prompt(goal, subtask, num, total, wm, tree, hints, step, phase_title)
        hints  = []

        # LLM
        try:    response = chat.send_message(prompt, tools=TOOLS)
        except Exception as e:
            print(f"    ⚠️  LLM error: {e}"); recovery.record_no_tool_call(); time.sleep(2); continue

        if not (response.candidates and response.candidates[0].content.parts):
            recovery.record_no_tool_call()
            _no_tool_hint(recovery, vision, hints, step, subtask.description); continue

        part = response.candidates[0].content.parts[0]
        if not hasattr(part, "function_call"):
            recovery.record_no_tool_call()
            _no_tool_hint(recovery, vision, hints, step, subtask.description); continue

        action = part.function_call.name
        args   = dict(part.function_call.args)
        recovery.record_action(action)
        print(f"    🔧 {action}  {json.dumps(args)[:100]}")

        # ── Scratchpad (no safety gate) ────────────────────────
        if action in _SCRATCHPAD_ACTIONS:
            result, done = execute_scratchpad_action(action, args, wm)
            print(f"    ✅ {result[:120]}")
            wm.add_action(step, action, args, result)
            logger.log_action(step, action, args, result)
            if done:
                if "SUBTASK_COMPLETE" in result:
                    return _verify(subtask, result, verifier, hints)
                return False, result.replace("SUBTASK_FAILED: ", "")
            continue

        # ── V4 vision / monitor / trigger actions ──────────────
        if action in _V4_ACTIONS:
            result, done, new_state = execute_v4_action(
                action, args,
                grounding_engine=grounding,
                monitor_manager=monitor_mgr,
                scheduler=scheduler,
                vision=vision,
                prev_screen_state=screen_state,
            )
            if result is not None:
                print(f"    ✅ {result[:150]}")
                if new_state: screen_state = new_state
                wm.add_action(step, action, args, result)
                logger.log_action(step, action, args, result)
                if done: return True, result
                continue

        # ── Safety check ───────────────────────────────────────
        try:
            check_action(action, args)
        except ConfirmationRequired as exc:
            if not CONFIRM_ALL_ACTIONS and action not in AUTONOMOUS_HIGH_RISK_ACTIONS:
                pass  # auto-approve in plan-approval mode
            else:
                if not request_confirmation(exc):
                    hints.append(f"User denied '{action}'. Try a different approach.")
                    wm.add_action(step, action, args, "Denied"); continue
        except SafetyError as exc:
            msg = f"SAFETY BLOCK: {exc}"
            print(f"    🚫 {msg}")
            hints.append(f"Safety blocked. Try differently.\n{exc}")
            wm.add_action(step, action, args, msg)
            logger.log_action(step, action, args, msg, blocked=True); continue

        # ── Execute ────────────────────────────────────────────
        if SCREEN_CHANGE_DETECTION and grounding:
            pre = grounding.capture_state()

        try:    result, terminal = execute_action(action, args, memory=memory, vision=vision)
        except Exception as e: result = f"Execution error: {e}"; terminal = False

        # Screen-change feedback
        if SCREEN_CHANGE_DETECTION and grounding:
            time.sleep(0.3)
            changed, screen_state = grounding.has_screen_changed(pre)
            if not changed and action in ("click","double_click","press_key","browser_click"):
                hints.append(
                    "⚠️  Screen did NOT change after click — may not have registered.\n"
                    "Try vision_click() instead."
                )

        print(f"    ✅ {result[:160]}")
        wm.add_action(step, action, args, result)
        logger.log_action(step, action, args, result)
        if memory: memory.log_action(step, action, args, result)
        if terminal: return "COMPLETE" in result, result

        # Recovery
        is_fail = any(t in result.lower() for t in
            ["not found","failed","error","timed out","does not exist"])
        if is_fail:
            rec  = recovery.record_failure(action, args, result, step)
            hint = recovery.build_semantic_hint(rec)
            if hint: hints.append(hint)
            if recovery.should_use_vision(result) and RECOVERY_VISION_FALLBACK and vision:
                desc = vision.describe_screen(focus=subtask.description)
                hints.append(recovery.build_vision_hint(desc, step))

        if recovery.is_stuck():
            if RECOVERY_VISION_FALLBACK and vision:
                desc = vision.describe_screen(focus=subtask.description)
                hints.append(recovery.build_vision_hint(desc, step))
                hints.append("Stuck — try a completely different approach.")
            recovery.reset_stuck()
            if recovery.should_escalate() and RECOVERY_HUMAN_ESCALATION:
                h = recovery.escalate_to_human(context=subtask.description)
                if h is None: return False, "User quit."
                if h: hints.append(h)

        time.sleep(STEP_DELAY)

    return False, f"Subtask hit max steps ({max_s})"


def _verify(subtask, result, verifier, hints):
    print(f"\n    👁️  Moondream2 verifying: {subtask.title}...")
    for attempt in range(1, VERIFY_MAX_RETRIES + 1):
        vr = verifier.verify(subtask.title, subtask.success_criterion)
        print(f"    📊 passed={vr.passed} confidence={vr.confidence:.2f}")
        if vr.passed and vr.confidence >= VERIFY_CONFIDENCE_THRESHOLD:
            print("    ✅ Verified\n")
            return True, result.replace("SUBTASK_COMPLETE: ", "")
        if vr.suggestion: hints.append(f"Verify failed: {vr.observation}\nTry: {vr.suggestion}")
        time.sleep(0.8)
    print("    ⚠️  Low confidence — accepting anyway")
    return True, result.replace("SUBTASK_COMPLETE: ", "") + " (low conf)"


def _no_tool_hint(recovery, vision, hints, step, ctx):
    if recovery.is_stuck() and RECOVERY_VISION_FALLBACK and vision:
        desc = vision.describe_screen(focus=ctx)
        hints.append(recovery.build_vision_hint(desc, step))
        hints.append("You returned text instead of a function. Call a function NOW.")
        recovery.reset_stuck()

# ──────────────────────────────────────────────────────────────
# PHASE RUNNER  (hierarchical — fresh chat per phase)
# ──────────────────────────────────────────────────────────────
def run_phase(
    goal, phase, pnum, ptotal,
    wm, vision, grounding, verifier, memory, logger,
    recovery, monitor_mgr, scheduler, backtracker, gstep,
):
    print(f"\n{'━'*62}")
    print(f"  PHASE {pnum}/{ptotal}: {phase.title}")
    print(f"  Checkpoint: {phase.checkpoint}")
    print(f"{'━'*62}")

    chat      = _model.start_chat(enable_automatic_function_calling=False)
    subtasks  = list(enumerate(phase.subtasks, 1))
    i = 0

    while i < len(subtasks):
        local_num, subtask = subtasks[i]

        if subtask.status != PhaseStatus.PENDING:
            i += 1; continue

        done_ids = {s.id for s in phase.subtasks if s.status == PhaseStatus.COMPLETE}
        if not all(d in done_ids for d in subtask.depends_on):
            i += 1; continue

        subtask.status = PhaseStatus.RUNNING
        ok, result = run_subtask(
            goal, subtask, local_num, len(phase.subtasks), phase.title,
            wm, vision, grounding, verifier, memory, logger,
            recovery, chat, monitor_mgr, scheduler, gstep,
        )

        if ok:
            subtask.status = PhaseStatus.COMPLETE
            subtask.result = result
            print(f"  ✅ {subtask.title}")
            i += 1
        else:
            subtask.status = PhaseStatus.FAILED
            subtask.result = result
            print(f"  ❌ {subtask.title} → {result[:60]}")

            if backtracker:
                decision = backtracker.decide(
                    failed_subtask_id=subtask.id,
                    failed_phase_id=phase.id,
                    failure_reason=result,
                    has_previous_subtask=(i > 0),
                )
                print(f"  🔄 {decision.level.value}: {decision.reason[:55]}")

                if decision.level == BacktrackLevel.RETRY_SUBTASK:
                    subtask.status = PhaseStatus.PENDING; subtask.result = None
                    continue
                elif decision.level == BacktrackLevel.REDO_PREVIOUS and i > 0:
                    prev = subtasks[i-1][1]
                    prev.status = PhaseStatus.PENDING; prev.result = None
                    subtask.status = PhaseStatus.PENDING; subtask.result = None
                    i = max(0, i-1); continue
                elif decision.level == BacktrackLevel.ESCALATE:
                    if RECOVERY_HUMAN_ESCALATION:
                        h = recovery.escalate_to_human(context=subtask.description)
                        if h is None: return False, "User quit."
                        if h:
                            subtask.status = PhaseStatus.PENDING; subtask.result = None; continue
            i += 1

    return not phase.has_failures(), f"Phase {pnum} done"

# ──────────────────────────────────────────────────────────────
# MAIN AGENT
# ──────────────────────────────────────────────────────────────
_scheduler = None

def run_agent(goal: str) -> str:
    global _scheduler
    sid    = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    logger = AgentLogger()
    vision = VisionEngine()
    ground = GroundingEngine(vision) if GROUNDING_ENABLED else None
    verify = SubtaskVerifier(vision)
    recov  = RecoveryManager()
    bt     = BacktrackEngine() if BACKTRACK_ENABLED else None
    mem    = AgentMemory(sid, goal) if MEMORY_ENABLED else None
    wm     = WorkingMemory(goal)
    mon    = get_monitor_manager() if MULTI_MONITOR_ENABLED else None

    if _scheduler is None:
        _scheduler = TriggerScheduler(agent_runner=run_agent)
        _scheduler.start()

    logger.log_session_start(goal)

    print(f"\n{'╔'+'═'*62+'╗'}")
    print(f"║  🖥️  FULL OS AGENT v4                                         ║")
    print(f"║  Vision : {vision.model_name:<53}║")
    mode = "Plan-approval (autonomous)" if not CONFIRM_ALL_ACTIONS else "Confirm-all"
    print(f"║  Mode   : {mode:<53}║")
    if mon: print(f"║  Monitors: {mon.monitor_count():<52}║")
    print(f"╠{'═'*62}╣")
    print(f"║  Goal: {goal[:57]:<57}║")
    print(f"{'╚'+'═'*62+'╝'}\n")

    # Memory context
    similar = mem.search_similar_tasks(goal) if mem else []
    context = ""
    if similar:
        good = [t for t in similar if t["success"]]
        print(f"🧠 Memory: {len(similar)} similar past task(s)")
        if good: context = f"Similar past success: '{good[0]['goal']}'"

    # Choose plan type
    ptype = choose_plan_type(goal) if HIERARCHICAL_PLANNING else "flat"
    print(f"📋 Planning mode: {ptype}\n")

    gstep   = [1]
    success = False
    outcome = "Did not complete."

    if ptype == "hierarchical":
        plan = decompose_hierarchical(goal, context)
        display_hierarchical_plan(plan)

        if not CONFIRM_ALL_ACTIONS:
            try: ans = input("\n  Approve plan? [y/N]: ").strip().lower()
            except: ans = "n"
            if ans not in ("y","yes"): return "Plan rejected by user."

        for pnum, phase in enumerate(plan.phases, 1):
            done_ids = {p.id for p in plan.phases if p.status == PhaseStatus.COMPLETE}
            if not all(d in done_ids for d in phase.depends_on):
                phase.status = PhaseStatus.SKIPPED; continue

            phase.status = PhaseStatus.RUNNING
            ok, res = run_phase(
                goal, phase, pnum, len(plan.phases),
                wm, vision, ground, verify, mem, logger,
                recov, mon, _scheduler, bt, gstep,
            )
            phase.status = PhaseStatus.COMPLETE if ok else PhaseStatus.FAILED
            phase.result = res
            print(f"\n  Plan:\n{plan.summary()}")

            if not ok and RECOVERY_HUMAN_ESCALATION:
                try: ans = input(f"\n  Phase {pnum} failed. Continue? [c/a]: ").strip().lower()
                except: ans = "a"
                if ans == "a":
                    outcome = f"Aborted at phase {pnum}."; break

        done  = plan.completed_subtasks()
        total = plan.total_subtasks()
        if plan.is_complete() and not plan.has_failures():
            success = True; outcome = f"✅ All {total} subtasks completed."
        elif done > 0:
            outcome = f"⚠️  Partial: {done}/{total} subtasks completed."
        else:
            outcome = "❌ No subtasks completed."

    else:
        # Flat plan
        flat = decompose_goal(goal, context)
        show_plan(flat)

        if not CONFIRM_ALL_ACTIONS:
            try: ans = input("\n  Approve plan? [y/N]: ").strip().lower()
            except: ans = "n"
            if ans not in ("y","yes"): return "Plan rejected by user."

        chat = _model.start_chat(enable_automatic_function_calling=False)

        from planner import SubtaskStatus
        for i, st in enumerate(flat.subtasks, 1):
            st.status = SubtaskStatus.RUNNING
            ok, res = run_subtask(
                goal, st, i, len(flat.subtasks), "",
                wm, vision, ground, verify, mem, logger,
                recov, chat, mon, _scheduler, gstep,
            )
            st.status = SubtaskStatus.COMPLETE if ok else SubtaskStatus.FAILED
            st.result = res

        done  = sum(1 for s in flat.subtasks if s.status == SubtaskStatus.COMPLETE)
        total = len(flat.subtasks)
        if done == total:
            success = True; outcome = "✅ Task completed successfully."
        else:
            outcome = f"⚠️  {done}/{total} subtasks completed."

    stats = recov.stats()
    bts   = bt.get_stats() if bt else {}
    print(f"\n{'═'*64}")
    print(f"  {outcome}")
    print(f"  Steps: {gstep[0]-1}  Failures: {stats['total_failures']}"
          f"  Vision: {stats['vision_calls']}  Backtracks: {bts.get('total_backtracks',0)}")
    print(f"  Scratchpad: {wm.read_all()}")
    print(f"{'═'*64}\n")

    logger.log_session_end(outcome)
    if mem: mem.end_session(outcome, success); mem.close()
    return outcome

# ──────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║    Full OS Agent v4                                          ║")
    print("║    Vision: Moondream2 (local) → Gemini (fallback)            ║")
    print("║    Setup : ollama pull moondream                             ║")
    print("║            pip install -r requirements.txt                   ║")
    print("║                                                              ║")
    print("║    Commands: history | triggers | quit | <any goal>          ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    while True:
        try:    goal = input("🎯 Goal: ").strip()
        except KeyboardInterrupt: print("\nGoodbye."); break

        if not goal: continue
        if goal.lower() == "quit":
            if _scheduler: _scheduler.stop()
            break
        if goal.lower() == "history":
            if MEMORY_ENABLED:
                from memory import AgentMemory as AM
                m = AM("_tmp","history")
                for s in m.list_recent_sessions():
                    icon = "✅" if "COMPLETE" in str(s.get("outcome","")) else "❌"
                    print(f"  {icon} [{s['started_at'][:16]}] {s['goal']}")
                    print(f"       → {str(s.get('outcome',''))[:70]}")
                m.close()
            continue
        if goal.lower() == "triggers":
            if _scheduler:
                print(json.dumps(_scheduler.list_triggers(), indent=2))
            continue

        run_agent(goal)
        print()