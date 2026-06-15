#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

if [ "${SEED_DB:-false}" = "true" ]; then
  echo "Seeding database..."
  python seed.py
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
