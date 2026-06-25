# APOCALYPSE — zero-dependency stdlib app; tiny image.
FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV HOST=0.0.0.0 PORT=8088
EXPOSE 8088
# OPENROUTER_API_KEY must be provided at runtime as a secret (NOT baked in)
CMD ["python3", "-u", "app.py"]
