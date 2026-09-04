#!/bin/sh
set -eu
# Dokku runs this once with runtime configuration before switching web traffic.
python manage.py check
python manage.py migrate --noinput
python manage.py collectstatic --noinput
