#!/usr/bin/env python3
"""
Production gateway core: market-aware routing with automatic FALLBACK and STREAMING.
Used by app.py and proxy.py so both share one reliable code path.

  complete(body, task) -> (response_dict, meta)        # non-streaming, falls over on failure
  stream(body, task, write) -> meta                    # SSE; connect-time fallback, then forward
ranked() gives the ordered provider list; a failed provider (HTTP/timeout) drops to the next.
"""
import json, urllib.request, urllib.error, socket, time
from router import build_policy, choose, baselines, ranked, resolve_task, BASE, KEY

MAX_TRIES = 4   # cap fallbacks so a bad model can't hammer every provider

def _request(model, provider, body, stream):
    payload = dict(body); payload["model"] = model
    payload["provider"] = {"order": [provider], "allow_fallbacks": False}
    payload["stream"] = stream
    payload.pop("task", None)
    return urllib.request.Request(
        f"{BASE}/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://localhost/mar", "X-Title": "mar-gateway"})

def _plan(model, body, task):
    task = resolve_task(model, body, task)        # auto-detect if untagged
    p = build_policy(model, task=task)
    return p, ranked(p), task

def complete(body, task=None):
    """Non-streaming with fallback. Returns (response_dict, meta). Raises if all providers fail."""
    model = body["model"]; p, order, task = _plan(model, body, task)
    tried = []
    for r in order[:MAX_TRIES]:
        tried.append(r["provider"])
        try:
            t0 = time.time()
            with urllib.request.urlopen(_request(model, r["provider"], body, False), timeout=90) as resp:
                d = json.load(resp)
            return d, {"provider": r["provider"], "quant": r["quant"], "price": r["price_1m"],
                       "acc": r["accuracy"], "fallbacks": len(tried) - 1, "tried": tried, "task": task,
                       "latency": round(time.time() - t0, 2), "floor": p["floor"],
                       "cost": (d.get("usage", {}) or {}).get("cost", 0) or 0}
        except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout, TimeoutError):
            continue
    raise RuntimeError(f"all {len(tried)} providers failed: {tried}")

def stream(body, task, write):
    """Streaming with connect-time fallback. `write(bytes)` forwards SSE chunks. Returns meta.
       Fallback applies until the first byte; once forwarding begins we do not switch providers."""
    model = body["model"]; p, order, task = _plan(model, body, task)
    tried = []
    for r in order[:MAX_TRIES]:
        tried.append(r["provider"])
        try:
            resp = urllib.request.urlopen(_request(model, r["provider"], body, True), timeout=90)
        except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout, TimeoutError):
            continue
        try:
            while True:
                chunk = resp.read(2048)
                if not chunk:
                    break
                write(chunk)
        finally:
            resp.close()
        return {"provider": r["provider"], "fallbacks": len(tried) - 1, "tried": tried, "task": task}
    raise RuntimeError(f"all {len(tried)} providers failed (stream): {tried}")
