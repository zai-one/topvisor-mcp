from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from zai_topvisor.config import ServiceConfig
from zai_topvisor.server import AdmittedHttpClient, create_server
from zai_topvisor.transport import ProviderRateLimited, ProviderTransportError

SECRET = "synthetic-topvisor-key-never-live"
CONTRACT = json.loads((Path(__file__).resolve().parents[1] / "contracts/topvisor.json").read_text())["tools"]
WRITE = {"project_id": 1, "keyword_id": 2, "tags": [3], "apply": True, "idempotency_key": "change-1"}
READ_TOOLS = {
    "topvisor_positions_history",
    "topvisor_list_projects",
    "topvisor_list_keywords",
    "topvisor_get_project_setup",
    "topvisor_list_folders",
    "topvisor_list_groups",
    "topvisor_search_regions",
}
WRITE_TOOLS = {
    "topvisor_create_project",
    "topvisor_create_folder",
    "topvisor_create_groups",
    "topvisor_import_keywords",
    "topvisor_add_keywords",
    "topvisor_set_keyword_target",
    "topvisor_set_keyword_tags",
    "topvisor_add_searcher",
    "topvisor_add_region",
    "topvisor_import_regions",
    "topvisor_apply",
}


@pytest.fixture(scope="module")
def pair() -> RSAKeyPair:
    return RSAKeyPair.generate()


def config(path: Path, pair: RSAKeyPair, **kwargs: Any) -> ServiceConfig:
    return replace(
        ServiceConfig(
            user_id="1", api_key=SECRET, state_path=path / "state.sqlite", public_key=pair.public_key
        ),
        **kwargs,
    )


def token(
    pair: RSAKeyPair, *, scopes: list[str] | None = None, account: str = "default", actor: str = "operator"
) -> str:
    return pair.create_token(
        subject=actor,
        issuer="topvisor-operator",
        audience="topvisor-mcp",
        scopes=scopes if scopes is not None else ["topvisor:read", "topvisor:write"],
        expires_in_seconds=60,
        additional_claims={"account_id": account},
    )


@asynccontextmanager
async def connection(server: Any, bearer: str):
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True)

    # FastMCP expects a synchronous factory returning an AsyncClient.
    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    async with (
        app.router.lifespan_context(app),
        Client(
            StreamableHttpTransport("http://fixture/mcp", auth=bearer, httpx_client_factory=client_factory)
        ) as client,
    ):
        yield client


class Recorder:
    def __init__(self, *, fail: Exception | None = None):
        self.calls: list[tuple[str, str, Any, bool]] = []
        self.fail = fail

    def factory(self, store: Any, execution_id: str, actor: str) -> AdmittedHttpClient:
        owner = self

        class Http(AdmittedHttpClient):
            async def request(
                self, method: str, url: str, *, headers=None, payload=None, params=None, idempotent=False
            ) -> Any:
                await self._admit_attempt(1)
                owner.calls.append((method, url, payload, idempotent))
                if owner.fail:
                    raise owner.fail
                return {"result": [], "total": 0, "innocent": SECRET}

        return Http(store, execution_id, actor)


async def test_original_surface_runs_and_counts_every_write_and_readback(tmp_path: Path, pair: RSAKeyPair):
    recorder = Recorder()
    settings = config(tmp_path, pair, write_enabled=True)
    server = create_server(settings, transport="stdio", http_factory=recorder.factory)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert names == READ_TOOLS | WRITE_TOOLS
        for tool in await client.list_tools():
            if tool.name not in CONTRACT:
                assert tool.name == "topvisor_positions_history"
                continue
            assert {
                "inputSchema": tool.inputSchema,
                "outputSchema": tool.outputSchema,
                "description": tool.description,
            } == CONTRACT[tool.name]
        dry = (await client.call_tool("topvisor_set_keyword_tags", {**WRITE, "apply": False})).data
        assert dry["dry_run"] and not dry["applied"] and not recorder.calls
        result = (await client.call_tool("topvisor_set_keyword_tags", WRITE)).data
        assert result["applied"] and result["provider"] == "topvisor"
        assert result["readback"]["total"] == 0
        assert SECRET not in json.dumps(result)
        assert [call[3] for call in recorder.calls] == [False, True]
    with sqlite3.connect(settings.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2
        assert db.execute("SELECT status FROM writes").fetchone()[0] == "applied"
    assert SECRET.encode() not in settings.state_path.read_bytes()


async def test_idempotency_persists_restart_and_rejects_different_payload(tmp_path: Path, pair: RSAKeyPair):
    recorder = Recorder()
    settings = config(tmp_path, pair, write_enabled=True)
    first = None
    for _ in range(2):
        async with Client(
            create_server(settings, transport="stdio", http_factory=recorder.factory)
        ) as client:
            result = (await client.call_tool("topvisor_set_keyword_tags", WRITE)).data
            assert first is None or result == first
            first = result
            with pytest.raises(ToolError, match="provider_error"):
                await client.call_tool("topvisor_set_keyword_tags", {**WRITE, "tags": [4]})
    assert len(recorder.calls) == 2


async def test_interrupted_write_remains_pending_and_does_not_repeat(tmp_path: Path, pair: RSAKeyPair):
    settings = config(tmp_path, pair, write_enabled=True)
    recorder = Recorder(fail=ProviderTransportError(SECRET))
    for _ in range(2):
        async with Client(
            create_server(settings, transport="stdio", http_factory=recorder.factory)
        ) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool("topvisor_set_keyword_tags", WRITE)
            assert SECRET not in str(caught.value)
    assert len(recorder.calls) == 1
    with sqlite3.connect(settings.state_path) as db:
        assert db.execute("SELECT status FROM writes").fetchone()[0] == "pending"


async def test_write_flag_and_delete_allowlist_fail_before_network(tmp_path: Path, pair: RSAKeyPair):
    recorder = Recorder()
    async with Client(
        create_server(config(tmp_path, pair), transport="stdio", http_factory=recorder.factory)
    ) as client:
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_set_keyword_tags", WRITE)
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_apply",
                {"operation": ["del", "projects_2", "projects"], "params": {"project_id": 1}},
            )
    assert recorder.calls == []


