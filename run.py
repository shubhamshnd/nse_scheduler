#!/usr/bin/env python3
"""
run.py — CLI entry point for manual pipeline execution.

Usage:
  python run.py                         # full pipeline
  python run.py screen                  # screen only
  python run.py screen news ai          # multiple tasks
  python run.py earnings                # earnings dashboard
  python run.py --list-tasks            # show available tasks
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

TASKS_AVAILABLE = {
    "screen":    ["screen"],
    "news":      ["news"],
    "ai":        ["ai_analysis"],
    "earnings":  ["earnings_dashboard"],
    "telegram":  ["telegram_report"],
    "full":      ["screen", "news", "ai_analysis", "earnings_dashboard", "telegram_report"],
    "scan":      ["screen", "news", "ai_analysis"],
}


def main():
    args = sys.argv[1:]

    if "--list-tasks" in args or "-l" in args:
        print("\nAvailable tasks:")
        for name, t in TASKS_AVAILABLE.items():
            print(f"  {name:<12} → {t}")
        print()
        return

    if not args:
        tasks = TASKS_AVAILABLE["full"]
        print(f"No task specified. Running full pipeline: {tasks}")
    else:
        tasks = []
        for arg in args:
            if arg in TASKS_AVAILABLE:
                tasks.extend(TASKS_AVAILABLE[arg])
            else:
                # treat as raw task name (screen, news, ai_analysis, etc.)
                tasks.append(arg)
        # deduplicate while preserving order
        seen = set()
        tasks = [t for t in tasks if not (t in seen or seen.add(t))]

    from core.config_loader import CFG
    from core.pipeline import run_tasks

    print(f"\n🚀 Running tasks: {tasks}\n{'─'*50}")
    status = run_tasks(tasks, CFG)

    print(f"\n{'─'*50}")
    print("Results:")
    for task, st in status.items():
        ok  = "✓" if st.get("ok") else "✗"
        det = {k: v for k, v in st.items() if k not in ["ok", "elapsed_s"]}
        print(f"  {ok} {task:<25} {det}  ({st.get('elapsed_s','?')}s)")
    print()


if __name__ == "__main__":
    main()
