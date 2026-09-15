# syntax=docker/dockerfile:1

# Cloud in a Bottle builds this with rootless podman and routes HTTP to it.
# Two processes run inside: cron rebuilds the page every half hour, and a small
# stdlib web server answers the router. See bin/entrypoint.sh.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/opt/matplotlib \
    PORT=8080

# cron: the half-hourly trigger.
# tzdata: so TZ (e.g. TZ=America/Anchorage) resolves to a real zone.
# ca-certificates: HTTPS to the calendar feed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        cron \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first: this layer is cached across rebuilds that only touch code.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Build matplotlib's font cache now rather than on the first cron run, where it
# would add several seconds to a job that should be quick. MPLCONFIGDIR points
# at this baked-in directory, so the cache survives into every container.
RUN mkdir -p "$MPLCONFIGDIR" \
    && python -c "import matplotlib.pyplot" \
    && chmod -R a+rX "$MPLCONFIGDIR"

COPY src/ ./src/
COPY templates/ ./templates/
COPY static/ ./static/
COPY bin/ ./bin/

# Debian's cron ignores files in /etc/cron.d that are group- or world-writable,
# or whose name contains a dot -- hence the explicit mode and the rename.
RUN chmod 0755 /app/bin/*.sh \
    && install -m 0644 /app/bin/dashboard.cron /etc/cron.d/dashboard

# Must match [runtime.container].port in cloudinabottle.toml. Documentation
# only -- the server binds $PORT.
EXPOSE 8080

# The platform performs its own health check against [routing].health_check;
# this one is for plain `docker run` / `podman run` outside the Bottle.
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; \
urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8080')}/healthz\", timeout=4)" \
    || exit 1

# Runs as root *inside the container*. Under the rootless podman that Cloud in a
# Bottle uses, that maps to an unprivileged user on the host. cron needs it, and
# so does writing to PID 1's stdout from a cron job.
ENTRYPOINT ["/app/bin/entrypoint.sh"]
