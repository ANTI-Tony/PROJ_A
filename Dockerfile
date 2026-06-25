# APOCALYPSE — zero-dependency stdlib app; tiny image.
FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV HOST=0.0.0.0 PORT=8088 MAR_DB=/data/saas.db
EXPOSE 8088
# Secrets at runtime (NOT baked in): OPENROUTER_API_KEY (server fallback), MAR_SECRET (sessions/BYOK).
# /data is a mounted volume so the SQLite DB (users, keys, usage) persists across deploys.
CMD ["python3", "-u", "saas.py"]
