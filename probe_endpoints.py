#!/usr/bin/env python3
"""
Market-Aware Routing — Validation Harness (Step 1: dispersion + churn snapshot)

Zero-cost: hits only OpenRouter's PUBLIC endpoints API (no key, no inference spend).
Answers the load-bearing empirical questions BEFORE building anything:
  Q1 price dispersion : how big is the cross-provider price spread for the SAME open model?
  Q2 churn (temporal) : run repeatedly over days -> does the cheapest-healthy provider change?
  Q4 safe savings     : naive (pick a fixed provider) vs cheapest-healthy endpoint

Each run writes a timestamped snapshot to data/snap_<utc>.json and prints a dispersion table.
Re-run on a cron (e.g. hourly) for a few days, then run analyze_churn.py over the snapshots.

This snapshot feed is ALSO the paper's ReplayEnv trace source (build-once-use-twice).
"""
import json, urllib.request, time, os, sys
from datetime import datetime, timezone

BASE = "https://openrouter.ai/api/v1"
DATA = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA, exist_ok=True)

# Open-weight models with many competing providers = where the wedge lives.
TARGETS = [
    "meta-llama/llama-3.3-70b-instruct",
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-4-maverick",
    "qwen/qwen3-235b-a22b",
    "deepseek/deepseek-chat-v3.1",
    "deepseek/deepseek-r1",
    "mistralai/mistral-small-3.2-24b-instruct",
    "google/gemma-3-27b-it",
]

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mar-validation/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def fnum(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def fetch_endpoints(model_id):
    author, slug = model_id.split("/", 1)
    url = f"{BASE}/models/{author}/{slug}/endpoints"
    try:
        data = get(url).get("data", {})
    except Exception as e:
        return {"model": model_id, "error": str(e), "endpoints": []}
    eps = []
    for e in data.get("endpoints", []):
        pr = e.get("pricing", {}) or {}
        eps.append({
            "provider": e.get("provider_name") or e.get("name"),
            "quant": e.get("quantization"),
            "ctx": e.get("context_length"),
            # prices are per-token (string) -> convert to $/1M tokens
            "price_in_1m":  (fnum(pr.get("prompt"))     or 0) * 1e6,
            "price_out_1m": (fnum(pr.get("completion")) or 0) * 1e6,
            "uptime_30m": fnum((e.get("uptime_last_30m") if "uptime_last_30m" in e else None)),
            "status": e.get("status"),
        })
    return {"model": model_id, "name": data.get("name"), "endpoints": eps}

def dispersion_row(rec):
    eps = [e for e in rec["endpoints"] if e["price_out_1m"] and e["price_out_1m"] > 0]
    if not eps:
        return None
    # blended cost proxy: 1 input : 1 output (adjust per workload later)
    for e in eps:
        e["blended"] = 0.5 * e["price_in_1m"] + 0.5 * e["price_out_1m"]
    cheap = min(eps, key=lambda e: e["blended"])
    exp   = max(eps, key=lambda e: e["blended"])
    return {
        "model": rec["model"],
        "n_providers": len(eps),
        "cheapest": (cheap["provider"], round(cheap["blended"], 3), cheap["quant"]),
        "priciest": (exp["provider"],   round(exp["blended"], 3),   exp["quant"]),
        "spread_x": round(exp["blended"] / cheap["blended"], 1) if cheap["blended"] else None,
        "quants": sorted({str(e["quant"]) for e in eps}),
    }

def main():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = {"utc": ts, "models": []}
    rows = []
    for mid in TARGETS:
        rec = fetch_endpoints(mid)
        snap["models"].append(rec)
        row = dispersion_row(rec)
        if row: rows.append(row)
        time.sleep(0.4)  # be polite
    path = os.path.join(DATA, f"snap_{ts}.json")
    json.dump(snap, open(path, "w"), indent=2)

    print(f"\nSnapshot {ts}  ->  {path}\n")
    print(f"{'model':<42}{'#prov':>6}{'spread':>8}  {'cheapest (blended $/1M, quant)':<34}quants")
    print("-" * 120)
    for r in sorted(rows, key=lambda r: -(r['spread_x'] or 0)):
        c = r["cheapest"]
        print(f"{r['model']:<42}{r['n_providers']:>6}{str(r['spread_x'])+'x':>8}  "
              f"{c[0]+' $'+str(c[1])+' '+str(c[2]):<34}{','.join(r['quants'])}")
    spreads = [r["spread_x"] for r in rows if r["spread_x"]]
    if spreads:
        print(f"\nQ1 dispersion: median spread {sorted(spreads)[len(spreads)//2]}x, "
              f"max {max(spreads)}x across {len(rows)} models.")
    print("Q2 churn: re-run over days, then analyze_churn.py over data/snap_*.json")

if __name__ == "__main__":
    main()
