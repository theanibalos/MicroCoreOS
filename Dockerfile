# ══════════════════════════════════════════════════════════════════
# MicroCoreOS — Production Dockerfile
# ══════════════════════════════════════════════════════════════════
#
# Build:
#   docker build -t microcoreos .
#
# Run:
#   docker run -p 5000:5000 --env-file .env microcoreos
#
# ══════════════════════════════════════════════════════════════════

FROM python:3.12-slim

# ── uv (fast Python package manager) ──────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ── Dependencies (cached layer — only rebuilds when lock file changes) ──
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# ── Application source ─────────────────────────────────────────────
COPY . .

# ── Production defaults ────────────────────────────────────────────
# HTTP_HOST must be 0.0.0.0 in a container — otherwise the server only
# listens on loopback and no external requests can reach it.
ENV HTTP_HOST=0.0.0.0
ENV HTTP_PORT=5000

EXPOSE 5000

CMD ["uv", "run", "main.py"]
