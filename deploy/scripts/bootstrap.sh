#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/docmaster/app
python3 -m venv "$ROOT/.venv"
source "$ROOT/.venv/bin/activate"
cd "$ROOT/backend"
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_docmaster
