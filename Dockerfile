# syntax=docker/dockerfile:1

FROM python:3.9-slim AS base

# PYTHONDONTWRITEBYTECODE: the image layer is read-only anyway, so .pyc files
# are dead weight. PYTHONUNBUFFERED: without it the JSON log lines sit in a
# pipe buffer and arrive late (or not at all, if the container is killed).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg2 links against libpq at runtime; the -dev headers and compiler are
# only needed if a wheel isn't available, so they're dropped in the same layer
# to keep them out of the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies are copied and installed before the source so an application
# change doesn't invalidate the (slow) pip layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Run unprivileged: a container escape shouldn't start from root.
RUN useradd --create-home --uid 10001 orbit \
    && chown -R orbit:orbit /app
USER orbit

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

# Migrations are deliberately NOT run here: with more than one replica every
# container would race to apply them at boot. Run `alembic upgrade head` as a
# separate release step.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
