"""Build the dashboard page.  This is what cron runs every half hour.

    python -m dashboard.generate

Two properties worth keeping if you change this file:

* **One source failing degrades one card.**  Every ``collect()`` runs inside a
  try/except, so an unreachable calendar server does not blank the page.
* **The write is atomic.**  The page renders to a temporary file in the output
  directory and is then ``os.replace``'d into place, so the web server never
  serves a half-written document.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import Config, apply_process_timezone
from .sources import Panel, all_sources

log = logging.getLogger("dashboard.generate")

_REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(os.environ.get("DASHBOARD_TEMPLATE_DIR") or _REPO_ROOT / "templates")
STATIC_DIR = Path(os.environ.get("DASHBOARD_STATIC_DIR") or _REPO_ROOT / "static")


def build_environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        # Explicitly True, not select_autoescape(): that helper keys off the
        # template's extension, and ours ends in `.j2`, so it would quietly
        # leave escaping OFF. Calendar summaries are third-party text that
        # lands straight in the page, so this is load-bearing.
        autoescape=True,
        # Catch typo'd variable names at render time instead of silently
        # emitting an empty string into the page.
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment


def collect_panels(config: Config) -> list[Panel]:
    panels: list[Panel] = []
    for source in all_sources():
        try:
            panels.append(source.collect(config))
        except Exception:
            log.exception("source %r failed", source.key)
            panels.append(
                Panel(
                    key=source.key,
                    title=source.title,
                    error=traceback.format_exc(limit=0).strip().splitlines()[-1],
                    empty_message="This source could not be read.",
                )
            )
    return panels


def render(config: Config, panels: list[Panel], generated_at: datetime) -> str:
    template = build_environment().get_template("dashboard.html.j2")
    stylesheet = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    return template.render(
        config=config,
        panels=panels,
        stylesheet=stylesheet,
        generated_at=generated_at,
        generated_label=generated_at.strftime("%a %-d %b, %-H:%M"),
    )


def write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    config = Config.from_env()
    apply_process_timezone(config)
    generated_at = datetime.now(config.timezone)

    panels = collect_panels(config)
    html = render(config, panels, generated_at)
    write_atomically(config.index_path, html)

    broken = [panel.key for panel in panels if panel.error]
    log.info(
        "wrote %s (%d panels, %d bytes)%s",
        config.index_path,
        len(panels),
        len(html.encode("utf-8")),
        f", degraded: {', '.join(broken)}" if broken else "",
    )
    # Cron mails or logs a non-zero exit; a page that rendered with one broken
    # card is still a success, so only a hard failure exits non-zero.
    return 0


if __name__ == "__main__":
    sys.exit(main())
