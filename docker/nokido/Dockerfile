# Nokido — Dockerfile multi-stage, variants modulaires.
#
# Build:
#   docker build -f docker/nokido/Dockerfile --build-arg VARIANT=core -t nokido:core .
#   docker build -f docker/nokido/Dockerfile --build-arg VARIANT=hub  -t nokido:hub  .
#   docker build -f docker/nokido/Dockerfile --build-arg VARIANT=full -t nokido:full .
#
# Variants (extras pyproject.toml):
#   core = client/SDK minimal (~80 MB)        → httpx + requests + pydantic + rich + psutil
#   hub  = client + hub serveur + RAG + LLM   → core + [hub,rag,llm,docs,git] (~450 MB)
#   full = stack typique end-user             → core + [hub,rag,llm,cloud,ui,git,docker,docs] (~900 MB)
#   all  = vraiment tout (lourd, inclut ML)   → [all] (~3-5 GB avec torch/jax)
#
# Default: hub (le plus utile pour le compose).
ARG VARIANT=hub

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Builder : compile les wheels, télécharge les sources
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

ARG VARIANT

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libffi-dev libssl-dev git curl pkg-config build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Layer cache : copier seulement les fichiers de package d'abord
COPY pyproject.toml README.md ./
COPY app/__init__.py    app/__init__.py
COPY tools/__init__.py  tools/__init__.py

# Pré-télécharge wheels selon le variant. Pas d'install dans le builder —
# on garde juste le cache wheels pour le stage runtime.
RUN python -m pip install --upgrade pip wheel \
 && pip wheel --no-deps --wheel-dir /wheels ".[${VARIANT}]" 2>/dev/null || true \
 && pip download --dest /wheels ".[${VARIANT}]"

# Build le package laforge-agent lui-même
COPY app/    app/
COPY tools/  tools/
RUN pip wheel --no-deps --wheel-dir /wheels .

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Runtime : image minimale, copie wheels depuis builder
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

ARG VARIANT
LABEL org.opencontainers.image.title="Nokido"
LABEL org.opencontainers.image.description="Autonomous Local-First AI Operating System"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"
LABEL org.opencontainers.image.source="https://github.com/user/Nokido"
LABEL org.opencontainers.image.variant="${VARIANT}"

# Runtime deps minimal — curl pour healthcheck, libgomp pour faiss
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copie wheels + install offline (rapide, reproductible)
COPY --from=builder /wheels /wheels
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir --no-index --find-links=/wheels "laforge-agent[${VARIANT}]" \
 && rm -rf /wheels

# Code source (pour les modules pas packagés : configs, sample.env, docs)
COPY app/                      app/
COPY tools/                    tools/
COPY Nokido.env.example       Nokido.env.example
COPY sample.env                sample.env
COPY MANIFESTO.md              MANIFESTO.md
COPY README.md                 README.md
COPY LICENSE                   LICENSE
COPY pyproject.toml            pyproject.toml

# Non-root user — sandbox UID/GID 1000 par défaut
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID nokido && \
    useradd -m -u $UID -g $GID -s /bin/bash nokido && \
    mkdir -p /app/RAG /app/logs /app/sandbox && \
    chown -R nokido:nokido /app

USER nokido

# Variables runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LAFORGE_ROOT=/app \
    LAFORGE_ENV=prod \
    LAFORGE_VARIANT=${VARIANT}

EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8766/health || exit 1

# Hub par défaut. Override CMD si autre variant (ex. core utilisé pour script client).
CMD ["python", "-m", "tools.nokido_hub"]
