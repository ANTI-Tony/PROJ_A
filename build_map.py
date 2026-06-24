#!/usr/bin/env python3
"""
Consolidate all data/quality_*.json into a single queryable quality-equivalence map:
  quality_map.json :  model -> task -> provider -> {accuracy, price_1m, latency, availability, quant, utc}

This map IS the asset: the product's routing substrate AND the paper's dataset.
Prints a dispersion summary (one row per model x task) — the moat visualization / paper table.

Usage: python3 build_map.py
"""
import json, glob, os
from collections import defaultdict

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")

def main():
    files = [f for f in sorted(glob.glob(os.path.join(DATA, "quality_*.json")))
             if not f.endswith("quality_map.json")]
    m = defaultdict(lambda: defaultdict(dict))   # model -> task -> provider -> rec
    for f in files:
        d = json.load(open(f))
        model, task, utc = d["model"], d.get("probe_set", "?"), d.get("utc", "")
        if task == "hard": task = "math"   # normalize legacy label
        for r in d["results"]:
            if r.get("accuracy") is None:
                continue
            prov = r["provider"]
            prev = m[model][task].get(prov)
            if prev and prev["utc"] >= utc:
                continue  # keep most recent measurement
            m[model][task][prov] = {
                "accuracy": r["accuracy"], "price_1m": round(r["price_1m"], 4),
                "latency": r.get("mean_latency"), "availability": r.get("availability"),
                "quant": r.get("quant"), "served": r.get("served"), "utc": utc}

    out = os.path.join(DATA, "quality_map.json")
    json.dump(m, open(out, "w"), indent=2)

    print(f"Consolidated {len(files)} runs -> {out}\n")
    print(f"{'model':<38}{'task':<15}{'#prov':>5}{'acc range':>12}{'price x':>8}{'lat x':>7}  cheapest-equiv")
    print("-" * 110)
    rows = 0
    for model in sorted(m):
        for task in sorted(m[model]):
            provs = m[model][task]
            accs = [r["accuracy"] for r in provs.values()]
            prices = [r["price_1m"] for r in provs.values() if r["price_1m"] > 0]
            lats = [r["latency"] for r in provs.values() if r["latency"]]
            best = max(accs)
            floor = best - 0.05
            # cheapest provider that is quality-equivalent AND healthy
            eq = [(p, r) for p, r in provs.items()
                  if r["accuracy"] >= floor and (r["availability"] or 1) >= 0.9 and r["price_1m"] > 0]
            cheap = min(eq, key=lambda x: x[1]["price_1m"]) if eq else None
            pr_x = (max(prices)/min(prices)) if len(prices) > 1 else 1
            lt_x = (max(lats)/min(lats)) if len(lats) > 1 else 1
            cheapest = f"{cheap[0]} ${cheap[1]['price_1m']:.3f} ({cheap[1]['accuracy']:.0%})" if cheap else "-"
            short = model.split("/")[-1]
            print(f"{short:<38}{task:<15}{len(provs):>5}"
                  f"{min(accs):>6.0%}-{best:<5.0%}{pr_x:>7.1f}x{lt_x:>6.1f}x  {cheapest}")
            rows += 1
    print(f"\n{rows} (model x task) cells mapped. "
          f"price/latency spreads are the arbitrage; acc range is the quality gate.")

if __name__ == "__main__":
    main()
