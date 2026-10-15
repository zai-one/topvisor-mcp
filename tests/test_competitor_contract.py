from __future__ import annotations

import sqlite3
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_semantics import operator_accepts
from test_server import config, connection, token

from zai_topvisor import semantics
from zai_topvisor.policy import PolicyStore
from zai_topvisor.semantics import competitor_payload
from zai_topvisor.server import create_server
from zai_topvisor.transport import ProviderError, request_hash

ADD = {"action": "add", "project_id": 7, "url": "https://synthetic.invalid", "name": "Example"}


def test_add_emits_one_competitor_with_scalar_brand_fields():
    assert competitor_payload(
        "add",
        7,
        url="https://www.synthetic.invalid/",
        name=" Example ",
        brand_name="Example Brand",
        service_name="aiTracker",
        brand_aliases=["Alias", "Alias"],
    ) == {
        "project_id": 7,
        "url": "synthetic.invalid",
        "name": "Example",
        "brand_name": "Example Brand",
        "service_name": "aiTracker",
        "brand_aliases": ["Alias"],
    }


def test_single_item_legacy_arguments_normalize_before_approval_and_idempotency():
    assert competitor_payload("add", 7, urls=["https://synthetic.invalid"], names=["Example"]) == (
        competitor_payload("add", 7, url="synthetic.invalid", name="Example")
    )


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"url": []},
        {"url": ""},
        {"url": "bad url"},
        {"urls": []},
        {"urls": ["first.invalid", "second.invalid"]},
        {"url": "first.invalid", "urls": ["first.invalid"]},
        {"url": "first.invalid", "names": ["First", "Second"]},
        {"url": "first.invalid", "names": [None]},
        {"url": "first.invalid", "name": "First", "names": ["First"]},
        {"url": "first.invalid", "name": ["First"]},
        {"url": "first.invalid", "name": " "},
        {"url": "first.invalid", "brand_name": ["Brand"]},
        {"url": "first.invalid", "brand_name": " "},
        {"url": "first.invalid", "brand_names": ["Brand"]},
        {"url": "first.invalid", "service_name": "other"},
        {"url": "first.invalid", "brand_aliases": "Alias"},
    ],
)
def test_invalid_or_ambiguous_add_is_refused(args):
    with pytest.raises(ValueError):
        competitor_payload("add", 7, **args)


@pytest.mark.parametrize("transport", ["stdio", "http"])
@pytest.mark.parametrize("legacy", [False, True])
async def test_mcp_add_binds_normalized_scalar_payload_and_preserves_replay(
    tmp_path: Path,
    monkeypatch,
    transport,
    legacy,
):
    sent = []

    async def fake_request(runtime, endpoint, payload, *, read=True):
        sent.append((endpoint, payload, read))
        return {"result": {"id": 9}}

    monkeypatch.setattr(semantics, "request", fake_request)
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    pair = RSAKeyPair.generate()
    server = create_server(config(tmp_path, pair, write_enabled=True), transport=transport)
    args = {"action": "add", "project_id": 7, "urls": [ADD["url"]], "names": [ADD["name"]]} if legacy else ADD
    args = {**args, "brand_name": "Example Brand", "service_name": "aiTracker", "brand_aliases": ["Alias"]}
    expected = {
        "project_id": 7,
        "url": "synthetic.invalid",
        "name": "Example",
        "brand_name": "Example Brand",
        "service_name": "aiTracker",
        "brand_aliases": ["Alias"],
    }
    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(
            Client(server) if transport == "stdio" else connection(server, token(pair))
        )
        tool = next(tool for tool in await client.list_tools() if tool.name == "topvisor_competitors_write")
        assert {"url", "name", "brand_name", "service_name", "brand_aliases"} <= tool.inputSchema[
            "properties"
        ].keys()
        ticket = (await client.call_tool("topvisor_competitors_write", args)).data
        assert ticket["request"] == {"endpoint": "add/projects_2/competitors", "payload": expected}
        assert not sent
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_competitors_write", {**args, "approval_id": ticket["approval_id"]}
            )
        operator_accepts(ticket)
        for change in (
            {"project_id": 8},
            {"urls": ["other.invalid"]} if legacy else {"url": "other.invalid"},
            {"names": ["Other"]} if legacy else {"name": "Other"},
            {"brand_name": "Other"},
            {"service_name": "positions"},
            {"brand_aliases": ["Other"]},
        ):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "topvisor_competitors_write", {**args, **change, "approval_id": ticket["approval_id"]}
                )
        assert not sent
        first = (
            await client.call_tool(
                "topvisor_competitors_write", {**args, "approval_id": ticket["approval_id"]}
            )
        ).data
        assert first["applied"] and sent == [
            ("add/projects_2/competitors", expected, False),
            ("get/projects_2/competitors", {"project_id": 7, "limit": 100, "offset": 0}, True),
        ]
        # A fresh accepted ticket for the same normalized request replays the durable receipt.
        scalar = {**args, "url": ADD["url"], "name": ADD["name"]}
        scalar.pop("urls", None)
        scalar.pop("names", None)
        again = (await client.call_tool("topvisor_competitors_write", scalar)).data
        operator_accepts(again)
        replay = (
            await client.call_tool(
                "topvisor_competitors_write", {**scalar, "approval_id": again["approval_id"]}
            )
        ).data
        assert replay == first and len(sent) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"url": ["first.invalid", "second.invalid"]},
        {"urls": ["first.invalid", "second.invalid"]},
        {"names": ["First", "Second"]},
        {"brand_names": ["Brand"]},
    ],
)
async def test_mcp_refuses_legacy_bulk_and_removed_fields_before_approval(tmp_path, monkeypatch, change):
    async def no_provider(*args, **kwargs):
        raise AssertionError("invalid add reached provider")

    monkeypatch.setattr(semantics, "request", no_provider)
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    pair = RSAKeyPair.generate()
    server = create_server(config(tmp_path, pair, write_enabled=True), transport="stdio")
    async with Client(server) as client:
        args = {**ADD, **change}
        if "urls" in change:
            args.pop("url")
        if "names" in change:
            args.pop("name")
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_competitors_write", args)


