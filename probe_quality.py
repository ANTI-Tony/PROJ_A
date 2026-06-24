#!/usr/bin/env python3
"""
Q3 — Quality-equivalence + reliability probe (hardened).

For ONE open model, route the SAME objective probe set to each PROVIDER separately
(pinned, no fallback) and measure accuracy AND reliability. Separates:
  - silent QUALITY degradation (wrong answers)   <- matters most on weaker models / harder tasks
  - RELIABILITY (rate-limit vs real failure)     <- matters most on capable models
Neither is inferable from price or quantization label -> measurement IS the moat.

Hardening vs v1:
  * error typing: 429 rate-limit / 5xx server / timeout / client, retried w/ backoff
    -> distinguishes "provider is unhealthy" from "I hit a rate limit"
  * endpoint dedupe (provider,quant,price)
  * HARD probe set (multi-step) to break the 100% ceiling on strong models
  * latency only over successful calls; real $ from OpenRouter usage.cost

Usage:
  python3 probe_quality.py meta-llama/llama-3.3-70b-instruct
  python3 probe_quality.py deepseek/deepseek-chat-v3.1 --easy
Key from .env. Cost: cents.
"""
import json, urllib.request, urllib.error, time, os, sys, re, socket

HERE = os.path.dirname(__file__)
BASE = "https://openrouter.ai/api/v1"
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)

def load_key():
    for line in open(os.path.join(HERE, ".env")):
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("no OPENROUTER_API_KEY in .env")
KEY = load_key()

# Easy set (v1) — saturates on strong models.
EASY = [
    ("A store sold 23 apples Monday and 41 Tuesday. Total? Number only.", 64),
    ("Tom has 5 boxes of 12 pencils. Gives away 18. Left? Number only.", 42),
    ("Train: 60 km/h for 3h, then 40 km/h for 2h. Total km? Number only.", 260),
    ("8 teams of 11 players. Total players? Number only.", 88),
    ("3 shirts at $25 and 2 hats at $15. Total $? Number only.", 105),
    ("Rectangle 12 cm by 7 cm. Area in sq cm? Number only.", 84),
    ("Factory makes 150 widgets/hour. In 8 hours? Number only.", 1200),
    ("Three friends split a $96 bill equally. Each pays? Number only.", 32),
    ("Class of 28 students, 3/4 passed. How many passed? Number only.", 21),
    ("Paid $18/h plus a $50 bonus, for 6 hours. Total $? Number only.", 158),
]

# Hard set — multi-step, fractions, %, to separate top providers.
HARD = [
    ("A baker makes 12 dozen muffins, sells 3/4, then gives away 9. How many remain? Number only.", 27),
    ("A car goes 240 km on 16 liters. Liters for 525 km at the same rate? Number only.", 35),
    ("$22/hour for 40 hours, overtime at 1.5x. Total pay for a 46-hour week in $? Number only.", 1078),
    ("A tank 3/5 full holds 360 liters. Liters when completely full? Number only.", 600),
    ("Three consecutive even numbers sum to 96. The largest? Number only.", 34),
    ("A $80 shirt is discounted 25%, then 10% tax added on the discounted price. Final $? Number only.", 66),
    ("Garden 18 m by 12 m with a 1 m wide path around the inside edge. Path area in sq m? Number only.", 56),
    ("Printer does 24 pages/min. Pages in 2 hours 15 minutes? Number only.", 3240),
    ("A number increased by 30% equals 169. The original number? Number only.", 130),
    ("Apples cost $3 for 4. How many apples for $24? Number only.", 32),
    ("$250 collected, $90 spent, the rest split equally among 8 students. Each gets $? Number only.", 20),
    ("Two numbers sum to 50, differ by 12. The larger one? Number only.", 31),
    ("Tank fills 25 L/min, drains 10 L/min, both open from empty. Minutes to reach 180 L? Number only.", 12),
    ("320-page book: read 1/4 day one, then 1/2 of the remainder day two. Pages left? Number only.", 120),
    ("Buy pens at $2, sell at $5. How many pens sold to make $90 profit? Number only.", 30),
    ("Car worth $20000 drops 20% year one, then 10% of the new value year two. Value after 2 years $? Number only.", 14400),
    ("3 eggs make 12 cookies. Eggs for 44 cookies? Number only.", 11),
    ("John is twice Mary's age. In 5 years their ages sum to 40. John's age now? Number only.", 20),
    ("2/5 of a class of 35 are boys. How many girls? Number only.", 21),
    ("If 5 machines make 5 widgets in 5 minutes, minutes for 100 machines to make 100 widgets? Number only.", 5),
]

