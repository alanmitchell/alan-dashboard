#!/usr/bin/env bash
# Wrapper that cron invokes. Its only job is to restore the environment that
# cron strips, then hand off to the generator.
set -euo pipefail

if [ -r /app/.cron.env ]; then
    # shellcheck source=/dev/null
    . /app/.cron.env
fi

cd /app
exec python -m dashboard.generate
