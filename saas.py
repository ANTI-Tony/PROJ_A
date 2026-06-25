#!/usr/bin/env python3
"""
APOCALYPSE — multi-tenant SaaS (BYOK).

Customers sign up, get an API key, save their own OpenRouter key (BYOK), point their app's
base_url at us, and we route every request to the cheapest quality-equivalent healthy provider
using THEIR key. They see usage + savings on a dashboard. Stdlib only (http.server + sqlite3).

  GET  /                       landing (marketing + login/signup)
  GET/POST /signup /login      auth
  POST /logout
  GET  /dashboard              their API keys, BYOK form, usage + savings, integration snippet
  POST /keys/new /keys/revoke /byok
  POST /v1/chat/completions    OpenAI-compatible; auth by THEIR api key; routes with THEIR BYOK key

Run:  python3 saas.py        # http://localhost:8088
"""
import json, os, time, base64, hmac, hashlib, secrets, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import db, gateway
from audit import analyze_cell

db.init()
SECRET = os.environ.get("MAR_SECRET") or secrets.token_hex(16)

# ---------- OAuth (GitHub + Google) ----------
OAUTH = {
    "github": {
        "id": os.environ.get("GITHUB_CLIENT_ID"), "secret": os.environ.get("GITHUB_CLIENT_SECRET"),
        "auth": "https://github.com/login/oauth/authorize", "scope": "user:email",
        "token": "https://github.com/login/oauth/access_token"},
    "google": {
        "id": os.environ.get("GOOGLE_CLIENT_ID"), "secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "auth": "https://accounts.google.com/o/oauth2/v2/auth", "scope": "openid email",
        "token": "https://oauth2.googleapis.com/token"},
}
def oauth_on(p): return bool(OAUTH[p]["id"] and OAUTH[p]["secret"])

