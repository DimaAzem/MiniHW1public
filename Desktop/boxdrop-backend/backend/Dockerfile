# --- Stage 1: builder -------------------------------------------------
# Installs dependencies into an isolated prefix so the final image never
# carries build tooling or pip's cache.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: runtime ---------------------------------------------------
FROM python:3.12-slim AS runtime

# Run as a non-root user for defense in depth.
RUN groupadd --gid 1000 boxdrop && \
    useradd --uid 1000 --gid boxdrop --shell /bin/bash --create-home boxdrop

WORKDIR /app

COPY --from=builder /install /usr/local
COPY backend/ ./backend/

RUN chown -R boxdrop:boxdrop /app

USER boxdrop

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
