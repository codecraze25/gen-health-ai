#!/bin/sh
set -e

attempt=1
until alembic upgrade head; do
    if [ "$attempt" -ge 10 ]; then
        echo "Database migrations failed after $attempt attempts" >&2
        exit 1
    fi
    echo "Database not ready (attempt $attempt), retrying in 3s..." >&2
    attempt=$((attempt + 1))
    sleep 3
done

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --no-access-log
