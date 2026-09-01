#!/bin/sh
# Bring the Supabase schema up to date, then serve. Runs on every deploy; Alembic is
# a no-op when there is nothing new to apply.
set -e

echo "› alembic upgrade head"
alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
