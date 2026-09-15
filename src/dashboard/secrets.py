"""Reading secrets from the Bottle's secrets service.

Cloud in a Bottle has no way to set arbitrary environment variables on an
installed app. Values that must not live in the git repository come from the
pre-installed **Secrets** app instead, which this app declares a grant for in
``cloudinabottle.toml``::

    [[services.v2.consumes]]
    service = "github.com/imbue-openhost/openhost/services/secrets"
    shortname = "secrets"
    version = ">=0.1.0"
    grants = [{ key = "CALENDAR_ICS_URLS" }]

The router mediates the call and authenticates it with ``BOTTLE_APP_TOKEN``,
which is injected per app. Outside a Bottle (plain ``docker run``, tests) there
is no router, and :func:`get_secret` reports that rather than failing -- local
development keeps using ``--env-file``.

Nothing here is ever logged: the token is a bearer credential and the values are
the secrets themselves.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import requests

log = logging.getLogger("dashboard.secrets")

_ENDPOINT = "/api/services/v2/call/secrets/get"

# Values are fetched once per process. A generate run is short-lived, so this is
# really about not making the same call once per source.
_cache: dict[tuple[str, str], str] = {}
_lock = threading.Lock()


class SecretsUnavailable(RuntimeError):
    """The service is configured but could not be read.

    Distinct from "no secrets service here at all", which is not an error.
    """


def reset_cache() -> None:
    """Drop cached values. Used by tests; harmless elsewhere."""
    with _lock:
        _cache.clear()


def _service() -> tuple[str, str] | None:
    """Router URL and app token, or ``None`` when not running on a Bottle."""
    router = os.environ.get("BOTTLE_ROUTER_URL", "").strip().rstrip("/")
    token = os.environ.get("BOTTLE_APP_TOKEN", "").strip()
    if not router or not token:
        return None
    return router, token


def available() -> bool:
    return _service() is not None


def _extract(payload: Any, key: str) -> str | None:
    """Pull one key out of the service's reply.

    The manual documents the request but not the response shape, so accept the
    obvious encodings and fail loudly on anything else rather than silently
    treating a misread reply as "secret not set".
    """
    if not isinstance(payload, dict):
        raise SecretsUnavailable(f"unexpected reply type {type(payload).__name__}")

    for container in (payload, payload.get("secrets"), payload.get("values"),
                      payload.get("data"), payload.get("result")):
        if isinstance(container, dict) and key in container:
            value = container[key]
            if value is None:
                return None
            if not isinstance(value, str):
                raise SecretsUnavailable(f"{key!r} is {type(value).__name__}, not a string")
            return value

    # The service answered and simply has no such key: the owner has not set it.
    if any(
        isinstance(payload.get(name), dict)
        for name in ("secrets", "values", "data", "result")
    ) or not payload:
        return None
    raise SecretsUnavailable("could not find a key/value mapping in the reply")


def get_secret(key: str, config) -> str:
    """Return the secret's value.

    Returns ``""`` when there is no secrets service (not on a Bottle) or when
    the owner has not set this key. Raises :class:`SecretsUnavailable` when the
    service exists but the call fails, so the caller can say so instead of
    showing a misleading "not configured" message.
    """
    service = _service()
    if service is None:
        return ""
    router, token = service

    cache_key = (router, key)
    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]

    try:
        response = requests.post(
            f"{router}{_ENDPOINT}",
            json={"keys": [key]},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=config.http_timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except SecretsUnavailable:
        raise
    except Exception as exc:
        # Deliberately no token, no URL query, no body in the message.
        raise SecretsUnavailable(f"{type(exc).__name__}: {exc}") from exc

    value = _extract(payload, key) or ""
    with _lock:
        _cache[cache_key] = value
    log.info("read %r from the secrets service (%s)", key, "set" if value else "unset")
    return value
