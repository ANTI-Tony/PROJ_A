#!/usr/bin/env python3
"""
Savings & Safety Audit — the product's FRONT DOOR (wedge).

Reads the measured quality_map.json and produces a one-page, customer-readable report:
  - how much you OVERPAY by picking a premium/default provider (router saves X% at equal quality)
  - where picking the CHEAPEST silently drops quality (the trap) — per (model, task)
  - which providers are UNRELIABLE / SLOW
No integration required: it's the "here's your number" report that earns the meeting.

Usage:
  python3 audit.py                      # audit the whole measured map
  python3 audit.py meta-llama/llama-3.3-70b-instruct   # filter to one model
Writes data/audit_report.md and prints a summary.
"""
import json, os, sys

HERE = os.path.dirname(__file__)
MAP = os.path.join(HERE, "data", "quality_map.json")

def load():
    if not os.path.exists(MAP):
        sys.exit("No quality_map.json. Run: python3 build_map.py")
    return json.load(open(MAP))

def analyze_cell(provs, floor_drop=0.05, min_avail=0.9):
    rows = [{"provider": p, **r} for p, r in provs.items()
            if r.get("price_1m", 0) > 0 and r.get("accuracy") is not None]
    if not rows:
        return None
    best = max(r["accuracy"] for r in rows)
    floor = best - floor_drop
    equiv_healthy = [r for r in rows
                     if r["accuracy"] >= floor and (r.get("availability") or 1) >= min_avail]
    router = min(equiv_healthy, key=lambda r: r["price_1m"]) if equiv_healthy else None
    premium = max(rows, key=lambda r: r["price_1m"])              # "play it safe, pay up" buyer
    cheapest = min(rows, key=lambda r: r["price_1m"])             # "sort by price" buyer
    lat = [r["latency"] for r in rows if r.get("latency")]
    return {
        "best": best, "floor": floor, "router": router, "premium": premium,
        "cheapest": cheapest, "n": len(rows),
        "save_vs_premium": ((premium["price_1m"] - router["price_1m"]) / premium["price_1m"]
                            if router and premium["price_1m"] else 0),
        "quality_trap": cheapest["accuracy"] < floor,
        "trap_drop": cheapest["accuracy"] - best,
        "lat_x": (max(lat)/min(lat)) if len(lat) > 1 else 1,
        "unreliable": [r for r in rows if (r.get("availability") or 1) < min_avail],
    }

def main():
    m = load()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    lines = ["# Savings & Safety Audit", "",
             "_Measured across competing providers per (model, task). "
             "Price ⊥ quality ⊥ latency ⊥ reliability — you cannot pick from the price list._", ""]
    tot_cells = traps = 0
    save_pcts = []
    for model in sorted(m):
        if only and model != only:
            continue
        lines.append(f"## {model}")
        for task in sorted(m[model]):
            a = analyze_cell(m[model][task])
            if not a or not a["router"]:
                continue
            tot_cells += 1
            save_pcts.append(a["save_vs_premium"])
            r, pr, ch = a["router"], a["premium"], a["cheapest"]
            lines.append(f"- **{task}** ({a['n']} providers): route to **{r['provider']}** "
                         f"(${r['price_1m']:.3f}/1M, {r['accuracy']:.0%}, {r.get('quant')}). "
                         f"Premium pick {pr['provider']} costs ${pr['price_1m']:.3f}/1M → "
                         f"**save {a['save_vs_premium']:.0%}** at equal quality. "
                         f"Latency varies {a['lat_x']:.0f}×.")
            if a["quality_trap"]:
                traps += 1
                lines.append(f"    - ⚠️ **Quality trap:** the cheapest ({ch['provider']}, "
                             f"${ch['price_1m']:.3f}/1M) scores {ch['accuracy']:.0%} = "
                             f"**{a['trap_drop']:+.0%} vs best** (below the {a['floor']:.0%} floor). "
                             f"'Route to cheapest' silently degrades here.")
            if a["unreliable"]:
                u = ", ".join(f"{x['provider']} ({(x.get('availability') or 0):.0%} avail)"
                              for x in a["unreliable"])
                lines.append(f"    - ⚠️ **Unreliable at probe time:** {u}.")
        lines.append("")
    headline = (f"**Across {tot_cells} (model×task) workloads: median **{sorted(save_pcts)[len(save_pcts)//2]:.0%}** "
                f"savings vs premium picks at equal measured quality; "
                f"{traps} workloads where 'route to cheapest' silently drops below the quality floor.**"
                if save_pcts else "No cells.")
    lines.insert(3, headline); lines.insert(4, "")
    report = "\n".join(lines)
    out = os.path.join(HERE, "data", "audit_report.md")
    open(out, "w").write(report)
    print(report)
    print(f"\n[written -> {out}]")

if __name__ == "__main__":
    main()