# Classification (sentiment) — gold label exact-match. Tests a different task class.
CLASSIFICATION = [
    ("Sentiment, answer exactly 'positive' or 'negative': Absolutely loved it, best purchase this year!", "positive"),
    ("Sentiment, answer exactly 'positive' or 'negative': Terrible quality, broke after one day.", "negative"),
    ("Sentiment, answer exactly 'positive' or 'negative': The food was delicious and the staff friendly.", "positive"),
    ("Sentiment, answer exactly 'positive' or 'negative': Worst customer service I have ever experienced.", "negative"),
    ("Sentiment, answer exactly 'positive' or 'negative': Exceeded my expectations, highly recommend.", "positive"),
    ("Sentiment, answer exactly 'positive' or 'negative': Complete waste of money, do not buy.", "negative"),
    ("Sentiment, answer exactly 'positive' or 'negative': Fantastic value and super fast shipping.", "positive"),
    ("Sentiment, answer exactly 'positive' or 'negative': It stopped working and they refused a refund.", "negative"),
    ("Sentiment, answer exactly 'positive' or 'negative': A delightful experience from start to finish.", "positive"),
    ("Sentiment, answer exactly 'positive' or 'negative': Overpriced and underwhelming.", "negative"),
    ("Sentiment, answer exactly 'positive' or 'negative': I'm thrilled with how well this works.", "positive"),
    ("Sentiment, answer exactly 'positive' or 'negative': Disappointing, it did not match the description.", "negative"),
    ("Sentiment, answer exactly 'positive' or 'negative': Five stars, would buy again in a heartbeat.", "positive"),
    ("Sentiment, answer exactly 'positive' or 'negative': The room was dirty and smelled bad.", "negative"),
    ("Sentiment, answer exactly 'positive' or 'negative': Great product, exactly what I needed.", "positive"),
]

# Extraction — pull the requested figure from short text. Integer exact-match.
EXTRACTION = [
    ("Order #4521 shipped on the 3rd. The order number? Number only.", 4521),
    ("The meeting is at 2 PM in room 308. The room number? Number only.", 308),
    ("Invoice total: $1,250 due in 30 days. The total in dollars? Number only.", 1250),
    ("She scored 87 out of 100 on the exam. Her score? Number only.", 87),
    ("Flight BA249 departs gate 12. The gate number? Number only.", 12),
    ("We sold 3,400 units in Q1 and 2,100 in Q2. Units in Q1? Number only.", 3400),
    ("The package weighs 15 kg and costs $45. The weight in kg? Number only.", 15),
    ("Temperature dropped to -8 degrees overnight. The temperature? Number only.", -8),
    ("The book has 512 pages across 24 chapters. How many pages? Number only.", 512),
    ("Apartment 7B is on the 9th floor. The floor number? Number only.", 9),
    ("The recipe serves 6 and takes 45 minutes. How many minutes? Number only.", 45),
    ("Customer ID 99812 placed 3 orders. The customer ID? Number only.", 99812),
    ("The car's mileage is 84,000 km. The mileage in km? Number only.", 84000),
    ("Ticket price is $120 for adults and $60 for children. Adult price in dollars? Number only.", 120),
    ("The stadium holds 55,000 fans and sold 48,200 tickets. Tickets sold? Number only.", 48200),
]

