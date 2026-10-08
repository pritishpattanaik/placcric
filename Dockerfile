# PlacCric application image. Build with `docker compose build app` (see docs/DEPLOYMENT.md).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home --home-dir /app placcric

COPY requirements.txt .
RUN pip install -r requirements.txt

# Code stays root-owned and read-only for the runtime user.
COPY alembic.ini server.py ./
COPY app ./app
COPY migrations ./migrations
COPY web ./web
COPY data/scorecards.json data/rosters.json ./data/
COPY tests ./tests

ARG PLACCRIC_VERSION=dev
ENV PLACCRIC_VERSION=${PLACCRIC_VERSION} PLACCRIC_HOST=0.0.0.0 PLACCRIC_PORT=8000
LABEL org.opencontainers.image.source="https://github.com/pritishpattanaik/placcric" \
      org.opencontainers.image.revision="${PLACCRIC_VERSION}"

USER placcric
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]
CMD ["python", "server.py"]
