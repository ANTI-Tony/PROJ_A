#!/usr/bin/env python3
"""
Market-Aware Router — product core engine (MVP).

The thesis, made executable: price ⊥ quality ⊥ latency ⊥ reliability, so you CANNOT
pick a provider from the price list. This router consumes the MEASURED quality map
(data/quality_*.json from probe_quality.py) + LIVE price/health (OpenRouter /endpoints)
and routes each request to the CHEAPEST endpoint that is BOTH quality-equivalent
(measured acc >= floor relative to the best) AND currently healthy.

It logs a counterfactual savings ledger vs two naive baselines:
  - quality-first  : always the highest-measured-accuracy provider (what a careful user does)
  - price-blind    : pick cheapest by list price IGNORING quality (what 'route to cheapest' does)

This is the product MVP core AND the paper's online-quality-aware policy. Build once.

Usage:
  python3 router.py plan  meta-llama/llama-3.3-70b-instruct        # show the policy/decision
  python3 router.py ask   meta-llama/llama-3.3-70b-instruct "..."  # actually route one request
  python3 router.py demo  meta-llama/llama-3.3-70b-instruct        # route a batch, print savings
"""
import json, glob, os, sys, re, urllib.request, urllib.error, time, socket

HERE = os.path.dirname(__file__)
BASE = "https://openrouter.ai/api/v1"
DATA = os.path.join(HERE, "data")

def load_key():
    # prefer env var (deploy secret); fall back to local .env file (dev)
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k.strip()
    envf = os.path.join(HERE, ".env")
    if os.path.exists(envf):
        for line in open(envf):
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("no OPENROUTER_API_KEY (set env var or .env)")
KEY = load_key()

def _live_market():
    """Fresh per-(model,provider) price/health from refresh.py, if available; else {}."""
    f = os.path.join(DATA, "live_market.json")
    try:
        return json.load(open(f)) if os.path.exists(f) else {}
    except Exception:
        return {}

def latest_quality(model, task=None):
    """Most recent measured quality file for this (model, task). The safe quality
       floor is task-dependent (hard math vs classification differ), so route by task."""
    safe = model.replace("/", "_")
    files = sorted(glob.glob(os.path.join(DATA, f"quality_{safe}_*.json")))
    if not files:
        return None
    if task:
        pats = [f"_{task}_"] + (["_hard_"] if task == "math" else [])  # legacy 'hard' == math
        tf = [f for f in files if any(pt in f for pt in pats)]
        return json.load(open(tf[-1])) if tf else None
    pref = [f for f in files if "_math_" in f or "_hard_" in f]  # default: general reasoning signal
    return json.load(open((pref or files)[-1]))

def build_policy(model, quality_floor_drop=0.05, min_avail=0.9, task=None):
    """Merge measured quality with the policy thresholds.
       quality_floor_drop: max acceptable accuracy drop vs the best measured provider.
       min_avail: minimum measured availability to be routable."""
    q = latest_quality(model, task)
    if not q:
        # raise (not sys.exit): SystemExit bypasses `except Exception` in server handlers
        raise ValueError(f"No measured quality for {model} task={task}. "
                         f"Run: python3 probe_quality.py {model} --task={task or 'math'}")
    rows = [r for r in q["results"] if r.get("accuracy") is not None and r.get("served", 0) >= 3]
    best = max(r["accuracy"] for r in rows)
    floor = best - quality_floor_drop
    live = _live_market().get(model, {})   # overlay FRESH price (quality stays from slow probes)
    for r in rows:
        lv = live.get(r["provider"])
        if lv and lv.get("price_1m"):
            r["price_1m"] = lv["price_1m"]; r["live"] = True
        r["equivalent"] = r["accuracy"] >= floor
        r["healthy"] = (r.get("availability", 0) >= min_avail)
        r["routable"] = r["equivalent"] and r["healthy"]
    return {"model": model, "measured_utc": q["utc"], "probe_set": q.get("probe_set"),
            "best_acc": best, "floor": floor, "rows": rows}

