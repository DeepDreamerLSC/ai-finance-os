#!/bin/sh
set -eu

python -m alembic upgrade head
exec python -m app.server