async def test_http_scopes_and_account_cannot_be_bypassed(tmp_path: Path, pair: RSAKeyPair):
    recorder = Recorder()
    server = create_server(config(tmp_path, pair, write_enabled=True), http_factory=recorder.factory)
    async with connection(server, token(pair, scopes=["topvisor:read"])) as client:
        assert {tool.name for tool in await client.list_tools()} == READ_TOOLS
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_set_keyword_tags", WRITE)
    async with connection(server, token(pair, account="another-account")) as client:
        with pytest.raises(ToolError, match="provider_disabled"):
            await client.call_tool("topvisor_list_projects", {})
    assert recorder.calls == []


async def test_principals_have_separate_idempotency_namespaces(tmp_path: Path, pair: RSAKeyPair):
    recorder = Recorder()
    server = create_server(config(tmp_path, pair, write_enabled=True), http_factory=recorder.factory)
    for actor in ["alice", "bob", "alice"]:
        async with connection(server, token(pair, actor=actor)) as client:
            await client.call_tool("topvisor_set_keyword_tags", WRITE)
    assert len(recorder.calls) == 4


async def test_upstream_cooldown_persists_restart(tmp_path: Path, pair: RSAKeyPair):
    settings = config(tmp_path, pair)
    recorder = Recorder(fail=ProviderRateLimited(SECRET, retry_after_seconds=3600))
    for _ in range(2):
        async with Client(
            create_server(settings, transport="stdio", http_factory=recorder.factory)
        ) as client:
            with pytest.raises(ToolError, match="provider_rate_limited"):
                await client.call_tool("topvisor_list_projects", {})
    assert len(recorder.calls) == 1


@pytest.mark.parametrize("external_cancel", [False, True])
async def test_cancellation_stops_upstream_and_preserves_pending_write(
    tmp_path: Path, pair: RSAKeyPair, monkeypatch: pytest.MonkeyPatch, external_cancel: bool
):
    started, stopped = asyncio.Event(), asyncio.Event()
    settings = config(tmp_path, pair, write_enabled=True)
    monkeypatch.setattr("zai_topvisor.server.OPERATION_TIMEOUT_SECONDS", 0.1)

    class Slow(AdmittedHttpClient):
        async def request(self, *args: Any, **kwargs: Any):
            await self._admit_attempt(1)
            started.set()
            try:
                await asyncio.sleep(5)
            finally:
                stopped.set()

    server = create_server(settings, transport="stdio", http_factory=Slow)
    tool = await server.get_tool("topvisor_set_keyword_tags")
    task = asyncio.create_task(tool.fn(**WRITE))
    await asyncio.wait_for(started.wait(), timeout=2)
    if external_cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if external_cancel else ToolError):
        await task
    assert stopped.is_set()
    with sqlite3.connect(settings.state_path) as db:
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
        assert db.execute("SELECT status FROM writes").fetchone()[0] == "pending"
        assert db.execute("SELECT outcome FROM calls").fetchone()[0] == (
            "cancelled" if external_cancel else "error"
        )


async def test_installed_stdio_entrypoint_has_real_tools(tmp_path: Path):
    credential = tmp_path / "synthetic.token"
    credential.write_text(SECRET)
    credential.chmod(0o600)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "zai_topvisor"],
        cwd=str(tmp_path),
        env={
            "TOPVISOR_USER_ID": "1",
            "TOPVISOR_API_KEY_FILE": str(credential),
            "TOPVISOR_STATE_PATH": str(tmp_path / "state.sqlite"),
        },
        keep_alive=False,
    )
    async with Client(transport, timeout=30) as client:
        assert {tool.name for tool in await client.list_tools()} == READ_TOOLS | WRITE_TOOLS
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_set_keyword_tags", WRITE)


@pytest.mark.parametrize("bearer", [None, "invalid.signature.token"])
async def test_http_requires_valid_signature_before_protocol_execution(
    tmp_path: Path, pair: RSAKeyPair, bearer
):
    recorder = Recorder()
    server = create_server(config(tmp_path, pair), http_factory=recorder.factory)
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True)
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client,
    ):
        response = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
            },
        )
    assert response.status_code in {401, 403}
    assert recorder.calls == []
