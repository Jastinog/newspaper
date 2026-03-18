#!/bin/bash
set -e

cd /root/Projects/newspaper
echo '>> Pulling latest...'
git pull origin master

echo '>> Installing dependencies...'
uv sync

echo '>> Running migrations...'
uv run python manage.py migrate

echo '>> Collecting static files...'
uv run python manage.py collectstatic --no-input --clear > /dev/null

echo '>> Restarting gunicorn...'
systemctl restart newspaper-gunicorn

echo '>> Done!'
systemctl status newspaper-gunicorn --no-pager | head -5
