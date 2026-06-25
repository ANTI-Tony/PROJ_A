#!/usr/bin/env python3
"""
Test the central claim: price ⊥ quality ⊥ latency ⊥ reliability.

WITHIN each (model x task) cell (so "same model" holds), compute Spearman rank
correlation of provider PRICE against accuracy, latency, and availability.
Aggregate across cells. Near-zero => the claim holds; large |r| => it doesn't.
Pure stdlib (manual Spearman with tie-averaged ranks). Run: python3 correlations.py
"""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
m = json.load(open(os.path.join(HERE, "data", "quality_map.json")))

def avg_ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0]*len(xs); i = 0
    while i < len(xs):
        j = i
        while j+1 < len(xs) and xs[order[j+1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j+1):
            ranks[order[k]] = r
        i = j+1
    return ranks

def pearson(a, b):
    n = len(a); ma = sum(a)/n; mb = sum(b)/n
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    da = sum((x-ma)**2 for x in a)**0.5; db = sum((x-mb)**2 for x in b)**0.5
    return num/(da*db) if da > 0 and db > 0 else None

def spearman(a, b):
    if len(a) < 3:
        return None
    return pearson(avg_ranks(a), avg_ranks(b))

def collect(metric_key, invert=False):
    """Return per-cell spearman(price, metric). invert: availability/latency sign note handled by caller."""
    out = []
    for model in m:
        for task in m[model]:
            provs = list(m[model][task].values())
            price = [p["price_1m"] for p in provs if p["price_1m"] > 0]
            met = []
            ok = True
            for p in provs:
                if p["price_1m"] <= 0:
                    continue
                v = p.get(metric_key)
                if v is None:
                    ok = False; break
                met.append(v)
            if not ok or len(price) < 3:
                continue
            r = spearman(price, met)
            if r is not None:
                out.append((f"{model.split('/')[-1]}/{task}", r, len(price)))
    return out

def summarize(name, rows, hyp):
    rs = [r for _, r, _ in rows]
    if not rs:
        print(f"{name}: no cells with variance"); return
    rs_sorted = sorted(rs)
    mean = sum(rs)/len(rs); med = rs_sorted[len(rs)//2]
    strong = sum(1 for r in rs if abs(r) > 0.5)
    print(f"\n{name}  ({len(rs)} cells with variance)")
    print(f"  mean Spearman = {mean:+.2f} | median = {med:+.2f} | "
          f"range [{min(rs):+.2f},{max(rs):+.2f}] | |r|>0.5 in {strong}/{len(rs)} cells")
    print(f"  → {hyp}")

print("Within-(model×task) Spearman rank correlation vs PRICE")
print("="*64)
acc = collect("accuracy")
lat = collect("latency")
av  = collect("availability")
summarize("price vs ACCURACY", acc,
          "if ~0: paying more does NOT buy quality (⊥ holds)")
summarize("price vs LATENCY", lat,
          "if ~0: paying more does NOT buy speed (⊥ holds)")
summarize("price vs AVAILABILITY", av,
          "if ~0: paying more does NOT buy reliability (⊥ holds)")

# show the most price-correlated cells (where the claim is weakest) — honesty
print("\nCells where price MOST predicts accuracy (claim weakest):")
for name, r, n in sorted(acc, key=lambda x: -abs(x[1]))[:5]:
    print(f"  {name:<34} r={r:+.2f} (n={n})")
print("\nNote: cells with saturated accuracy (all-100%) have zero quality variance and "
      "are excluded above — there, price trivially cannot buy quality either.")
