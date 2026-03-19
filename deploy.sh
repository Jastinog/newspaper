#!/bin/bash
set -e

export PATH=/root/.local/bin:$PATH
cd /root/Projects/newspaper
echo '>> Pulling latest...'
git pull origin master

echo '>> Installing dependencies...'
uv sync

echo '>> Running migrations...'
uv run python manage.py migrate

echo '>> Compiling translations...'
uv run python manage.py compilemessages

echo '>> Collecting static files...'
uv run python manage.py collectstatic --no-input --clear > /dev/null

echo '>> Restarting services...'
systemctl restart newspaper-gunicorn
systemctl restart newspaper-daphne
systemctl restart newspaper-celery
systemctl restart newspaper-celerybeat

echo '>> Done!'
systemctl status newspaper-gunicorn --no-pager | head -3
systemctl status newspaper-daphne --no-pager | head -3
systemctl status newspaper-celery --no-pager | head -3
systemctl status newspaper-celerybeat --no-pager | head -3