def choose(policy):
    routable = [r for r in policy["rows"] if r["routable"]]
    if not routable:
        # degrade gracefully: best healthy provider regardless of price
        healthy = [r for r in policy["rows"] if r["healthy"]] or policy["rows"]
        return max(healthy, key=lambda r: r["accuracy"]), "fallback(no quality-equivalent healthy endpoint)"
    return min(routable, key=lambda r: r["price_1m"]), "cheapest quality-equivalent + healthy"

def ranked(policy):
    """Ordered fallback list: cheapest quality-equivalent+healthy first, then other healthy
       by accuracy, then the rest by accuracy. The gateway tries these in order."""
    rows = policy["rows"]
    routable = sorted((r for r in rows if r["routable"]), key=lambda r: r["price_1m"])
    healthy  = sorted((r for r in rows if r["healthy"] and not r["routable"]), key=lambda r: -r["accuracy"])
    rest     = sorted((r for r in rows if not r["healthy"]), key=lambda r: -r["accuracy"])
    seen, out = set(), []
    for r in (*routable, *healthy, *rest):
        if r["provider"] not in seen:
            seen.add(r["provider"]); out.append(r)
    return out

def baselines(policy):
    rows = policy["rows"]
    quality_first = max(rows, key=lambda r: (r["accuracy"], -r["price_1m"]))
    price_blind   = min(rows, key=lambda r: r["price_1m"])   # ignores quality/health
    return quality_first, price_blind

# ---- task auto-detection (so callers need not tag the task) ----
def _last_user(body):
    if isinstance(body, str):
        return body
    for msg in reversed(body.get("messages", []) or []):
        if msg.get("role") == "user":
            return msg.get("content", "") or ""
    return ""

def detect_task(body):
    """Cheap, zero-latency heuristic mapping a prompt to a measured task class. None if unsure."""
    t = _last_user(body).lower()
    if any(k in t for k in ("classify", "sentiment", "positive or negative", "category",
                            "label this", "is this spam", "intent of")):
        return "classification"
    if any(k in t for k in ("extract", "pull the", "return the", "what is the value",
                            "find the", "which number", "the order number", "the id")):
        return "extraction"
    if re.search(r"\d\s*[\+\-\*x/]\s*\d", t) or any(k in t for k in (
            "calculate", "how many", "how much", "solve", "sum of", "product of",
            "percent", "what is ", "total")):
        return "math"
    return None

def measured_tasks(model):
    safe = model.replace("/", "_")
    tasks = set()
    for f in glob.glob(os.path.join(DATA, f"quality_{safe}_*.json")):
        lab = os.path.basename(f).split(safe + "_", 1)[-1].rsplit("_", 1)[0]
        tasks.add("math" if lab == "hard" else lab)
    return tasks

def resolve_task(model, body, explicit=None):
    """Explicit tag wins; else heuristic; else strictest-available task (safety default)."""
    if explicit:
        return explicit
    avail = measured_tasks(model)
    t = detect_task(body)
    if t in avail:
        return t
    for pref in ("math", "extraction", "classification"):   # strictest floor first
        if pref in avail:
            return pref
    return next(iter(avail), None)

def fmt(r):
    return (f"{r['provider']} ({r['quant']}, ${r['price_1m']:.3f}/1M, "
            f"acc={r['accuracy']:.0%}, avail={r.get('availability',0):.0%})")

