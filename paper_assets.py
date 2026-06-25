#!/usr/bin/env python3
"""
Generate the paper's experiment assets from the measured quality_map.json:
  baselines_table.tex      — policy comparison (single-best / premium / random / cheapest / ours)
  fig_price_quality.pdf     — price-vs-accuracy scatter (visual proof price does not buy quality)
Run: python3 paper_assets.py
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
m = json.load(open(os.path.join(HERE, "data", "quality_map.json")))

def cells():
    for model in m:
        for task in m[model]:
            provs = [dict(p, provider=k) for k, p in m[model][task].items()
                     if p["price_1m"] > 0 and p.get("accuracy") is not None]
            if len(provs) >= 3:
                yield model, task, provs

# ---------- baseline policies ----------
FLOOR_DROP, MIN_AVAIL = 0.05, 0.9
def pick_policies(provs):
    best = max(p["accuracy"] for p in provs); floor = best - FLOOR_DROP
    cheapest = min(provs, key=lambda p: p["price_1m"])
    premium  = max(provs, key=lambda p: p["price_1m"])
    single_best = max(provs, key=lambda p: (p["accuracy"], -p["price_1m"]))
    eq_healthy = [p for p in provs if p["accuracy"] >= floor and (p.get("availability") or 1) >= MIN_AVAIL]
    ours = min(eq_healthy, key=lambda p: p["price_1m"]) if eq_healthy else \
           max([p for p in provs if (p.get("availability") or 1) >= MIN_AVAIL] or provs, key=lambda p: p["accuracy"])
    return floor, cheapest, premium, single_best, ours

def agg():
    pol = {n: {"acc": [], "relcost": [], "below": [], "avail": []}
           for n in ["Single-best (quality-first)", "Premium (most expensive)",
                     "Random", "Cheapest (price-blind)", "\\textbf{Ours}"]}
    for model, task, provs in cells():
        floor, cheapest, premium, single_best, ours = pick_policies(provs)
        minprice = min(p["price_1m"] for p in provs)
        meanprice = sum(p["price_1m"] for p in provs)/len(provs)
        meanacc = sum(p["accuracy"] for p in provs)/len(provs)
        meanavail = sum((p.get("availability") or 1) for p in provs)/len(provs)
        meanbelow = sum(1 for p in provs if p["accuracy"] < floor)/len(provs)
        def rec(name, p):
            pol[name]["acc"].append(p["accuracy"])
            pol[name]["relcost"].append(p["price_1m"]/minprice)
            pol[name]["below"].append(1.0 if p["accuracy"] < floor else 0.0)
            pol[name]["avail"].append(p.get("availability") or 1)
        rec("Single-best (quality-first)", single_best)
        rec("Premium (most expensive)", premium)
        rec("Cheapest (price-blind)", cheapest)
        rec("\\textbf{Ours}", ours)
        pol["Random"]["acc"].append(meanacc); pol["Random"]["relcost"].append(meanprice/minprice)
        pol["Random"]["below"].append(meanbelow); pol["Random"]["avail"].append(meanavail)
    return pol

def mean(x): return sum(x)/len(x)
def write_table():
    pol = agg()
    lines = [r"\begin{tabular}{lcccc}", r"\toprule",
             r"Policy & Mean acc.\ & Rel.\ cost$^\ast$ & Below-floor & Mean avail.\ \\",
             r"\midrule"]
    order = ["Single-best (quality-first)", "Premium (most expensive)", "Random",
             "Cheapest (price-blind)", "\\textbf{Ours}"]
    for n in order:
        d = pol[n]
        lines.append(f"{n} & {mean(d['acc']):.0%} & {mean(d['relcost']):.2f}$\\times$ & "
                     f"{mean(d['below']):.0%} & {mean(d['avail']):.0%} \\\\".replace("%", "\\%"))
    lines += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(HERE, "baselines_table.tex"), "w").write("\n".join(lines))
    print("baselines_table.tex:")
    for n in order:
        d = pol[n]
        print(f"  {n:<30} acc={mean(d['acc']):.0%} relcost={mean(d['relcost']):.2f}x "
              f"below-floor={mean(d['below']):.0%} avail={mean(d['avail']):.0%}")

# ---------- figure ----------
def write_figure():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"math": "#ff8a3d", "classification": "#22d3ee", "extraction": "#34d399"}
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    seen = set()
    for model, task, provs in cells():
        minp = min(p["price_1m"] for p in provs)
        for p in provs:
            lbl = task if task not in seen else None; seen.add(task)
            ax.scatter(p["price_1m"]/minp, p["accuracy"]*100, s=26, alpha=0.7,
                       color=colors.get(task, "#888"), label=lbl, edgecolors="none")
    ax.set_xscale("log")
    ax.set_xlabel("Relative price within cell  (cheapest provider $=1$)")
    ax.set_ylabel("Accuracy (\\%)")
    ax.set_title("Same model, competing providers: price does not buy quality")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_price_quality.pdf"))
    print("fig_price_quality.pdf written")

if __name__ == "__main__":
    write_table()
    write_figure()
