#!/bin/bash
set -e

# Render and similar hosts inject $PORT; default 8000 for local Docker.
PORT="${PORT:-8000}"

if [ "$1" = "uvicorn" ]; then
  shift
  exec uvicorn "$@" --host 0.0.0.0 --port "$PORT"
fi

exec "$@"