def cmd_plan(model, task=None):
    p = build_policy(model, task=task)
    pick, why = choose(p)
    qf, pb = baselines(p)
    print(f"\nPolicy for {model}  task={task or p['probe_set']}  (measured {p['measured_utc']})")
    print(f"best acc={p['best_acc']:.0%}, equivalence floor={p['floor']:.0%}\n")
    print(f"{'provider':<14}{'quant':<9}{'acc':>5}{'avail':>7}{'$/1M':>9}  routable")
    print("-" * 56)
    for r in sorted(p["rows"], key=lambda r: r["price_1m"]):
        tag = "ROUTE" if r["routable"] else ("low-qual" if not r["equivalent"] else "unhealthy")
        print(f"{r['provider']:<14}{r['quant']:<9}{r['accuracy']:>5.0%}"
              f"{r.get('availability',0):>7.0%}{r['price_1m']:>9.3f}  {tag}")
    print(f"\n-> ROUTER picks: {fmt(pick)}\n   reason: {why}")
    print(f"   vs quality-first baseline: {fmt(qf)}")
    print(f"   vs price-blind  baseline: {fmt(pb)}")
    save = (qf["price_1m"] - pick["price_1m"]) / qf["price_1m"] if qf["price_1m"] else 0
    print(f"\n   savings vs quality-first at equivalent quality: {save:.0%} cheaper "
          f"(${qf['price_1m']:.3f} -> ${pick['price_1m']:.3f} /1M)")
    if pb["accuracy"] < p["floor"]:
        print(f"   price-blind would pick {pb['provider']} at acc={pb['accuracy']:.0%} "
              f"(BELOW floor {p['floor']:.0%}) — cheaper but NOT quality-equivalent. "
              f"This is the trap the router avoids.")

def call(model, provider, messages, max_tokens=1024):
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
               "provider": {"order": [provider], "allow_fallbacks": False}}
    req = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://localhost/mar", "X-Title": "mar-router"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    return (d["choices"][0]["message"]["content"], time.time()-t0,
            (d.get("usage", {}) or {}).get("cost", 0) or 0)

def cmd_ask(model, prompt, task=None):
    p = build_policy(model, task=task)
    pick, why = choose(p)
    print(f"Routing to {fmt(pick)}\n  reason: {why}\n")
    content, dt, cost = call(model, pick["provider"], [{"role": "user", "content": prompt}])
    print(content)
    print(f"\n[provider={pick['provider']}  latency={dt:.2f}s  cost=${cost:.6f}]")

def cmd_demo(model, task=None):
    """Route a batch; show cumulative real cost vs the price-blind baseline's cost,
       and whether price-blind would have stayed quality-equivalent."""
    p = build_policy(model, task=task)
    pick, _ = choose(p)
    qf, pb = baselines(p)
    prompts = ["Name the capital of France. One word.",
               "What is 17 * 23? Number only.",
               "List three primary colors, comma-separated.",
               "Is 91 prime? Answer yes or no."]
    spent = 0.0
    print(f"Router picks {pick['provider']} (${pick['price_1m']:.3f}/1M); "
          f"price-blind would pick {pb['provider']} (${pb['price_1m']:.3f}/1M, "
          f"acc {pb['accuracy']:.0%} vs floor {p['floor']:.0%}).\n")
    for pr in prompts:
        content, dt, cost = call(model, pick["provider"], [{"role": "user", "content": pr}])
        spent += cost
        print(f"  Q: {pr}\n  A: {content.strip()[:80]}   [{dt:.2f}s ${cost:.6f}]")
    # cost is dominated by tokens; price ratio is the honest per-token lever
    ratio_qf = pick["price_1m"] / qf["price_1m"] if qf["price_1m"] else 1
    print(f"\nReal spend this batch (router): ${spent:.6f}")
    print(f"At quality-first provider's price it'd be ~{1/ratio_qf:.2f}x = "
          f"${spent/ratio_qf:.6f}  -> router saves {1-ratio_qf:.0%} at equivalent quality.")
    print(f"Price-blind ({pb['provider']}) is ${pb['price_1m']:.3f}/1M but acc {pb['accuracy']:.0%}"
          f"{' — BELOW floor, unsafe' if pb['accuracy'] < p['floor'] else ''}.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    argv = sys.argv[1:]
    task = next((a.split("=", 1)[1] for a in argv if a.startswith("--task=")), None)
    pos = [a for a in argv if not a.startswith("--")]
    cmd, model = pos[0], pos[1]
    if cmd == "plan": cmd_plan(model, task)
    elif cmd == "ask": cmd_ask(model, pos[2], task)
    elif cmd == "demo": cmd_demo(model, task)
    else: print("commands: plan | ask | demo   [--task=math|classification|extraction]")