def score_int(text, gold):
    return extract_int(text) == gold

def score_label(text, gold):
    t = (text or "").lower()
    other = "negative" if gold == "positive" else "positive"
    return gold in t and other not in t

TASKS = {  # name -> (probes, scorer)
    "math":           (HARD,           score_int),
    "math_easy":      (EASY,           score_int),
    "classification": (CLASSIFICATION, score_label),
    "extraction":     (EXTRACTION,     score_int),
}

RETRYABLE = {429, 500, 502, 503, 504}

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def fnum(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def list_providers(model):
    author, slug = model.split("/", 1)
    eps = http_get(f"{BASE}/models/{author}/{slug}/endpoints").get("data", {}).get("endpoints", [])
    seen, out = set(), []
    for e in eps:
        pr = e.get("pricing", {}) or {}
        price = ((fnum(pr.get("prompt")) or 0)*0.5 + (fnum(pr.get("completion")) or 0)*0.5)*1e6
        prov = e.get("provider_name") or e.get("name")
        quant = e.get("quantization") or "unknown"
        key = (prov, quant, round(price, 4))
        if key in seen:
            continue
        seen.add(key)
        out.append({"provider": prov, "quant": quant, "price_1m": price})
    return out

def extract_int(text):
    if text is None: return None
    nums = re.findall(r"-?\d+", text.replace(",", "").replace("$", ""))
    return int(nums[-1]) if nums else None

def ask(model, provider, q, max_tries=2):
    """Returns (answer_int|None, latency|None, cost, status). status in
    {ok, rate_limit, server, timeout, client, ok_after_retry}."""
    # 1024 tokens: reasoning models (e.g. DeepSeek) emit a chain before the final
    # number; 80 truncated it and extract_int grabbed a mid-reasoning digit (artifact).
    payload = {"model": model, "messages": [{"role": "user", "content": q}],
               "max_tokens": 1024, "temperature": 0,
               "provider": {"order": [provider], "allow_fallbacks": False}}
    body = json.dumps(payload).encode()
    retried = False
    for attempt in range(max_tries):
        try:
            req = urllib.request.Request(
                f"{BASE}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://localhost/mar", "X-Title": "mar-validation"})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.load(r)
            dt = time.time() - t0
            msg = d["choices"][0]["message"]["content"]
            cost = (d.get("usage", {}) or {}).get("cost", 0) or 0
            return msg, dt, cost, ("ok_after_retry" if retried else "ok")
        except urllib.error.HTTPError as e:
            if e.code in RETRYABLE and attempt < max_tries - 1:
                retried = True; time.sleep(0.6 * (attempt + 1) ** 2); continue
            return None, None, 0, ("rate_limit" if e.code == 429 else
                                   "server" if e.code >= 500 else "client")
        except (socket.timeout, urllib.error.URLError, TimeoutError):
            if attempt < max_tries - 1:
                retried = True; time.sleep(0.6 * (attempt + 1) ** 2); continue
            return None, None, 0, "timeout"
        except Exception:
            return None, None, 0, "client"
    return None, None, 0, "timeout"

