FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -s /sbin/nologin appuser

WORKDIR /app

COPY --from=builder /install /usr/local

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --chown=appuser:appuser scripts/ scripts/
COPY --chown=appuser:appuser config/ config/
COPY --chown=appuser:appuser data/ data/
COPY --chown=appuser:appuser models/ models/
COPY --chown=appuser:appuser agents/ agents/
COPY --chown=appuser:appuser execution/ execution/
COPY --chown=appuser:appuser risk/ risk/
COPY --chown=appuser:appuser dashboard/ dashboard/
COPY --chown=appuser:appuser monitoring/ monitoring/

RUN mkdir -p /app/logs /app/data/exports && \
    chown -R appuser:appuser /app/logs /app/data/exports

USER appuser

EXPOSE 8000 9090

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "scripts/run_live.py"]
CMD ["--symbol", "BTC/USDT"]
