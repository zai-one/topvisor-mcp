"""Read-only update suggestion: compare the installed version with the latest GitHub release.

Never installs anything. One unauthenticated HTTPS GET to the public GitHub API, a short
timeout, a ~24h local cache, a 30-minute pause after a failed attempt and graceful failure
offline. Opt out with TOPVISOR_DISABLE_UPDATE_CHECK=1.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from zai_topvisor import __version__

REPOSITORY = "zai-one/topvisor-mcp"
DISTRIBUTION = "zai-topvisor-mcp"
WHEEL_PREFIX = "zai_topvisor_mcp"
DISPLAY_NAME = "Topvisor MCP"
CHECK_TOOL = "topvisor_check_update"
ENV_DISABLE = "TOPVISOR_DISABLE_UPDATE_CHECK"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
CACHE_FILE = "update-check.json"
CACHE_TTL_SECONDS = 24 * 3600
FAILURE_BACKOFF_SECONDS = 30 * 60
FORCE_MIN_INTERVAL_SECONDS = 60
TIMEOUT_SECONDS = 3.0
# Plain numeric tags only (ASCII digits, optional leading "v"); anything else is "no release".
_TAG = re.compile(r"v?([0-9]{1,6}(?:\.[0-9]{1,6}){0,3})")
_RELEASE_URL = re.compile(re.escape(RELEASES_URL) + r"(?:/tag/v?[0-9]{1,6}(?:\.[0-9]{1,6}){0,3})?")
_TRUE = {"1", "true", "yes", "on"}
_LOCK = threading.Lock()

Fetch = Callable[[], dict[str, Any]]


def disabled() -> bool:
    return os.environ.get(ENV_DISABLE, "").strip().casefold() in _TRUE


def _plain_version(value: object) -> str | None:
    """Return the canonical digits-and-dots form of a plain version tag, else None."""
    if not isinstance(value, str):
        return None
    match = _TAG.fullmatch(value)
    return match.group(1) if match else None


def parse_version(value: object) -> tuple[int, ...] | None:
    plain = _plain_version(value)
    if plain is None:
        return None
    parts = [int(part) for part in plain.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _release_url(value: object) -> str | None:
    return value if isinstance(value, str) and _RELEASE_URL.fullmatch(value) else None


def update_command(version: str) -> str:
    wheel = f"{WHEEL_PREFIX}-{version}-py3-none-any.whl"
    url = f"https://github.com/{REPOSITORY}/releases/download/v{version}/{wheel}"
    return f'uv tool install --force "{DISTRIBUTION} @ {url}"'


def fetch_latest_release() -> dict[str, Any]:
    response = httpx.get(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{DISTRIBUTION}/{__version__} update-check",
        },
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
    )
    response.raise_for_status()
    if len(response.content) > 1_000_000:
        raise ValueError("release metadata too large")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("unexpected release metadata")
    return payload


def _release_record(payload: dict[str, Any], now: float) -> dict[str, Any]:
    version = _plain_version(payload.get("tag_name"))
    if version is None or payload.get("draft") or payload.get("prerelease"):
        raise ValueError("latest release has no stable version tag")
    url = _release_url(payload.get("html_url")) or RELEASES_URL
    return {"latest_version": version, "release_url": url, "checked_at": now}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _read_cache(path: Path) -> dict[str, Any]:
    """Validated cache state: last good release (or None) and the last fetch attempt."""
    state: dict[str, Any] = {"release": None, "attempted_at": None, "failed": False}
    try:
        if path.stat().st_size > 4096:
            return state
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if not isinstance(data, dict):
        return state
    version, url = _plain_version(data.get("latest_version")), _release_url(data.get("release_url"))
    if version is not None and url is not None and _number(data.get("checked_at")):
        state["release"] = {"latest_version": version, "release_url": url, "checked_at": data["checked_at"]}
    attempted = data.get("attempted_at")
    if _number(attempted):
        state["attempted_at"] = attempted
        state["failed"] = data.get("attempt_failed") is True
    elif state["release"] is not None:  # cache written before attempts were recorded
        state["attempted_at"] = state["release"]["checked_at"]
    return state


def _write_cache(path: Path, release: dict[str, Any] | None, attempted_at: float, failed: bool) -> None:
    record: dict[str, Any] = {**(release or {}), "attempted_at": attempted_at, "attempt_failed": failed}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass  # The cache is an optimisation; never fail the caller.


def _within(start: float | None, now: float, seconds: float) -> bool:
    return start is not None and 0 <= now - start < seconds


def _blocked(state: dict[str, Any], now: float, force: bool) -> str | None:
    """Why no fetch should happen now ("fresh", "throttled", "backoff"), or None to fetch."""
    release, attempted = state["release"], state["attempted_at"]
    if force:
        return "throttled" if _within(attempted, now, FORCE_MIN_INTERVAL_SECONDS) else None
    if release is not None and _within(release["checked_at"], now, CACHE_TTL_SECONDS):
        return "fresh"
    if state["failed"] and _within(attempted, now, FAILURE_BACKOFF_SECONDS):
        return "backoff"
    return None


def _view(record: dict[str, Any], source: str) -> dict[str, Any]:
    latest = record["latest_version"]
    current, newest = parse_version(__version__), parse_version(latest)
    available = bool(current is not None and newest is not None and newest > current)
    return {
        "enabled": True,
        "status": "ok",
        "source": source,
        "current_version": __version__,
        "latest_version": latest,
        "update_available": available,
        "release_url": record["release_url"],
        "update_command": update_command(latest) if available else None,
        "checked_at_unix": int(record["checked_at"]),
        "auto_update": False,
        "note": "Suggestion only; nothing is installed automatically. Restart the MCP client after updating.",
    }


def _unavailable(error: str, release: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "enabled": True,
        "status": "unavailable",
        "current_version": __version__,
        "update_available": None,
        "error": error,
        "releases_url": RELEASES_URL,
    }
    if release is not None:
        result["last_known"] = _view(release, "stale_cache")
    return result


def check_update(
    cache_path: Path, *, force: bool = False, fetch: Fetch | None = None, now: float | None = None
) -> dict[str, Any]:
    """Return current/latest version and an update command; never raises."""
    if disabled():
        return {
            "enabled": False,
            "status": "disabled",
            "current_version": __version__,
            "update_available": None,
            "note": f"Update checks are disabled by {ENV_DISABLE}.",
        }
    if fetch is None:
        fetch = fetch_latest_release  # resolved at call time so tests can patch the module
    # One attempt at a time per process, so concurrent callers see the recorded attempt.
    with _LOCK:
        now = time.time() if now is None else now
        state = _read_cache(cache_path)
        release = state["release"]
        reason = _blocked(state, now, force)
        if reason == "fresh" or (reason == "throttled" and release is not None and not state["failed"]):
            return _view(release, "cache")
        if reason is not None:
            return _unavailable("recent_attempt_failed" if state["failed"] else "recently_checked", release)
        try:
            record = _release_record(fetch(), now)
        except Exception as exc:  # offline, rate limited, malformed: degrade quietly
            _write_cache(cache_path, release, now, failed=True)
            return _unavailable(type(exc).__name__, release)
        _write_cache(cache_path, record, now, failed=False)
        return _view(record, "github")


def cached_hint(cache_path: Path) -> str | None:
    """Short startup hint from the local cache only; never touches the network."""
    if disabled():
        return None
    release = _read_cache(cache_path)["release"]
    if release is None:
        return None
    view = _view(release, "cache")
    if not view["update_available"]:
        return None
    return (
        f"{DISPLAY_NAME} {view['latest_version']} is available (installed {__version__}). "
        f"Mention it once to the user if relevant; {CHECK_TOOL} returns release notes and the update command."
    )


def refresh_in_background(cache_path: Path) -> threading.Thread | None:
    """Refresh a stale cache in a daemon thread so the next start can show a hint.

    Obeys the same cache, failure back-off and throttle rules as the tool.
    """
    if disabled() or _blocked(_read_cache(cache_path), time.time(), force=False) is not None:
        return None
    thread = threading.Thread(target=check_update, args=(cache_path,), name="update-check", daemon=True)
    thread.start()
    return thread
