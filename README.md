# alan-dashboard

A single-page dashboard of home and activity information, rebuilt every half
hour by cron and served from a container on a
[Cloud in a Bottle](https://cloudinabottle.org/) instance.

The page is one self-contained HTML file: charts are inline SVG and the
stylesheet is inlined, so there are no other assets to serve and nothing is
fetched from a CDN at view time.

## How it fits together

```
          every 30 min                      on every request
cron ──────────────────────▶ generate.py    serve.py ◀──────── Bottle router ◀── you
                                  │             │
                    sources/ ─────┤             │
                    charts.py ────┤             │
                    templates/ ───┘             │
                                  ▼             ▼
                        $BOTTLE_APP_TEMP_DIR/site/index.html
```

Two processes run in the container, both started by `bin/entrypoint.sh`:

| Process | Role |
|---|---|
| `cron` | Runs `python -m dashboard.generate` on the hour and the half hour. |
| `dashboard.serve` | Serves the generated file, plus `/healthz`. |

The split matters: Cloud in a Bottle routes HTTP to your container, so writing
a file to disk is not enough — something has to answer the socket. If either
process dies the entrypoint exits, so the platform restarts the container
rather than serving a page that quietly stopped updating.

### Layout

```
cloudinabottle.toml      App manifest (resources, routing, storage tiers)
Dockerfile               Image: python:3.12-slim + cron
bin/entrypoint.sh        PID 1: snapshots env, starts cron + server
bin/generate.sh          What cron actually invokes
bin/dashboard.cron       Installed to /etc/cron.d/dashboard
src/dashboard/
  config.py              Everything configurable, read from the environment
  generate.py            Collect → render → atomic write
  serve.py               Static server for the generated page
  charts.py              matplotlib → inline SVG
  theme.py               Palette, shared by the CSS and the charts
  sources/               One module per data source
templates/               Jinja2
static/style.css         Inlined into the page at render time
tests/
```

## Run it locally

```sh
docker build -t alan-dashboard .
docker run --rm -p 8080:8080 \
  -e TZ=America/Anchorage \
  -e DASHBOARD_TITLE="Alan's Home" \
  alan-dashboard
```

Then open <http://127.0.0.1:8080>. The first page is generated at startup, so
you do not wait for the first cron tick.

Without Docker you need the dependencies in `requirements.txt` and:

```sh
PYTHONPATH=src TZ=America/Anchorage python -m dashboard        # generate, then serve
PYTHONPATH=src python -m dashboard.generate                    # generate once
```

## Deploy to a Bottle

1. Push this repository somewhere your Bottle can reach by git URL.
2. In the Bottle dashboard, choose **Deploy New App** and give it that URL.
3. Approve the `secrets` grant the manifest requests.
4. Store your calendar URL in the **Secrets** app under `CALENDAR_ICS_URLS`
   (see [Secrets](#secrets)).
5. It appears at `https://alan-dashboard.<your-zone-domain>/`.

The manifest leaves `public_paths` empty, so the router requires your login on
every path — appropriate for a page showing your home's sensors and your
calendar. If a deploy reports the *health check* failing on authentication
rather than on the app, add `"/healthz"` to `public_paths`; it returns a
constant `ok` and exposes no data.

## Configuration

Non-secret settings are read from the environment. Secrets come from the
Bottle's secrets service; see [Secrets](#secrets) below. Nothing needs a config
file in the repository.

| Variable | Default | Meaning |
|---|---|---|
| `TZ` | `UTC` | Display timezone, e.g. `America/Anchorage`. An unknown zone falls back to UTC rather than failing. |
| `DASHBOARD_TITLE` | `Home Dashboard` | Page heading and `<title>`. |
| `DASHBOARD_SUBTITLE` | — | Optional line under the heading. |
| `CALENDAR_ICS_URLS` | — | Comma-separated iCalendar feeds. Overrides the stored secret; see [Secrets](#secrets). |
| `CALENDAR_LOOKAHEAD_DAYS` | `7` | How far ahead the calendar panel looks. |
| `DASHBOARD_REFRESH_SECONDS` | `1860` | How often the page reloads itself. Keep it slightly longer than the cron interval. |
| `DASHBOARD_HTTP_TIMEOUT` | `15` | Timeout for outbound requests, in seconds. |
| `DASHBOARD_LOG_LEVEL` | `INFO` | Python log level. |
| `DASHBOARD_OUTPUT_DIR` | *(see below)* | Overrides where the site is written. |
| `PORT` | `8080` | Must match `[runtime.container].port` in the manifest. |

Cloud in a Bottle injects `BOTTLE_APP_DATA_DIR` and `BOTTLE_APP_TEMP_DIR`
itself. Output goes to the first of `DASHBOARD_OUTPUT_DIR`,
`BOTTLE_APP_TEMP_DIR`, `BOTTLE_APP_DATA_DIR`, or `./var` — the *temp* tier by
preference, because the page is reproducible on the next cron run and does not
need to occupy backed-up storage.

## Secrets

Cloud in a Bottle has **no mechanism for setting arbitrary environment variables
on an installed app**, and a secret must never go in the Dockerfile — `ENV` and
`ARG` are both baked into image layers and readable with `docker history`, even
if the value never reached git.

So anything sensitive comes from the pre-installed **Secrets** app. The manifest
declares the grant:

```toml
[[services.v2.consumes]]
service = "github.com/imbue-openhost/openhost/services/secrets"
shortname = "secrets"
version = ">=0.1.0"
grants = [{ key = "CALENDAR_ICS_URLS" }]
```

At generate time the app reads it through the router, authenticated with the
`BOTTLE_APP_TOKEN` injected per app:

```
POST $BOTTLE_ROUTER_URL/api/services/v2/call/secrets/get
Authorization: Bearer $BOTTLE_APP_TOKEN
{"keys": ["CALENDAR_ICS_URLS"]}
```

**Resolution order**, implemented in `sources/calendar_feed.py`:

1. The `CALENDAR_ICS_URLS` environment variable, if set.
2. Otherwise the secrets service.
3. Otherwise the panel shows a setup hint.

The environment wins so local `--env-file` development works unchanged, and so
you can override a stored value without editing it. Outside a Bottle there is no
router at all, which is not an error — it just means step 1 is the only source.

If the service *is* configured but the call fails, the calendar panel reports
that explicitly rather than showing the "not configured yet" hint, which would
send you looking in the wrong place. Neither the token nor any secret value is
ever logged.

One caveat: the manual documents the request but not the reply shape, so
`secrets._extract()` accepts a flat mapping or one wrapped in `secrets` /
`values` / `data` / `result`, and raises on anything it cannot recognise rather
than silently reading it as "unset". If your instance answers differently, that
is the one function to adjust.

### Local development

No Bottle, no secrets service — use an env file, which `.gitignore` already
covers:

```sh
cat > .env <<'EOF'
TZ=America/Anchorage
DASHBOARD_TITLE=Alan's Home
CALENDAR_ICS_URLS=Home=https://calendar.google.com/calendar/ical/.../basic.ics
EOF

docker run --rm -p 8080:8080 --env-file .env alan-dashboard
```

`--env-file` takes bare `KEY=value` lines; do not quote the values.

### Connecting Google Calendar

The calendar panel reads **iCal feeds**, not the Google Calendar API. In Google
Calendar: *Settings* → pick the calendar → *Integrate calendar* → **Secret
address in iCal format**. Set it as:

```
Home=https://calendar.google.com/calendar/ical/.../basic.ics
```

Store that string in the Secrets app under `CALENDAR_ICS_URLS`, or put it in
your local `.env` for development.

This avoids an OAuth client, a consent screen and token refresh in a container
nobody logs into. The trade-off is that the URL *is* the credential — anyone
holding it can read that calendar. Never commit it, and rotate it from the same
settings page if it leaks.

Entries are comma-separated, and `Label=URL` names a feed in the UI. A bare URL
gets an automatic name. Any ICS feed works, so you can mix in iCloud, Fastmail,
Nextcloud or a sports schedule.

## Adding a data source

Panels are independent. Write a module in `src/dashboard/sources/` and add one
line to `all_sources()` in `sources/__init__.py`:

```python
from ..charts import bar_chart
from .base import Metric, Source

class RainfallSource(Source):
    key = "rainfall"
    title = "Rainfall"

    def collect(self, config):
        totals = fetch_from_somewhere(timeout=config.http_timeout)
        return self.panel(
            subtitle="Last 7 days",
            metrics=[Metric("This week", f"{sum(totals):.1f}", "mm")],
            chart=bar_chart("rainfall", DAY_NAMES, totals, columns=("Day", "mm")),
        )
```

`collect()` is allowed to raise. `generate.py` catches per source, so an
unreachable service degrades that one card and leaves the rest of the page
intact.

**Three panels currently ship sample data** and say so in the UI:
`home_climate`, `energy` and `activity` are placeholders, each with a `TODO`
marking the single method to replace. Only the calendar is wired to something
real — and it also shows the *Sample data* badge until you configure a feed.

## Changing the schedule

Edit `bin/dashboard.cron` and rebuild. Keep `DASHBOARD_REFRESH_SECONDS` a
little longer than the interval so the browser reloads just *after* a rebuild
rather than just before.

Cron deliberately starts jobs with a near-empty environment, which would hide
the injected `BOTTLE_*` variables from the generator. `bin/entrypoint.sh`
snapshots the relevant variables to `/app/.cron.env` (shell-quoted, mode 600
because it can hold the calendar URL) and `bin/generate.sh` sources it. Job
output is redirected to PID 1's stdout, so `bottle logs alan-dashboard` shows
each run.

## Tests

```sh
docker run --rm --entrypoint bash -v "$PWD":/src -w /src alan-dashboard \
  -c 'pip install -q "pytest~=8.0" && python -m pytest'
```

Or, with the dependencies in `requirements-dev.txt` installed locally:

```sh
python -m pytest
```

The suite covers config parsing, chart-fragment invariants, calendar parsing
(recurrence expansion, all-day ordering, timezone conversion, feed failures),
page rendering and escaping, the atomic write, and the server's status codes.
It makes no network calls.

## Design notes

**Charts are rendered twice, once per theme.** A matplotlib SVG bakes its
colours in and cannot follow `prefers-color-scheme`, so each chart is emitted in
both palettes and CSS shows the matching one. The pair is `aria-hidden`; a real
data table under each chart carries the values, so a screen reader reads the
numbers once rather than the same picture twice.

**Element ids are namespaced per fragment.** Several SVGs share one document.
Duplicate ids would make the browser resolve every reference to whichever copy
came first — a chart clipped to another chart's box. Each figure gets its own
`svg.hashsalt`, and `charts._clean()` then prefixes every id and drops the
decorative ones matplotlib emits for grouping.

**The write is atomic.** The page renders to a temporary file in the output
directory and is then `os.replace`'d into place, so the server never serves a
half-written document.

**Escaping is explicitly on.** `generate.py` sets `autoescape=True` rather than
`select_autoescape()`, which keys off the template's extension and would leave
escaping off for a `.j2` file. Calendar summaries are third-party text.

**Secrets are read, never stored.** `Config` deliberately holds no credential:
it is a dataclass, so it lands in reprs and tracebacks. The token is read from
the environment at call time inside `secrets.py` instead.

**Static, not interactive.** The page has no JavaScript. Charts have no hover
tooltips; the per-chart data table is the way to read exact values. That is the
trade for a page that is one file, works offline, and prints cleanly.

## Licence

MIT — see [LICENSE](LICENSE).
