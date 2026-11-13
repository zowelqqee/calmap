#!/bin/sh
set -eu

# Migrations and seeding run once here, before any worker starts, so several
# uvicorn workers never race on the schema. Both steps are idempotent.
echo "Applying database migrations..."
alembic upgrade head

echo "Seeding catalogue..."
python -m app.seed.run

# --proxy-headers makes request.client the real visitor behind Caddy/Nginx, which
# the auth rate limiter relies on. Only the listed proxy addresses are trusted.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --no-server-header
