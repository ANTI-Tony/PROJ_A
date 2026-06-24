# Savings & Safety Audit

_Measured across competing providers per (model, task). Price ⊥ quality ⊥ latency ⊥ reliability — you cannot pick from the price list._
**Across 18 (model×task) workloads: median **50%** savings vs premium picks at equal measured quality; 5 workloads where 'route to cheapest' silently drops below the quality floor.**


## deepseek/deepseek-chat-v3.1
- **classification** (7 providers): route to **DeepInfra** ($0.500/1M, 100%, fp4). Premium pick Google costs $1.150/1M → **save 57%** at equal quality. Latency varies 68×.
- **extraction** (6 providers): route to **AtlasCloud** ($0.625/1M, 100%, fp8). Premium pick Google costs $1.150/1M → **save 46%** at equal quality. Latency varies 34×.
- **math** (7 providers): route to **AtlasCloud** ($0.625/1M, 100%, fp8). Premium pick Google costs $1.150/1M → **save 46%** at equal quality. Latency varies 24×.
    - ⚠️ **Unreliable at probe time:** DeepInfra (80% avail).

## google/gemma-3-27b-it
- **classification** (5 providers): route to **DeepInfra** ($0.120/1M, 100%, fp8). Premium pick Phala costs $0.305/1M → **save 61%** at equal quality. Latency varies 4×.
    - ⚠️ **Unreliable at probe time:** Parasail (87% avail).
- **extraction** (5 providers): route to **DeepInfra** ($0.120/1M, 100%, fp8). Premium pick Phala costs $0.305/1M → **save 61%** at equal quality. Latency varies 8×.
- **math** (4 providers): route to **Phala** ($0.305/1M, 72%, unknown). Premium pick Phala costs $0.305/1M → **save 0%** at equal quality. Latency varies 3×.
    - ⚠️ **Quality trap:** the cheapest (Novita, $0.160/1M) scores 55% = **-17% vs best** (below the 67% floor). 'Route to cheapest' silently degrades here.

## meta-llama/llama-3.1-8b-instruct
- **classification** (5 providers): route to **DeepInfra** ($0.025/1M, 100%, fp8). Premium pick WandB costs $0.220/1M → **save 89%** at equal quality. Latency varies 8×.
- **extraction** (5 providers): route to **Novita** ($0.035/1M, 93%, fp8). Premium pick WandB costs $0.220/1M → **save 84%** at equal quality. Latency varies 10×.
    - ⚠️ **Quality trap:** the cheapest (DeepInfra, $0.025/1M) scores 80% = **-13% vs best** (below the 88% floor). 'Route to cheapest' silently degrades here.
- **math** (5 providers): route to **WandB** ($0.220/1M, 85%, bf16). Premium pick WandB costs $0.220/1M → **save 0%** at equal quality. Latency varies 13×.
    - ⚠️ **Quality trap:** the cheapest (DeepInfra, $0.025/1M) scores 60% = **-25% vs best** (below the 80% floor). 'Route to cheapest' silently degrades here.
    - ⚠️ **Unreliable at probe time:** Novita (65% avail).

## meta-llama/llama-3.3-70b-instruct
- **classification** (9 providers): route to **Nebius** ($0.265/1M, 100%, fp8). Premium pick Cloudflare costs $1.273/1M → **save 79%** at equal quality. Latency varies 25×.
- **extraction** (10 providers): route to **DeepInfra** ($0.210/1M, 100%, fp8). Premium pick Together costs $1.040/1M → **save 80%** at equal quality. Latency varies 6×.
    - ⚠️ **Unreliable at probe time:** Groq (53% avail).
- **math** (11 providers): route to **AkashML** ($0.265/1M, 70%, fp8). Premium pick Cloudflare costs $1.273/1M → **save 79%** at equal quality. Latency varies 56×.
    - ⚠️ **Quality trap:** the cheapest (DeepInfra, $0.210/1M) scores 65% = **-10% vs best** (below the 70% floor). 'Route to cheapest' silently degrades here.
    - ⚠️ **Unreliable at probe time:** Cloudflare (25% avail).

## meta-llama/llama-4-maverick
- **classification** (4 providers): route to **DeepInfra** ($0.375/1M, 100%, fp8). Premium pick Google costs $0.750/1M → **save 50%** at equal quality. Latency varies 3×.
- **extraction** (4 providers): route to **DeepInfra** ($0.375/1M, 93%, fp8). Premium pick Google costs $0.750/1M → **save 50%** at equal quality. Latency varies 4×.
- **math** (4 providers): route to **DeepInfra** ($0.375/1M, 85%, fp8). Premium pick Google costs $0.750/1M → **save 50%** at equal quality. Latency varies 2×.

## mistralai/mistral-small-3.2-24b-instruct
- **classification** (4 providers): route to **Venice** ($0.172/1M, 100%, fp8). Premium pick Mistral costs $0.200/1M → **save 14%** at equal quality. Latency varies 2×.
    - ⚠️ **Unreliable at probe time:** DeepInfra (80% avail).
- **extraction** (4 providers): route to **Mistral** ($0.200/1M, 100%, unknown). Premium pick Mistral costs $0.200/1M → **save 0%** at equal quality. Latency varies 3×.
    - ⚠️ **Quality trap:** the cheapest (DeepInfra, $0.138/1M) scores 93% = **-7% vs best** (below the 95% floor). 'Route to cheapest' silently degrades here.
- **math** (4 providers): route to **DeepInfra** ($0.138/1M, 100%, fp8). Premium pick Mistral costs $0.200/1M → **save 31%** at equal quality. Latency varies 4×.
