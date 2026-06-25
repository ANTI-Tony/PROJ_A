#!/usr/bin/env python3
"""
Generate LaTeX from the measured quality_map.json so the paper's numbers stay in sync
with the data. Emits:
  paper/results_table.tex   — the main per-(model,task) dispersion table
  paper/stats.tex           — \newcommand macros for headline numbers used in prose
Run: python3 paper/make_tables.py
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))   # repo root (paper sources live here)
MAP = os.path.join(HERE, "data", "quality_map.json")
OUT = HERE

sys.path.insert(0, HERE)
from audit import analyze_cell  # reuse the same analysis the product uses

def esc(s): return str(s).replace("&", "\\&").replace("_", "\\_").replace("%", "\\%")

def _avg_ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i]); ranks = [0.0]*len(xs); i = 0
    while i < len(xs):
        j = i
        while j+1 < len(xs) and xs[order[j+1]] == xs[order[i]]: j += 1
        for k in range(i, j+1): ranks[order[k]] = (i+j)/2.0 + 1
        i = j+1
    return ranks

def _pearson(a, b):
    n = len(a); ma = sum(a)/n; mb = sum(b)/n
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    da = sum((x-ma)**2 for x in a)**0.5; db = sum((x-mb)**2 for x in b)**0.5
    return num/(da*db) if da > 0 and db > 0 else None

def median_price_corr(m, key):
    """Median within-cell Spearman(price, metric) over cells where the metric varies."""
    rs = []
    for model in m:
        for task in m[model]:
            provs = [p for p in m[model][task].values() if p["price_1m"] > 0 and p.get(key) is not None]
            if len(provs) < 3: continue
            pr = [p["price_1m"] for p in provs]; mt = [p[key] for p in provs]
            r = _pearson(_avg_ranks(pr), _avg_ranks(mt))
            if r is not None: rs.append(r)
    return (sorted(rs)[len(rs)//2], len(rs)) if rs else (0.0, 0)

def main():
    m = json.load(open(MAP))
    rows = []
    saves, price_x, lat_x, traps = [], [], [], 0
    for model in sorted(m):
        for task in sorted(m[model]):
            a = analyze_cell(m[model][task])
            if not a or not a["router"]:
                continue
            provs = m[model][task]
            prices = [r["price_1m"] for r in provs.values() if r["price_1m"] > 0]
            accs = [r["accuracy"] for r in provs.values()]
            pxx = max(prices)/min(prices) if len(prices) > 1 else 1
            rows.append((model.split("/")[-1], task, a["n"], min(accs), max(accs),
                         pxx, a["lat_x"], a["router"]["price_1m"], a["save_vs_premium"],
                         a["quality_trap"]))
            saves.append(a["save_vs_premium"]); price_x.append(pxx); lat_x.append(a["lat_x"])
            if a["quality_trap"]:
                traps += 1

    # main table
    lines = [r"\begin{tabular}{llrccccr}", r"\toprule",
             r"Model & Task & $|P|$ & Acc.\ range & Price$\times$ & Lat.$\times$ & "
             r"Route price & Save \\", r"\midrule"]
    last = None
    for (mdl, task, n, amin, amax, pxx, ltx, rp, sv, trap) in rows:
        mcell = esc(mdl) if mdl != last else ""
        last = mdl
        trapmark = r"\,$\dagger$" if trap else ""
        lines.append(f"{mcell} & {esc(task)} & {n} & {amin:.0%}--{amax:.0%}{trapmark} & "
                     f"{pxx:.1f} & {ltx:.0f} & \\${rp:.3f} & {sv:.0%} \\\\".replace("%", "\\%"))
    lines += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(OUT, "results_table.tex"), "w").write("\n".join(lines))

    # headline macros
    med = sorted(saves)[len(saves)//2]
    cq, nq = median_price_corr(m, "accuracy")
    cl, nl = median_price_corr(m, "latency")
    cr, nr = median_price_corr(m, "availability")
    macros = [
        f"\\newcommand{{\\numcells}}{{{len(rows)}}}",
        f"\\newcommand{{\\nummodels}}{{{len(m)}}}",
        f"\\newcommand{{\\medsave}}{{{med*100:.0f}\\%}}",
        f"\\newcommand{{\\numtraps}}{{{traps}}}",
        f"\\newcommand{{\\maxpricex}}{{{max(price_x):.1f}$\\times$}}",
        f"\\newcommand{{\\maxlatx}}{{{max(lat_x):.0f}$\\times$}}",
        f"\\newcommand{{\\corrqual}}{{{cq:+.2f}}}",
        f"\\newcommand{{\\corrlat}}{{{cl:+.2f}}}",
        f"\\newcommand{{\\corrrel}}{{{cr:+.2f}}}",
        f"\\newcommand{{\\corrqualn}}{{{nq}}}",
    ]
    open(os.path.join(OUT, "stats.tex"), "w").write("\n".join(macros) + "\n")
    print(f"wrote results_table.tex ({len(rows)} rows) and stats.tex "
          f"(median save {med:.0%}, {traps} traps; price-corr qual {cq:+.2f}/lat {cl:+.2f}/rel {cr:+.2f})")

if __name__ == "__main__":
    main()
