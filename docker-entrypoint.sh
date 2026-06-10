#!/bin/bash
set -e

mkdir -p "${UPLOAD_DIR:-./uploads}"

exec "$@"
