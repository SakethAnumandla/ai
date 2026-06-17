#!/bin/bash
set -e

# Render and similar hosts inject $PORT; default 8000 for local Docker.
PORT="${PORT:-8000}"

if [ "$1" = "uvicorn" ]; then
  shift
  UVICORN_ARGS=(
    "$@"
    --host 0.0.0.0
    --port "$PORT"
    --timeout-keep-alive 120
    --timeout-graceful-shutdown 30
    --limit-concurrency "${UVICORN_LIMIT_CONCURRENCY:-40}"
    --proxy-headers
    --forwarded-allow-ips='*'
  )
  # Hot reload for local Docker dev (docker-compose.dev.yml sets UVICORN_RELOAD=true).
  # Reload requires a single worker process.
  if [ "${UVICORN_RELOAD:-false}" = "true" ]; then
    UVICORN_ARGS+=(--reload --reload-dir /app/app)
  else
    UVICORN_ARGS+=(--workers "${UVICORN_WORKERS:-1}")
  fi
  exec uvicorn "${UVICORN_ARGS[@]}"
fi

exec "$@"