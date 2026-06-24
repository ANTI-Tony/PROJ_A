#!/usr/bin/env python3
"""
Market-Aware Router — OpenAI-compatible proxy (product surface, MVP).

Drop-in: point any OpenAI client at  http://localhost:8077/v1  and it transparently
routes each chat request to the cheapest provider that is quality-equivalent AND healthy
(per the measured map), via OpenRouter. Adds response headers so the caller can see the
decision, and writes a persistent savings ledger (data/ledger.jsonl).

  POST /v1/chat/completions   -> routed completion (+ X-MAR-* headers)
  GET  /v1/ledger             -> cumulative savings summary

Run:   python3 proxy.py            # listens on :8077
Test:  curl -s localhost:8077/v1/chat/completions -H 'Content-Type: application/json' \
         -d '{"model":"meta-llama/llama-3.3-70b-instruct","messages":[{"role":"user","content":"2+2? number only"}]}'
"""
import json, os, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from router import build_policy, choose, baselines, BASE, KEY

HERE = os.path.dirname(__file__)
LEDGER = os.path.join(HERE, "data", "ledger.jsonl")
_policies = {}   # model -> (policy, pick, baselines), cached per process

def policy_for(model, task=None):
    key = (model, task)
    if key not in _policies:
        p = build_policy(model, task=task)
        pick, why = choose(p)
        qf, pb = baselines(p)
        _policies[key] = (p, pick, why, qf, pb)
    return _policies[key]

def upstream(model, provider, body):
    payload = dict(body)
    payload["model"] = model
    payload["provider"] = {"order": [provider], "allow_fallbacks": False}
    payload.pop("stream", None)  # MVP: non-streaming
    req = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://localhost/mar", "X-Title": "mar-proxy"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r), time.time() - t0

def log_ledger(rec):
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec) + "\n")

def ledger_summary():
    if not os.path.exists(LEDGER):
        return {"requests": 0, "spent_usd": 0, "counterfactual_quality_first_usd": 0, "saved_usd": 0}
    reqs = [json.loads(l) for l in open(LEDGER) if l.strip()]
    spent = sum(r["cost"] for r in reqs)
    cf = sum(r["counterfactual_quality_first"] for r in reqs)
    return {"requests": len(reqs), "spent_usd": round(spent, 6),
            "counterfactual_quality_first_usd": round(cf, 6),
            "saved_usd": round(cf - spent, 6),
            "saved_pct": (round(100*(cf-spent)/cf, 1) if cf else 0)}

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj, extra=None):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/") == "/v1/ledger":
            self._send(200, ledger_summary())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            model = body["model"]
            # task: optional caller hint (body.task or X-MAR-Task header) -> per-task quality floor
            task = body.pop("task", None) or self.headers.get("X-MAR-Task")
            p, pick, why, qf, pb = policy_for(model, task)
            resp, dt = upstream(model, pick["provider"], body)
            cost = (resp.get("usage", {}) or {}).get("cost", 0) or 0
            # counterfactual: same tokens at the quality-first provider's price
            ratio = (qf["price_1m"] / pick["price_1m"]) if pick["price_1m"] else 1
            cf_cost = cost * ratio
            log_ledger({"utc": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), "model": model,
                        "provider": pick["provider"], "cost": cost,
                        "counterfactual_quality_first": cf_cost, "latency": round(dt, 2)})
            self._send(200, resp, {
                "X-MAR-Provider": pick["provider"], "X-MAR-Quant": pick["quant"],
                "X-MAR-Reason": why, "X-MAR-Price-1M": f"{pick['price_1m']:.3f}",
                "X-MAR-Acc": f"{pick['accuracy']:.0%}", "X-MAR-Cost": f"{cost:.6f}",
                "X-MAR-Saved-vs-QualityFirst": f"{cf_cost - cost:.6f}"})
        except urllib.error.HTTPError as e:
            self._send(e.code, {"error": f"upstream {e.code}", "detail": e.read().decode()[:200]})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def log_message(self, *a):  # quiet
        pass

if __name__ == "__main__":
    port = int(os.environ.get("MAR_PORT", "8077"))
    print(f"Market-Aware proxy on http://localhost:{port}/v1  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
