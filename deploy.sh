#!/bin/bash

export PATH=/root/.local/bin:$PATH
cd /root/projects/newspaper

# ── colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RST='\033[0m'

COLS=$(tput cols 2>/dev/null || echo 80)

step() {
    local msg="$1"
    shift
    # print action name, no newline
    printf "  ${BOLD}%-50s${RST}" "$msg"
    # run command, capture output and status
    output=$("$@" 2>&1)
    rc=$?
    if [ $rc -eq 0 ]; then
        printf "[  ${GREEN}OK${RST}  ]\n"
    else
        printf "[${RED}FAILED${RST}]\n"
        echo "$output" | sed 's/^/    /'
        exit 1
    fi
}

svc() {
    local name="$1"
    printf "  ${BOLD}%-50s${RST}" "Restarting $name..."
    output=$(systemctl restart "$name" 2>&1)
    rc=$?
    if [ $rc -eq 0 ]; then
        printf "[  ${GREEN}OK${RST}  ]\n"
    else
        printf "[${RED}FAILED${RST}]\n"
        echo "$output" | sed 's/^/    /'
    fi
}

echo ""
printf "${CYAN}${BOLD}  ┌─────────────────────────────────────────────┐${RST}\n"
printf "${CYAN}${BOLD}  │           NEWSPAPER  ·  DEPLOY              │${RST}\n"
printf "${CYAN}${BOLD}  └─────────────────────────────────────────────┘${RST}\n"
echo ""

step "Pulling latest from origin..."        git pull origin master
step "Installing dependencies..."            uv sync
step "Running database migrations..."        uv run python manage.py migrate
step "Compiling translations..."             uv run python manage.py compilemessages
step "Collecting static files..."            uv run python manage.py collectstatic --no-input --clear

echo ""
printf "  ${DIM}── services ──${RST}\n"

svc newspaper-gunicorn
svc newspaper-daphne
svc newspaper-celery

echo ""
printf "  ${GREEN}${BOLD}Deploy complete.${RST}\n"
echo ""
