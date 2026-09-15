#!/usr/bin/env bash
# PID 1 in the container. Runs two things: cron (rebuilds the page every half
# hour) and the web server (answers the router). If either dies, exit so the
# platform restarts the container -- a dashboard that silently stopped updating
# is worse than one that is visibly down.
set -euo pipefail

ENV_FILE=/app/.cron.env

# Cron deliberately starts jobs with a near-empty environment, so the platform's
# injected BOTTLE_* variables and our own settings would be invisible to the
# generator. Snapshot them, shell-quoted, for bin/generate.sh to source.
python - >"$ENV_FILE" <<'PY'
import os
import shlex

KEEP_PREFIXES = ("BOTTLE_", "DASHBOARD_", "CALENDAR_")
KEEP_EXACT = {
    "TZ", "PATH", "PORT", "LANG", "LC_ALL",
    "PYTHONPATH", "PYTHONUNBUFFERED", "MPLBACKEND", "MPLCONFIGDIR",
}

for key, value in sorted(os.environ.items()):
    if key.startswith(KEEP_PREFIXES) or key in KEEP_EXACT:
        print(f"export {key}={shlex.quote(value)}")
PY
# CALENDAR_ICS_URLS is a read capability for your calendar -- treat it like a
# password even inside the container.
chmod 600 "$ENV_FILE"

# Build a page now so the first visitor sees real data instead of waiting up to
# 30 minutes for the first cron tick. A failure here is not fatal: the server
# serves a self-refreshing placeholder until cron succeeds.
if ! /app/bin/generate.sh; then
    echo "entrypoint: initial generation failed; serving placeholder until cron succeeds" >&2
fi

# -f keeps cron in the foreground of its own process; -L 0 silences syslog
# logging, which has nowhere to go in a container. Job output is redirected to
# PID 1's stdout by /etc/cron.d/dashboard instead.
cron -f -L 0 &
cron_pid=$!

python -m dashboard.serve &
server_pid=$!

shutdown() {
    trap - TERM INT
    kill "$cron_pid" "$server_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap shutdown TERM INT

status=0
wait -n || status=$?
shutdown
exit "$status"
