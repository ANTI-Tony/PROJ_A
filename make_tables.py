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
    macros = [
        f"\\newcommand{{\\numcells}}{{{len(rows)}}}",
        f"\\newcommand{{\\nummodels}}{{{len(m)}}}",
        f"\\newcommand{{\\medsave}}{{{med*100:.0f}\\%}}",
        f"\\newcommand{{\\numtraps}}{{{traps}}}",
        f"\\newcommand{{\\maxpricex}}{{{max(price_x):.1f}$\\times$}}",
        f"\\newcommand{{\\maxlatx}}{{{max(lat_x):.0f}$\\times$}}",
    ]
    open(os.path.join(OUT, "stats.tex"), "w").write("\n".join(macros) + "\n")
    print(f"wrote results_table.tex ({len(rows)} rows) and stats.tex "
          f"(median save {med:.0%}, {traps} traps, price up to {max(price_x):.1f}x, lat up to {max(lat_x):.0f}x)")

if __name__ == "__main__":
    main()
