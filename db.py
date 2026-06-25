#!/usr/bin/env python3
"""
SQLite data layer for the multi-tenant SaaS (stdlib only; zero external deps).
Tables: users, api_keys, usage. DB path = $MAR_DB or data/saas.db (put on a Fly volume to persist).

SECURITY (MVP, honest): passwords are PBKDF2-hashed; BYOK provider keys are stored
ENCRYPTED-AT-REST only if MAR_SECRET is set (XOR-stream over a SHA256 keystream — adequate
obfuscation, NOT strong crypto). For production, store BYOK keys in a real secrets manager
or encrypt with a vetted library. Treat the DB as sensitive.
"""
import os, sqlite3, hashlib, secrets, time, hmac

HERE = os.path.dirname(os.path.abspath(__file__))
DBP = os.environ.get("MAR_DB", os.path.join(HERE, "data", "saas.db"))
SECRET = os.environ.get("MAR_SECRET", "")   # for cookie signing + BYOK obfuscation

def conn():
    c = sqlite3.connect(DBP)
    c.row_factory = sqlite3.Row
    return c

def init():
    os.makedirs(os.path.dirname(DBP), exist_ok=True)
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, email TEXT UNIQUE, pw TEXT, byok TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS api_keys(
          key TEXT PRIMARY KEY, user_id INTEGER, label TEXT, created TEXT, revoked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS usage(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ts TEXT, model TEXT,
          provider TEXT, task TEXT, cost REAL, counterfactual REAL, latency REAL, fallbacks INTEGER);
        CREATE INDEX IF NOT EXISTS ix_usage_user ON usage(user_id);
        CREATE INDEX IF NOT EXISTS ix_keys_user ON api_keys(user_id);
        """)

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# ---- passwords ----
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"

def check_pw(pw, stored):
    try:
        salt, _ = stored.split("$", 1)
        return hmac.compare_digest(hash_pw(pw, salt), stored)
    except Exception:
        return False

# ---- BYOK obfuscation (see security note) ----
def _xor(s, b=False):
    if not SECRET or not s:
        return s
    data = bytes.fromhex(s) if b else s.encode()
    ks = b""
    i = 0
    while len(ks) < len(data):
        ks += hashlib.sha256(f"{SECRET}:{i}".encode()).digest(); i += 1
    out = bytes(d ^ k for d, k in zip(data, ks))
    return out.decode() if b else out.hex()
def enc(s): return _xor(s, b=False)
def dec(s): return _xor(s, b=True)

# ---- users ----
def create_user(email, pw):
    with conn() as c:
        try:
            cur = c.execute("INSERT INTO users(email,pw,created) VALUES(?,?,?)",
                            (email.lower().strip(), hash_pw(pw), _now()))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None  # email exists

def get_user_by_email(email):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()

def get_user(uid):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def set_byok(uid, key):
    with conn() as c:
        c.execute("UPDATE users SET byok=? WHERE id=?", (enc(key) if key else None, uid))

def get_byok(uid):
    u = get_user(uid)
    return dec(u["byok"]) if u and u["byok"] else None

# ---- api keys ----
def create_api_key(uid, label="default"):
    key = "apo-" + secrets.token_urlsafe(24)
    with conn() as c:
        c.execute("INSERT INTO api_keys(key,user_id,label,created) VALUES(?,?,?,?)",
                  (key, uid, label, _now()))
    return key

def user_for_key(key):
    with conn() as c:
        r = c.execute("SELECT user_id FROM api_keys WHERE key=? AND revoked=0", (key,)).fetchone()
        return r["user_id"] if r else None

def list_keys(uid):
    with conn() as c:
        return c.execute("SELECT * FROM api_keys WHERE user_id=? ORDER BY created", (uid,)).fetchall()

def revoke_key(uid, key):
    with conn() as c:
        c.execute("UPDATE api_keys SET revoked=1 WHERE key=? AND user_id=?", (key, uid))

# ---- usage ----
def log_usage(uid, model, provider, task, cost, counterfactual, latency, fallbacks):
    with conn() as c:
        c.execute("""INSERT INTO usage(user_id,ts,model,provider,task,cost,counterfactual,latency,fallbacks)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  (uid, _now(), model, provider, task, cost, counterfactual, latency, fallbacks))

def usage_summary(uid, limit=50):
    with conn() as c:
        rows = c.execute("SELECT * FROM usage WHERE user_id=? ORDER BY id DESC LIMIT ?",
                         (uid, limit)).fetchall()
        agg = c.execute("""SELECT COUNT(*) n, COALESCE(SUM(cost),0) spent,
                           COALESCE(SUM(counterfactual),0) cf FROM usage WHERE user_id=?""", (uid,)).fetchone()
    spent, cf = agg["spent"], agg["cf"]
    return {"requests": agg["n"], "spent": round(spent, 6), "saved": round(cf - spent, 6),
            "saved_pct": round(100*(cf-spent)/cf, 1) if cf else 0,
            "recent": [dict(r) for r in rows]}

if __name__ == "__main__":
    init(); print("db initialized at", DBP)