async def test_http_read_scope_cannot_prepare_competitor_add(tmp_path, monkeypatch):
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    pair = RSAKeyPair.generate()
    server = create_server(config(tmp_path, pair, write_enabled=True))
    async with connection(server, token(pair, scopes=["topvisor:read"])) as client:
        assert "topvisor_competitors_write" not in {tool.name for tool in await client.list_tools()}
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_competitors_write", ADD)


async def test_disabled_writes_cannot_prepare_competitor_add(tmp_path, monkeypatch):
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    pair = RSAKeyPair.generate()
    server = create_server(config(tmp_path, pair, write_enabled=False), transport="stdio")
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_competitors_write", ADD)


def legacy_hash():
    return request_hash(
        {
            "provider": "topvisor",
            "tool": "topvisor_competitors_write",
            "arguments": {
                "endpoint": "add/projects_2/competitors",
                "payload": {"project_id": 7, "urls": ["synthetic.invalid"], "names": ["Example"]},
            },
        }
    )


@pytest.mark.parametrize("explicit_key", [False, True])
@pytest.mark.parametrize("metadata", [{}, {"brand_name": "Brand", "service_name": "aiTracker"}])
async def test_pre_upgrade_pending_add_blocks_new_payload_before_approval_consumption(
    tmp_path,
    monkeypatch,
    explicit_key,
    metadata,
):
    async def no_provider(*args, **kwargs):
        raise AssertionError("unknown pre-upgrade add was dispatched again")

    monkeypatch.setattr(semantics, "request", no_provider)
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    pair = RSAKeyPair.generate()
    settings = config(tmp_path, pair, write_enabled=True)
    store = PolicyStore(settings.state_path, settings.account_id, 100, 100)
    server = create_server(settings, transport="stdio")
    async with Client(server) as client:
        args = {**ADD, **metadata}
        ticket = (await client.call_tool("topvisor_competitors_write", args)).data
        operator_accepts(ticket)
        digest = legacy_hash()
        store.reserve_write(
            "previous-actor",
            "old-explicit-key" if explicit_key else digest,
            "topvisor_competitors_write",
            digest,
        )
        with pytest.raises(ToolError, match='"code":"provider_error"'):
            await client.call_tool(
                "topvisor_competitors_write", {**args, "approval_id": ticket["approval_id"]}
            )
        with sqlite3.connect(settings.state_path) as db:
            assert db.execute(
                "SELECT accepted,consumed FROM approvals WHERE id=?", (ticket["approval_id"],)
            ).fetchone() == (1, None)
        # The migration fence is specific to the old request and configured account.
        other = (await client.call_tool("topvisor_competitors_write", {**ADD, "url": "other.invalid"})).data
        assert other["needs_operator_approval"]


def test_legacy_pending_guard_is_rechecked_in_atomic_reservation(tmp_path):
    first = PolicyStore(tmp_path / "state.sqlite", "A", 100, 100)
    second = PolicyStore(tmp_path / "state.sqlite", "A", 100, 100)
    digest = legacy_hash()
    first.require_legacy_write_reconciled("topvisor_competitors_write", digest)
    second.reserve_write("previous", "old", "topvisor_competitors_write", digest)
    with pytest.raises(ProviderError, match="pending manual reconciliation"):
        first.reserve_write(
            "current", "new", "topvisor_competitors_write", "new-digest", legacy_digest=digest
        )
    other_account = PolicyStore(tmp_path / "state.sqlite", "B", 100, 100)
    assert (
        other_account.reserve_write(
            "current", "new", "topvisor_competitors_write", "new-digest", legacy_digest=digest
        )
        is None
    )