def run(model, probes, label, scorer=score_int):
    provs = list_providers(model)
    print(f"\nModel: {model}   providers: {len(provs)}   probes: {len(probes)} ({label})\n")
    results = []
    for p in provs:
        correct = attempted = 0; lat = []; spent = 0.0
        status = {"ok": 0, "ok_after_retry": 0, "rate_limit": 0, "server": 0, "timeout": 0, "client": 0}
        aborted = False
        for i, (q, gold) in enumerate(probes):
            ans, dt, cost, st = ask(model, p["provider"], q)
            status[st] += 1; spent += cost
            if st in ("ok", "ok_after_retry"):
                attempted += 1; lat.append(dt)
                if scorer(ans, gold): correct += 1
            # early-abort a dead provider: first 3 calls all failed -> unhealthy, skip rest
            if i == 2 and attempted == 0:
                aborted = True
                print(f"  {p['provider']:<14} {p['quant']:<8} DEAD (0/3, {st}) — skipping remaining {len(probes)-3}")
                break
            time.sleep(0.3)
        served = status["ok"] + status["ok_after_retry"]
        failed = len(probes) - served
        acc = (correct / attempted) if attempted else None      # accuracy over SERVED only
        avail = served / len(probes)
        row = {**p, "accuracy": acc, "availability": avail,
               "served": served, "failed": failed, "status": status,
               "mean_latency": round(sum(lat)/len(lat), 2) if lat else None,
               "spent_usd": round(spent, 6)}
        results.append(row)
        accs = f"{acc:>5.0%}" if acc is not None else "  n/a"
        flags = []
        if status["rate_limit"]: flags.append(f"429x{status['rate_limit']}")
        if status["server"]:     flags.append(f"5xx x{status['server']}")
        if status["timeout"]:    flags.append(f"to x{status['timeout']}")
        if status["ok_after_retry"]: flags.append(f"retry x{status['ok_after_retry']}")
        print(f"  {p['provider']:<14} {p['quant']:<8} acc={accs} (n={attempted:>2}) "
              f"avail={avail:>4.0%}  ${p['price_1m']:.3f}/1M  lat={row['mean_latency']}s"
              f"  {' '.join(flags)}")

    # quality table over providers that actually served a quorum
    valid = [r for r in results if r["served"] >= max(3, len(probes)//2) and r["accuracy"] is not None]
    if valid:
        best = max(r["accuracy"] for r in valid)
        print(f"\nQuality table (served >= 50%):  best accuracy = {best:.0%}")
        print(f"{'provider':<14}{'quant':<9}{'acc':>6}{'drop':>7}{'avail':>7}{'$/1M':>9}")
        print("-" * 54)
        for r in sorted(valid, key=lambda r: r["price_1m"]):
            print(f"{r['provider']:<14}{r['quant']:<9}{r['accuracy']:>6.0%}"
                  f"{r['accuracy']-best:>7.0%}{r['availability']:>7.0%}{r['price_1m']:>9.3f}")
        cheap = min(valid, key=lambda r: r["price_1m"])
        print(f"\nCheapest served = {cheap['provider']} ({cheap['quant']}, ${cheap['price_1m']:.3f}/1M): "
              f"acc {cheap['accuracy']:.0%} vs best {best:.0%} -> {cheap['accuracy']-best:+.0%}")
    unhealthy = [r for r in results if r["availability"] < 0.5]
    if unhealthy:
        print("\nLow availability at probe time (health signal, may be transient):")
        for r in unhealthy:
            print(f"  {r['provider']} ({r['quant']}, ${r['price_1m']:.3f}/1M): "
                  f"served {r['served']}/{len(probes)}  {r['status']}")

    total = sum(r["spent_usd"] for r in results)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = os.path.join(DATA, f"quality_{model.replace('/','_')}_{label}_{ts}.json")
    json.dump({"model": model, "utc": ts, "probe_set": label, "results": results}, open(out, "w"), indent=2)
    print(f"\nTotal spent this run: ${total:.5f}   ->  {out}")

if __name__ == "__main__":
    args = sys.argv[1:]
    model = next((a for a in args if not a.startswith("-")), "meta-llama/llama-3.3-70b-instruct")
    task = "math"
    for a in args:
        if a.startswith("--task="): task = a.split("=", 1)[1]
        elif a == "--easy": task = "math_easy"
    if task not in TASKS:
        sys.exit(f"unknown task '{task}'. choices: {', '.join(TASKS)}")
    probes, scorer = TASKS[task]
    run(model, probes, task, scorer)
