#!/bin/sh
set -eu

echo "Applying database migrations..."
alembic upgrade head

echo "Seeding catalogue..."
python -m app.seed.run

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}"
