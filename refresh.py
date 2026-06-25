#!/usr/bin/env python3
"""
Refresh the LIVE market layer (the moat's freshness).

Quality is measured slowly and expensively (probe_quality.py); PRICE, latency, and uptime
change often and are FREE to re-pull. This script re-pulls them from OpenRouter /endpoints for
every model in the quality map and writes:
  data/live_market.json            — current live price/uptime/latency per (model, provider)
  data/snapshots/market_<utc>.json — timestamped history (accumulates -> enables churn analysis)
It then reports any change in the cheapest quality-equivalent provider per cell (live churn).

Zero inference cost. Run frequently (e.g. hourly via cron); re-run probe_quality weekly.
Usage: python3 refresh.py
"""
import json, os, glob, urllib.request, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MAP = os.path.join(DATA, "quality_map.json")
LIVE = os.path.join(DATA, "live_market.json")
SNAPDIR = os.path.join(DATA, "snapshots")
os.makedirs(SNAPDIR, exist_ok=True)

def fnum(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def endpoints(model):
    author, slug = model.split("/", 1)
    req = urllib.request.Request(
        f"https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints",
        headers={"User-Agent": "mar-refresh"})
    eps = json.load(urllib.request.urlopen(req, timeout=25))["data"]["endpoints"]
    out = {}
    for e in eps:
        pr = e.get("pricing", {}) or {}
        price = ((fnum(pr.get("prompt")) or 0)*0.5 + (fnum(pr.get("completion")) or 0)*0.5)*1e6
        if price <= 0:
            continue
        out[e.get("provider_name") or e.get("name")] = {
            "price_1m": round(price, 4),
            "uptime_30m": fnum(e.get("uptime_last_30m")),
            "uptime_1d": fnum(e.get("uptime_last_1d")),
            "latency_30m": fnum(e.get("latency_last_30m")),
            "status": e.get("status"),
        }
    return out

def cheapest_equiv(measured_cell, live_model, floor_drop=0.05, min_avail=0.9):
    """Cheapest provider that is measured-quality-equivalent + measured-healthy, priced LIVE."""
    accs = [p["accuracy"] for p in measured_cell.values() if p.get("accuracy") is not None]
    if not accs:
        return None
    floor = max(accs) - floor_drop
    cands = []
    for prov, meas in measured_cell.items():
        if meas.get("accuracy") is None or meas["accuracy"] < floor:
            continue
        if (meas.get("availability") or 1) < min_avail:
            continue
        price = (live_model.get(prov) or {}).get("price_1m") or meas.get("price_1m")
        if price:
            cands.append((prov, price))
    return min(cands, key=lambda x: x[1])[0] if cands else None

def main():
    m = json.load(open(MAP))
    prev = json.load(open(LIVE)) if os.path.exists(LIVE) else {}
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    live = {}
    for model in m:
        try:
            live[model] = endpoints(model)
        except Exception as e:
            live[model] = {}
            print(f"  ! {model}: {e}")
        time.sleep(0.3)

    json.dump(live, open(LIVE, "w"), indent=2)
    json.dump({"utc": ts, "market": live}, open(os.path.join(SNAPDIR, f"market_{ts}.json"), "w"))

    # churn: did the cheapest quality-equivalent provider change vs the previous refresh?
    changes = 0
    print(f"\nLive refresh {ts}  ({len(m)} models)\n")
    for model in sorted(m):
        for task in sorted(m[model]):
            now = cheapest_equiv(m[model][task], live.get(model, {}))
            was = cheapest_equiv(m[model][task], prev.get(model, {})) if prev else None
            if prev and now and was and now != was:
                changes += 1
                pn = (live.get(model, {}).get(now) or {}).get("price_1m")
                pw = (prev.get(model, {}).get(was) or {}).get("price_1m")
                print(f"  CHURN  {model.split('/')[-1]}/{task}: {was} (${pw}) -> {now} (${pn})")
    nsnap = len(glob.glob(os.path.join(SNAPDIR, "market_*.json")))
    if prev:
        print(f"\n{changes} cheapest-provider change(s) vs last refresh. {nsnap} snapshots stored.")
    else:
        print(f"First refresh: baseline stored ({nsnap} snapshot). Re-run later to detect churn.")
    print("Router now prices via data/live_market.json (quality stays from slow probes).")

if __name__ == "__main__":
    main()
