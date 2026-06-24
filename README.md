# Market-Aware Routing — Validation Harness

Light validation BEFORE building. Zero-cost where possible. De-risks both the paper
(real ReplayEnv trace + dynamic-price thesis) and the product (quality-equivalence wedge).

## Falsifiable questions
- **Q1 price dispersion** — how big is the cross-provider spread for the same open model? → `probe_endpoints.py`
- **Q2 churn (temporal)** — does the cheapest provider change over time? → `analyze_churn.py` over many snapshots
- **Q3 quality-equivalence** — do cheaper (more quantized) endpoints silently lose quality? → `probe_quality.py` (TODO, needs API key + small spend) — THE moat
- **Q4 safe savings** — counterfactual: naive single-provider vs cheapest-healthy-equivalent → derived once Q1–Q3 land

## First snapshot (2026-06-22)
- Q1: median spread **2.3×**, max **8.8×** (Llama-3.1-8B). Real but NOT the "100×" marketing; fat spreads on small/old models, ~2× on frontier open models.
- Cheapest endpoint is consistently the **most quantized** (fp4/fp8) → confirms the real wedge is "is the cheap one actually as good?", not raw price.
- Provider count 1–13; single-provider models (e.g. qwen3-235b) have NO arbitrage.

## Usage
```bash
python3 probe_endpoints.py          # one snapshot -> data/snap_<utc>.json
python3 analyze_churn.py            # churn over all snapshots (needs >=2)
```

## Collect churn data (hourly, a few days)
```bash
# add to crontab (crontab -e), runs hourly:
0 * * * * cd /Users/tonygpt/Desktop/PROJECTS/market-aware-routing && /usr/bin/python3 probe_endpoints.py >> data/cron.log 2>&1
```

## Q3 results (3-model spectrum, honest)
- **Llama-3.1-8B / hard math**: same model, 6 providers → **35%–90%** accuracy. QUALITY dominates on weak models. Price ⊥ quality (WandB $0.22→45%, Groq $0.065→90%).
- **Llama-3.3-70B / hard math**: 60%–75% accuracy; latency **0.16s–8.96s (56×)**; Cloudflare 4xx-fails. Quality modest, RELIABILITY/LATENCY emerge.
- **DeepSeek-v3.1 / moderate**: all 100% incl **fp4**; wedge = price (2.3×) + latency (24×) + reliability (fp4 80% avail). Quality SATURATES — fp4 does NOT always degrade.
- Takeaway: which axis matters depends on model strength × task difficulty → you need continuous **measurement**, not a static rule. (max_tokens=80 truncation artifact on the first DeepSeek run was caught & fixed → 1024.)

## Product MVP (works now)
```bash
python3 router.py plan meta-llama/llama-3.3-70b-instruct   # show routing decision + baselines
python3 proxy.py                                           # OpenAI-compatible proxy on :8077
# point any OpenAI client at http://localhost:8077/v1 ; responses carry X-MAR-* decision headers
curl -s localhost:8077/v1/ledger                          # cumulative savings vs quality-first
```
- `router.py` core: cheapest provider with measured acc ≥ floor AND avail ≥ 90%.
- 70B demo: picks AkashML = **62% cheaper** than Groq at equivalent quality, avoids sub-floor DeepInfra.
- DeepSeek demo: health-filters off the cheap-but-rate-limited fp4 → AtlasCloud.

## Older note (Q3 probe rationale)
Needs an OpenRouter API key + small inference budget (~$5–20). For each (model × provider),
run a held-out probe set (classification/extraction golds where "equivalent" is objectively
checkable) → equivalence score vs a reference endpoint. The cheapest endpoint that stays
≥ τ-equivalent AND healthy = the safe route. This map is the product moat and the paper's
online-quality signal.