def _sign_state(provider):
    nonce = secrets.token_urlsafe(8)
    sig = hmac.new(SECRET.encode(), f"{provider}:{nonce}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"{provider}.{nonce}.{sig}"

def _check_state(state, provider):
    try:
        prov, nonce, sig = state.split(".")
        good = hmac.new(SECRET.encode(), f"{prov}:{nonce}".encode(), hashlib.sha256).hexdigest()[:16]
        return prov == provider and hmac.compare_digest(good, sig)
    except Exception:
        return False

def _post_json(url, data, headers=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def _get_json(url, token, scheme="Bearer"):
    req = urllib.request.Request(url, headers={"Authorization": f"{scheme} {token}",
                                               "Accept": "application/json", "User-Agent": "apocalypse"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def oauth_email(provider, code, redirect_uri):
    cfg = OAUTH[provider]
    if provider == "github":
        tok = _post_json(cfg["token"], {"client_id": cfg["id"], "client_secret": cfg["secret"],
                                        "code": code, "redirect_uri": redirect_uri})["access_token"]
        emails = _get_json("https://api.github.com/user/emails", tok, "token")
        primary = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
        return primary or (emails[0]["email"] if emails else None)
    else:  # google
        tok = _post_json(cfg["token"], {"client_id": cfg["id"], "client_secret": cfg["secret"],
                         "code": code, "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        info = _get_json("https://openidconnect.googleapis.com/v1/userinfo", tok["access_token"])
        return info.get("email") if info.get("email_verified") else info.get("email")

# ---------- sessions ----------
def sign(uid):
    msg = str(uid).encode()
    sig = hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(msg).decode() + "." + sig

def unsign(cookie):
    try:
        b64, sig = cookie.split(".")
        msg = base64.urlsafe_b64decode(b64)
        if hmac.compare_digest(hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()[:16], sig):
            return int(msg)
    except Exception:
        pass
    return None

# ---------- HTML ----------
CSS = """
:root{--bg:#05070d;--panel:#0b1020;--line:#16213e;--cyan:#22d3ee;--orange:#ff8a3d;--green:#34d399;--red:#f87171;--txt:#cdd6e8;--dim:#6b7a99}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.6 ui-monospace,Menlo,monospace}
a{color:var(--cyan);text-decoration:none}.wrap{max-width:880px;margin:0 auto;padding:30px 20px 70px}
header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:16px}
.logo{font-size:24px;font-weight:800;letter-spacing:5px;color:#fff;text-shadow:0 0 16px var(--cyan)}.logo b{color:var(--cyan)}
h1{font-size:22px;color:#fff}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}
.panel h2{font-size:13px;letter-spacing:2px;color:var(--cyan);text-transform:uppercase;margin:0 0 12px}
input,button{font:13px ui-monospace,monospace;background:#0a0f1d;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:10px}
input{width:100%;margin:6px 0}button{background:var(--cyan);color:#04111a;font-weight:700;border:0;cursor:pointer;padding:10px 18px}
button.ghost{background:transparent;color:var(--dim);border:1px solid var(--line)}
.stats{display:flex;gap:12px}.stat{flex:1;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.stat .v{font-size:24px;color:var(--green);font-weight:700}.stat .k{color:var(--dim);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--dim)}
code,.mono{color:var(--dim)}.key{font-family:monospace;background:#020a12;padding:6px 10px;border-radius:6px;color:var(--cyan);word-break:break-all}
pre{background:#020a12;border:1px solid var(--line);border-radius:8px;padding:12px;overflow-x:auto;color:#cde}
.err{color:var(--red)}.ok{color:var(--green)}.dim{color:var(--dim)}
"""

def page(title, body, uid=None):
    nav = (f'<a href="/dashboard">dashboard</a> &nbsp; <form method="post" action="/logout" style="display:inline">'
           f'<button class="ghost">logout</button></form>') if uid else \
          '<a href="/login">login</a> &nbsp; <a href="/signup">sign up</a>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>APOCALYPSE — {title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body><div class="wrap">
<header><div class="logo">APO<b>CALYPSE</b></div><div>{nav}</div></header>{body}</div></body></html>"""

def landing(stats):
    return page("market-aware routing", f"""
<h1>Stop picking your inference provider from the price list.</h1>
<p class="dim">The same open model, served by competing providers, varies up to {stats['maxprice']}× in price,
{stats['maxlat']}× in latency, and silently in quality. Bring your own key, point your app at us, and every
request auto-routes to the cheapest provider that is quality-equivalent and healthy.</p>
<div class="stats">
  <div class="stat"><div class="v">{stats['save']}%</div><div class="k">median savings, equal quality</div></div>
  <div class="stat"><div class="v">{stats['cells']}</div><div class="k">(model×task) cells measured</div></div>
  <div class="stat"><div class="v">{stats['traps']}</div><div class="k">silent quality traps caught</div></div>
</div>
<div class="panel"><h2>get started</h2>
<p><a href="/signup">Create an account</a> → save your OpenRouter key → change one line (<code>base_url</code>). BYOK: we never charge you for inference.</p></div>""")

def auth_form(kind, err=""):
    social = ""
    if oauth_on("github"):
        social += '<a href="/auth/github"><button class="ghost" style="width:100%;margin:4px 0">Continue with GitHub</button></a>'
    if oauth_on("google"):
        social += '<a href="/auth/google"><button class="ghost" style="width:100%;margin:4px 0">Continue with Google</button></a>'
    if social:
        social = social + '<p class="dim" style="text-align:center;margin:10px 0">— or —</p>'
    return page(kind, f"""
<div class="panel" style="max-width:420px;margin:40px auto"><h2>{kind}</h2>
{'<p class="err">'+err+'</p>' if err else ''}
{social}
<form method="post" action="/{kind}">
  <input name="email" type="email" placeholder="email" required>
  <input name="pw" type="password" placeholder="password" required>
  <button>{kind}</button>
</form>
<p class="dim">{'No account? <a href="/signup">sign up</a>' if kind=='login' else 'Have an account? <a href="/login">login</a>'}</p></div>""")

def dashboard(uid, base_url):
    u = db.get_user(uid)
    keys = db.list_keys(uid)
    summ = db.usage_summary(uid)
    byok_set = bool(u["byok"])
    keyrows = "".join(
        f'<tr><td class="key">{k["key"][:12]}…{k["key"][-4:]}</td><td>{k["label"]}</td>'
        f'<td>{"revoked" if k["revoked"] else "active"}</td>'
        f'<td><form method="post" action="/keys/revoke" style="display:inline">'
        f'<input type="hidden" name="key" value="{k["key"]}"><button class="ghost">revoke</button></form></td></tr>'
        for k in keys) or '<tr><td colspan=4 class="dim">no keys yet</td></tr>'
    full_key = next((k["key"] for k in keys if not k["revoked"]), "YOUR_API_KEY")
    usagerows = "".join(
        f'<tr><td>{r["ts"][5:16]}</td><td>{r["model"].split("/")[-1]}</td><td>{r["task"]}</td>'
        f'<td>{r["provider"]}</td><td>${r["cost"]:.6f}</td><td class="ok">${(r["counterfactual"]-r["cost"]):.6f}</td></tr>'
        for r in summ["recent"]) or '<tr><td colspan=6 class="dim">no requests yet</td></tr>'
    snippet = (f'from openai import OpenAI\n'
               f'client = OpenAI(base_url="{base_url}/v1", api_key="{full_key}")\n'
               f'r = client.chat.completions.create(\n'
               f'    model="meta-llama/llama-3.3-70b-instruct",\n'
               f'    messages=[{{"role":"user","content":"What is 12*12?"}}])\n'
               f'print(r.choices[0].message.content)')
    return page("dashboard", f"""
<h1>Dashboard <span class="dim" style="font-size:13px">{u['email']}</span></h1>
<div class="stats">
  <div class="stat"><div class="v">{summ['requests']}</div><div class="k">requests routed</div></div>
  <div class="stat"><div class="v">${summ['saved']:.4f}</div><div class="k">saved ({summ['saved_pct']}%)</div></div>
  <div class="stat"><div class="v">${summ['spent']:.4f}</div><div class="k">your spend (your key)</div></div>
</div>

<div class="panel"><h2>1 · your OpenRouter key (BYOK)</h2>
<p class="dim">We route with <b>your</b> key — we never charge you for inference. {'<span class="ok">✓ key saved</span>' if byok_set else '<span class="err">⚠ not set — required to route</span>'}</p>
<form method="post" action="/byok"><input name="byok" type="password" placeholder="sk-or-v1-..."><button>save key</button></form></div>

<div class="panel"><h2>2 · your API keys</h2>
<table><tr><th>key</th><th>label</th><th>status</th><th></th></tr>{keyrows}</table>
<form method="post" action="/keys/new" style="margin-top:10px"><button>+ new API key</button></form></div>

<div class="panel"><h2>3 · use it — change one line</h2>
<pre>{snippet}</pre>
<p class="dim">Or curl: <code>curl {base_url}/v1/chat/completions -H "Authorization: Bearer {full_key}" -d '{{"model":"...","messages":[...]}}'</code></p></div>

<div class="panel"><h2>recent requests</h2>
<table><tr><th>time</th><th>model</th><th>task</th><th>routed to</th><th>cost</th><th>saved</th></tr>{usagerows}</table></div>""", uid)

# ---------- landing stats (from the measured map) ----------
def landing_stats():
    try:
        m = json.load(open(os.path.join(os.path.dirname(__file__), "data", "quality_map.json")))
    except Exception:
        m = {}
    saves, px, lx, traps, cells = [], [1], [1], 0, 0
    for model in m:
        for task in m[model]:
            a = analyze_cell(m[model][task])
            if not a or not a["router"]:
                continue
            cells += 1; saves.append(a["save_vs_premium"]); lx.append(a["lat_x"])
            prices = [p["price_1m"] for p in m[model][task].values() if p["price_1m"] > 0]
            if len(prices) > 1: px.append(max(prices)/min(prices))
            if a["quality_trap"]: traps += 1
    med = sorted(saves)[len(saves)//2] if saves else 0
    return {"save": round(med*100), "cells": cells, "traps": traps,
            "maxprice": round(max(px), 1), "maxlat": round(max(lx))}

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _uid(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            if part.strip().startswith("mar_session="):
                return unsign(part.strip()[12:])
        return None

    def _html(self, s, code=200, cookie=None):
        b = s.encode(); self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _redirect(self, to, cookie=None):
        self.send_response(303); self.send_header("Location", to)
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0"); self.end_headers()

    def _json(self, code, obj, extra=None):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _base(self):
        host = self.headers.get("Host", "localhost")
        proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        return f"{proto}://{host}"

    def _form(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return urllib.parse.parse_qs(self.rfile.read(n).decode())

    def do_GET(self):
        p = self.path.rstrip("/") or "/"
        uid = self._uid()
        if p == "/":
            self._html(landing(landing_stats()))
        elif p == "/login":
            self._html(auth_form("login"))
        elif p == "/signup":
            self._html(auth_form("signup"))
        elif p == "/dashboard":
            if not uid:
                return self._redirect("/login")
            self._html(dashboard(uid, self._base()))
        elif p.startswith("/auth/"):
            self._oauth(p)
        else:
            self._html(page("404", "<p>not found</p>", uid), 404)

    def _oauth(self, path):
        parts = path.split("/")             # /auth/<provider>[/callback]
        provider = parts[2] if len(parts) > 2 else ""
        if provider not in OAUTH or not oauth_on(provider):
            return self._html(page("oauth", "<p class='err'>provider not configured</p>"), 400)
        redirect_uri = f"{self._base()}/auth/{provider}/callback"
        if len(parts) <= 3:                 # start: redirect to provider
            cfg = OAUTH[provider]
            q = urllib.parse.urlencode({"client_id": cfg["id"], "redirect_uri": redirect_uri,
                                        "scope": cfg["scope"], "state": _sign_state(provider),
                                        "response_type": "code"})
            return self._redirect(f"{cfg['auth']}?{q}")
        # callback: verify state, exchange code -> email -> session
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code, state = qs.get("code", [""])[0], qs.get("state", [""])[0]
        if not code or not _check_state(state, provider):
            return self._html(auth_form("login", "OAuth failed (bad state)"), 400)
        try:
            email = oauth_email(provider, code, redirect_uri)
        except Exception as e:
            return self._html(auth_form("login", f"OAuth error: {e}"), 400)
        if not email:
            return self._html(auth_form("login", "could not get a verified email from provider"), 400)
        uid = db.upsert_oauth_user(email, provider)
        self._redirect("/dashboard", f"mar_session={sign(uid)}; HttpOnly; Path=/; Max-Age=2592000")

    def do_POST(self):
        p = self.path.rstrip("/")
        if p == "/v1/chat/completions":
            return self._route()
        uid = self._uid()
        if p in ("/signup", "/login"):
            f = self._form(); email = (f.get("email", [""])[0]); pw = f.get("pw", [""])[0]
            if p == "/signup":
                nid = db.create_user(email, pw)
                if not nid:
                    return self._html(auth_form("signup", "email already registered"))
                db.create_api_key(nid)               # give them a key on signup
                return self._redirect("/dashboard", f"mar_session={sign(nid)}; HttpOnly; Path=/; Max-Age=2592000")
            u = db.get_user_by_email(email)
            if not u or not db.check_pw(pw, u["pw"]):
                return self._html(auth_form("login", "wrong email or password"))
            return self._redirect("/dashboard", f"mar_session={sign(u['id'])}; HttpOnly; Path=/; Max-Age=2592000")
        if p == "/logout":
            return self._redirect("/", "mar_session=; Path=/; Max-Age=0")
        if not uid:
            return self._redirect("/login")
        f = self._form()
        if p == "/byok":
            db.set_byok(uid, f.get("byok", [""])[0].strip()); return self._redirect("/dashboard")
        if p == "/keys/new":
            db.create_api_key(uid); return self._redirect("/dashboard")
        if p == "/keys/revoke":
            db.revoke_key(uid, f.get("key", [""])[0]); return self._redirect("/dashboard")
        self._redirect("/dashboard")

    def _route(self):
        # OpenAI-compatible endpoint: auth by the customer's API key, route with their BYOK key
        auth = self.headers.get("Authorization", "")
        key = auth[7:].strip() if auth.startswith("Bearer ") else ""
        uid = db.user_for_key(key)
        if not uid:
            return self._json(401, {"error": "invalid API key"})
        byok = db.get_byok(uid)
        if not byok:
            return self._json(400, {"error": "no OpenRouter key on file — set it in your dashboard"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        task = body.pop("task", None) or self.headers.get("X-MAR-Task")
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            try:
                gateway.stream(body, task, self.wfile.write, api_key=byok)
            except Exception as e:
                try: self.wfile.write(f"data: {json.dumps({'error': str(e)})}\n\n".encode())
                except Exception: pass
            return
        try:
            d, meta = gateway.complete(body, task, api_key=byok)
            cf = meta["cost"] * (meta["premium_price"]/meta["price"] if meta["price"] else 1)
            db.log_usage(uid, body.get("model", "?"), meta["provider"], meta["task"],
                         meta["cost"], cf, meta["latency"], meta["fallbacks"])
            self._json(200, d, {"X-MAR-Provider": meta["provider"], "X-MAR-Task": meta["task"],
                                "X-MAR-Fallbacks": meta["fallbacks"]})
        except Exception as e:
            self._json(502, {"error": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8088"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"APOCALYPSE SaaS -> http://{host}:{port}")
    ThreadingHTTPServer((host, port), H).serve_forever()
