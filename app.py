#!/usr/bin/env python3
"""
APOCALYPSE — web app (runnable demo).
The routing & settlement hub for AI inference.

Single-file stdlib server (no pip deps). Serves a Tron-style dashboard + JSON APIs
backed by the measured quality map and the live market-aware router.

  GET  /                       landing + live dashboard (HTML)
  GET  /api/map                consolidated quality map (model->task->provider)
  GET  /api/audit              savings & safety summary (per model x task)
  POST /api/route   {model,task,prompt}   -> live route via OpenRouter + decision + savings
  GET  /api/ledger             cumulative savings
  POST /v1/chat/completions    OpenAI-compatible drop-in (same as proxy.py)

Run:  python3 app.py      # http://localhost:8088
"""
import json, os, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from router import build_policy, choose, baselines, call, BASE, KEY
from audit import analyze_cell

HERE = os.path.dirname(__file__)
MAP = os.path.join(HERE, "data", "quality_map.json")
LEDGER = os.path.join(HERE, "data", "ledger.jsonl")

def load_map():
    return json.load(open(MAP)) if os.path.exists(MAP) else {}

def audit_summary():
    m = load_map(); cells = []; saves = []; traps = 0
    for model in sorted(m):
        for task in sorted(m[model]):
            a = analyze_cell(m[model][task])
            if not a or not a["router"]:
                continue
            saves.append(a["save_vs_premium"])
            if a["quality_trap"]:
                traps += 1
            cells.append({
                "model": model, "task": task, "n": a["n"],
                "router": a["router"]["provider"], "router_price": a["router"]["price_1m"],
                "router_acc": a["router"]["accuracy"], "quant": a["router"].get("quant"),
                "premium": a["premium"]["provider"], "premium_price": a["premium"]["price_1m"],
                "save_pct": round(a["save_vs_premium"]*100), "lat_x": round(a["lat_x"]),
                "quality_trap": a["quality_trap"], "trap_drop": round(a["trap_drop"]*100),
                "cheapest": a["cheapest"]["provider"], "cheapest_price": a["cheapest"]["price_1m"],
            })
    med = sorted(saves)[len(saves)//2] if saves else 0
    return {"cells": cells, "median_save_pct": round(med*100), "traps": traps,
            "n_cells": len(cells), "n_models": len(m)}

def ledger_summary():
    if not os.path.exists(LEDGER):
        return {"requests": 0, "spent_usd": 0, "saved_usd": 0, "saved_pct": 0}
    reqs = [json.loads(l) for l in open(LEDGER) if l.strip()]
    spent = sum(r["cost"] for r in reqs); cf = sum(r["counterfactual_quality_first"] for r in reqs)
    return {"requests": len(reqs), "spent_usd": round(spent, 6), "saved_usd": round(cf-spent, 6),
            "saved_pct": round(100*(cf-spent)/cf, 1) if cf else 0}

def do_route(model, task, prompt):
    p = build_policy(model, task=task)
    pick, why = choose(p); qf, pb = baselines(p)
    answer, dt, cost = call(model, pick["provider"], [{"role": "user", "content": prompt}])
    save = (qf["price_1m"]-pick["price_1m"])/qf["price_1m"] if qf["price_1m"] else 0
    log_ledger(model, pick, qf, cost, dt)
    return {"provider": pick["provider"], "quant": pick["quant"], "price": pick["price_1m"],
            "acc": pick["accuracy"], "reason": why, "answer": answer, "latency": round(dt, 2),
            "cost": cost, "premium": qf["provider"], "premium_price": qf["price_1m"],
            "save_pct": round(save*100), "floor": round(p["floor"]*100),
            "cheapest": pb["provider"], "cheapest_acc": round(pb["accuracy"]*100),
            "quality_trap": pb["accuracy"] < p["floor"]}

def log_ledger(model, pick, qf, cost, dt):
    ratio = qf["price_1m"]/pick["price_1m"] if pick["price_1m"] else 1
    with open(LEDGER, "a") as f:
        f.write(json.dumps({"utc": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                "model": model, "provider": pick["provider"], "cost": cost,
                "counterfactual_quality_first": cost*ratio, "latency": round(dt, 2)})+"\n")

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>APOCALYPSE — AI Inference Routing Hub</title><style>
:root{--bg:#05070d;--panel:#0b1020;--line:#16213e;--cyan:#22d3ee;--orange:#ff8a3d;--green:#34d399;--red:#f87171;--txt:#cdd6e8;--dim:#6b7a99}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
.grid-bg{position:fixed;inset:0;background:
 linear-gradient(transparent 97%,rgba(34,211,238,.07) 98%) 0 0/100% 28px,
 linear-gradient(90deg,transparent 97%,rgba(34,211,238,.07) 98%) 0 0/28px 100%;z-index:0;pointer-events:none}
.wrap{position:relative;z-index:1;max-width:1080px;margin:0 auto;padding:28px 20px 80px}
header{display:flex;align-items:baseline;gap:14px;border-bottom:1px solid var(--line);padding-bottom:18px}
.logo{font-size:30px;font-weight:800;letter-spacing:6px;color:#fff;text-shadow:0 0 18px var(--cyan)}
.logo b{color:var(--cyan)}.tag{color:var(--dim)}
.hero{margin:26px 0 10px}.hero h1{font-size:22px;margin:0 0 6px;color:#fff;font-weight:600}
.hero p{margin:0;color:var(--dim);max-width:720px}
.stats{display:flex;gap:14px;margin:22px 0}
.stat{flex:1;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.stat .v{font-size:26px;color:var(--cyan);font-weight:700}.stat.o .v{color:var(--orange)}.stat .k{color:var(--dim);font-size:12px;margin-top:2px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:18px 0}
.panel h2{margin:0 0 12px;font-size:14px;letter-spacing:2px;color:var(--cyan);text-transform:uppercase}
select,textarea,button{font:13px ui-monospace,monospace;background:#0a0f1d;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:9px}
select{margin-right:8px}textarea{width:100%;height:64px;margin:8px 0;resize:vertical}
button{background:var(--cyan);color:#04111a;font-weight:700;border:0;cursor:pointer;padding:10px 18px}
button:hover{box-shadow:0 0 16px var(--cyan)}button:disabled{opacity:.5;cursor:wait}
.card{margin-top:14px;border:1px solid var(--cyan);border-radius:10px;padding:14px;background:#071019;display:none}
.card.show{display:block}.card .answer{color:#fff;background:#020a12;border-radius:6px;padding:10px;margin-top:8px;white-space:pre-wrap}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:12px;margin-right:6px}
.b-cyan{background:rgba(34,211,238,.15);color:var(--cyan)}.b-green{background:rgba(52,211,153,.15);color:var(--green)}
.b-red{background:rgba(248,113,113,.15);color:var(--red)}.b-orange{background:rgba(255,138,61,.15);color:var(--orange)}
table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500}td .save{color:var(--green);font-weight:700}td .trap{color:var(--red)}
.mono{color:var(--dim)}footer{margin-top:30px;color:var(--dim);font-size:12px;border-top:1px solid var(--line);padding-top:16px}
.spin{color:var(--orange)}
</style></head><body><div class="grid-bg"></div><div class="wrap">
<header><div class="logo">APO<b>CALYPSE</b></div><div class="tag">// the routing &amp; settlement hub for AI inference</div></header>

<div class="hero"><h1>Stop picking your inference provider from the price list.</h1>
<p>Across competing providers, the same open model varies wildly in price, latency, reliability — and silently in quality.
Price ⊥ quality ⊥ latency ⊥ reliability. APOCALYPSE measures every (model × task × provider) cell and routes each
request to the cheapest provider that is <b>quality-equivalent and healthy right now.</b></p></div>

<div class="stats" id="stats">
  <div class="stat"><div class="v" id="s-save">—</div><div class="k">median savings vs premium, equal quality</div></div>
  <div class="stat o"><div class="v" id="s-traps">—</div><div class="k">workloads where "cheapest" silently degrades</div></div>
  <div class="stat"><div class="v" id="s-cells">—</div><div class="k">(model × task) cells measured</div></div>
</div>

<div class="panel"><h2>Try the router — live</h2>
  <div><select id="model"></select><select id="task"></select></div>
  <textarea id="prompt">Classify the sentiment, answer 'positive' or 'negative': The shipping was fast and the product works perfectly.</textarea>
  <button id="go" onclick="route()">⚡ ROUTE</button> <span id="spin" class="spin"></span>
  <div class="card" id="card"></div>
</div>

<div class="panel"><h2>Live quality map — the moat</h2>
  <table id="map"><thead><tr><th>model</th><th>task</th><th>providers</th><th>route → (price)</th>
  <th>save vs premium</th><th>latency Δ</th><th>quality trap?</th></tr></thead><tbody id="maprows"></tbody></table>
</div>

<footer>APOCALYPSE · drop-in OpenAI-compatible endpoint (<span class="mono">/v1/chat/completions</span>) ·
billed on guaranteed savings · self-host option for data residency · built on the measured quality map.</footer>
</div>
<script>
async function j(u,o){const r=await fetch(u,o);return r.json()}
let MAP={};
async function init(){
  const a=await j('/api/audit');
  document.getElementById('s-save').textContent=a.median_save_pct+'%';
  document.getElementById('s-traps').textContent=a.traps;
  document.getElementById('s-cells').textContent=a.n_cells;
  const tb=document.getElementById('maprows');tb.innerHTML='';
  a.cells.forEach(c=>{const tr=document.createElement('tr');
    tr.innerHTML=`<td>${c.model.split('/').pop()}</td><td>${c.task}</td><td>${c.n}</td>
    <td>${c.router} <span class="mono">$${c.router_price.toFixed(3)}</span></td>
    <td><span class="save">${c.save_pct}%</span></td><td>${c.lat_x}×</td>
    <td>${c.quality_trap?`<span class="trap">⚠ ${c.cheapest} ${c.trap_drop}%</span>`:'—'}</td>`;
    tb.appendChild(tr);});
  MAP=await j('/api/map');
  const ms=document.getElementById('model');ms.innerHTML='';
  Object.keys(MAP).sort().forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m.split('/').pop();ms.appendChild(o);});
  ms.onchange=fillTasks;fillTasks();
}
function fillTasks(){const m=document.getElementById('model').value;const ts=document.getElementById('task');ts.innerHTML='';
  Object.keys(MAP[m]||{}).sort().forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=t;ts.appendChild(o);});}
async function route(){
  const btn=document.getElementById('go'),sp=document.getElementById('spin'),card=document.getElementById('card');
  btn.disabled=true;sp.textContent='routing…';card.className='card';
  try{
    const d=await j('/api/route',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model:document.getElementById('model').value,task:document.getElementById('task').value,prompt:document.getElementById('prompt').value})});
    if(d.error){card.innerHTML=`<span class="b-red badge">error</span> ${d.error}`;card.className='card show';return;}
    const trap=d.quality_trap?`<span class="b-red badge">⚠ cheapest (${d.cheapest}) only ${d.cheapest_acc}% &lt; floor ${d.floor}% — avoided</span>`:'';
    card.innerHTML=`<span class="b-cyan badge">→ ${d.provider} (${d.quant})</span>
      <span class="b-green badge">save ${d.save_pct}% vs ${d.premium}</span>
      <span class="b-orange badge">${d.latency}s · $${d.cost.toFixed(6)}</span>
      <span class="b-cyan badge">measured acc ${Math.round(d.acc*100)}%</span> ${trap}
      <div class="answer">${(d.answer||'').trim()}</div>
      <div class="mono" style="margin-top:6px">reason: ${d.reason}</div>`;
    card.className='card show';
  }catch(e){card.innerHTML='<span class="b-red badge">error</span> '+e;card.className='card show';}
  finally{btn.disabled=false;sp.textContent='';}
}
init();
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def _html(self, s):
        b = s.encode(); self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path.rstrip("/")
        if p in ("", "/"): self._html(PAGE)
        elif p == "/api/map": self._json(200, load_map())
        elif p == "/api/audit": self._json(200, audit_summary())
        elif p == "/api/ledger": self._json(200, ledger_summary())
        else: self._json(404, {"error": "not found"})
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        p = self.path.rstrip("/")
        if p == "/api/route":
            try:
                self._json(200, do_route(body["model"], body.get("task"), body.get("prompt", "")))
            except urllib.error.HTTPError as e:
                self._json(200, {"error": f"upstream {e.code}"})
            except Exception as e:
                self._json(200, {"error": str(e)})
        elif p == "/v1/chat/completions":
            try:
                model = body["model"]; task = body.pop("task", None) or self.headers.get("X-MAR-Task")
                pol = build_policy(model, task=task); pick, _ = choose(pol)
                payload = dict(body); payload["provider"] = {"order": [pick["provider"]], "allow_fallbacks": False}
                req = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(payload).encode(),
                    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    self._json(200, json.load(r))
            except Exception as e:
                self._json(502, {"error": str(e)})
        else:
            self._json(404, {"error": "not found"})
    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8088"))
    print(f"APOCALYPSE running -> http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
