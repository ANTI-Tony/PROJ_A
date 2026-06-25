# Deploying APOCALYPSE

The app is a single stdlib Python server (no dependencies). The only secret is
`OPENROUTER_API_KEY`, provided at runtime (never baked into the image; `.env` and
`.git` are excluded by `.dockerignore`). It binds `HOST:PORT` (env, default `0.0.0.0:8088`
in the container).

## Local container test
```bash
docker build -t apocalypse .
docker run -p 8088:8088 -e OPENROUTER_API_KEY=sk-or-v1-... apocalypse
# open http://localhost:8088
```

## Fly.io (recommended — free tier, fast)
```bash
fly launch --copy-config --name apocalypse --no-deploy   # uses fly.toml
fly secrets set OPENROUTER_API_KEY=sk-or-v1-...           # secret, not in image
fly deploy
# -> https://apocalypse.fly.dev
```

## Railway / Render
Both auto-detect the Dockerfile. Create a new service from the GitHub repo
`ANTI-Tony/PROJ_A`, then set the env var `OPENROUTER_API_KEY` in the dashboard.
Render: set Health Check Path `/`. Expose port `8088`.

## Keeping the map fresh in production
The deployed app serves prices from `data/live_market.json` (committed). To keep it
fresh, run `refresh.py` on a schedule and redeploy, or add a small worker that runs
`python3 refresh.py` hourly and commits/persists `data/live_market.json`. Quality
(`probe_quality.py`) only needs re-running weekly.

## Notes
- The interactive "Try the router" panel makes real (paid) OpenRouter calls with your
  key — fine for demos; rate-limit or disable it before a public launch if cost is a concern.
- For data residency, the same image runs self-hosted in a customer's environment.
