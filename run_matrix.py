#!/usr/bin/env python3
"""
Thicken the quality map: run probe_quality across a (model x task) matrix.
Skips combos already measured (resumable). Run in background; then build_map.py.

Usage: python3 run_matrix.py
"""
import glob, os, sys
from probe_quality import run, TASKS

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")

# Multi-provider open models (arbitrage only exists where >1 provider competes).
MODELS = [
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat-v3.1",
    "meta-llama/llama-4-maverick",
    "mistralai/mistral-small-3.2-24b-instruct",
    "google/gemma-3-27b-it",
]
TASK_LIST = ["math", "classification", "extraction"]

def done(model, task):
    safe = model.replace("/", "_")
    if glob.glob(os.path.join(DATA, f"quality_{safe}_{task}_*.json")):
        return True
    if task == "math" and glob.glob(os.path.join(DATA, f"quality_{safe}_hard_*.json")):
        return True   # legacy 'hard' == math
    return False

def main():
    todo = [(m, t) for m in MODELS for t in TASK_LIST if not done(m, t)]
    print(f"Matrix: {len(MODELS)} models x {len(TASK_LIST)} tasks. "
          f"{len(todo)} cells to run ({len(MODELS)*len(TASK_LIST)-len(todo)} already done).\n")
    for i, (model, task) in enumerate(todo, 1):
        print(f"\n===== [{i}/{len(todo)}] {model}  task={task} =====")
        probes, scorer = TASKS[task]
        try:
            run(model, probes, task, scorer)
        except Exception as e:
            print(f"  FAILED {model}/{task}: {e}")
    print("\nMatrix done. Run: python3 build_map.py")

if __name__ == "__main__":
    main()
