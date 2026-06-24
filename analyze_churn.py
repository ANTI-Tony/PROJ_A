#!/usr/bin/env python3
"""
Analyze churn (Q2) over accumulated snapshots in data/snap_*.json.

The load-bearing question for BOTH the paper's "dynamic/temporal" thesis and the
product's "is this a moving target" claim:
  Does the cheapest provider for a given model CHANGE over time?
    - high churn  -> temporal/dynamic story holds; a live router beats a static pick.
    - low  churn  -> it's CROSS-SECTIONAL arbitrage (pick once), not temporal.
      (this would mean: weaken the paper's 'dynamic price' emphasis, keep the
       quality-equivalence + health wedge for the product.)

Run after you've collected several snapshots (e.g. hourly for a few days).
"""
import json, glob, os
from collections import defaultdict

DATA = os.path.join(os.path.dirname(__file__), "data")

def blended(e):
    pr = 0.5*(e.get("price_in_1m") or 0) + 0.5*(e.get("price_out_1m") or 0)
    return pr if pr > 0 else None

def cheapest(rec):
    eps = [(e["provider"], blended(e)) for e in rec["endpoints"] if blended(e)]
    return min(eps, key=lambda x: x[1])[0] if eps else None

def main():
    snaps = sorted(glob.glob(os.path.join(DATA, "snap_*.json")))
    if len(snaps) < 2:
        print(f"Only {len(snaps)} snapshot(s). Need >=2 to measure churn. "
              f"Run probe_endpoints.py repeatedly (e.g. hourly) first.")
        return
    # model -> ordered list of (utc, cheapest_provider)
    series = defaultdict(list)
    for s in snaps:
        snap = json.load(open(s))
        for rec in snap["models"]:
            c = cheapest(rec)
            if c: series[rec["model"]].append((snap["utc"], c))

    print(f"Snapshots: {len(snaps)}  ({snaps[0].split('snap_')[-1][:-5]} .. "
          f"{snaps[-1].split('snap_')[-1][:-5]})\n")
    print(f"{'model':<42}{'switches':>9}{'#distinct':>10}  cheapest-provider timeline")
    print("-" * 110)
    total_switch = total_steps = 0
    for m, seq in sorted(series.items()):
        provs = [p for _, p in seq]
        switches = sum(1 for i in range(1, len(provs)) if provs[i] != provs[i-1])
        distinct = len(set(provs))
        total_switch += switches; total_steps += max(len(provs)-1, 0)
        # compress consecutive repeats for a readable timeline
        tl, last = [], None
        for p in provs:
            if p != last: tl.append(p); last = p
        print(f"{m:<42}{switches:>9}{distinct:>10}  {' -> '.join(tl)}")
    rate = (total_switch/total_steps) if total_steps else 0
    print(f"\nChurn rate: {total_switch}/{total_steps} step-transitions changed cheapest "
          f"provider = {rate:.1%}.")
    print("Verdict: >~15% => temporal story holds (live router wins). "
          "<~5% => cross-sectional arbitrage; de-emphasize 'dynamic price' in the paper.")

if __name__ == "__main__":
    main()
