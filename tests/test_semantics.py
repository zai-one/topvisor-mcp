from __future__ import annotations

import os
import shlex
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from test_agent_layer import settings

from zai_topvisor.semantics import (
    COMPETITOR_WRITES,
    ENDPOINTS,
    PAID,
    competitor_payload,
    paid_payload,
    price_units,
    report_payload,
)
from zai_topvisor.server import create_server


def split_command(command: str) -> list[str]:
    """Split a command line the way the platform's shell hands it to the program."""
    if os.name != "nt":
        return shlex.split(command)
    import ctypes
    from ctypes import wintypes

    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    count = ctypes.c_int()
    argv = parse(command, ctypes.byref(count))
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def operator_accepts(ticket: dict) -> None:
    """Run the returned operator_command exactly as the operator would (no cwd/env assumptions)."""
    from zai_topvisor.approvals import main

    argv = split_command(ticket["operator_command"])
    assert argv[0] == "topvisor-approval"
    assert main(argv[1:]) == 0


def test_report_payloads():
    endpoint, payload = report_payload(
        "positions_summary", 7, region_index=2, date1="2026-10-01", date2="2026-10-08"
    )
    assert endpoint == "get/positions_2/summary"
    assert payload["region_index"] == 2 and payload["show_visibility"] is True and payload["type_range"] == 0
    assert report_payload("tasks", 7)[1]["filters"][0]["values"] == [7]
    assert report_payload("bank_history", None)[1] == {"limit": 100, "offset": 0}
    with pytest.raises(ValueError):
        report_payload("positions_summary", 7)
    with pytest.raises(ValueError):
        report_payload("del_everything", 7)


def test_paid_payloads_and_price():
    volumes = paid_payload("volumes", 7, volume_types=["base", "exact"], group_id=3)
    assert [q["type"] for q in volumes["qualifiers"]] == [1, 3] and volumes["filters"][0]["values"] == [3]
    collect = paid_payload("collect", 7, keywords=["диван", "диван"], searcher="yandex_hints", depth=2)
    assert collect["keywords"] == ["диван"] and collect["qualifiers"] == [
        {"searcher_key": 100, "region_key": 213, "depth": 2}
    ]
    assert price_units({"result": "1.5"}) == 1_500_000
    with pytest.raises(ValueError):
        paid_payload("volumes", 7, searcher="bing")
    writes = set(COMPETITOR_WRITES.values()) | {pair[1] for pair in PAID.values()}
    assert all(e.startswith(("get/", "edit/")) for e in ENDPOINTS - writes)
    assert {e for e in ENDPOINTS if e.startswith("del/")} == {"del/projects_2/competitors"}


def test_relevants_indexing_and_competitor_payloads_follow_openapi():
    price = paid_payload("relevants", 7, keywords=["a"], region_key=2, device="mobile")
    assert price == {
        "keywords": ["a"],
        "qualifiers": [{"searcher_key": 0, "region_key": 2, "region_device": 2}],
    }
    launch = paid_payload("relevants", 7, keywords=["a"], url="https://www.site.ru/", launch=True)
    assert launch["url"] == "site.ru"
    indexing = paid_payload("indexing", 7, urls=["site.ru/a"], indexing_searchers=["google", "bing"])
    assert indexing == {"indexing_searchers_keys": ["1", "5"], "urls": ["site.ru/a"]}
    with pytest.raises(ValueError):
        paid_payload("indexing", 7)
    assert competitor_payload("add", 7, url="https://x.ru") == {"project_id": 7, "url": "x.ru"}
    assert competitor_payload("enable", 7, ids=[3, 3], on=False) == {"project_id": 7, "ids": [3], "on": -1}
    assert competitor_payload("move", 7, id=3, to_id=4) == {
        "project_id": 7,
        "id": 3,
        "to_id": 4,
        "to_type": "after",
    }
    assert competitor_payload("brand", 7, id=3, aliases=["X"]) == {"project_id": 7, "id": 3, "aliases": ["X"]}
    for bad in (("rename", {"id": 3}), ("delete", {}), ("move", {"id": 3, "to_id": 4, "to_type": "in"})):
        with pytest.raises(ValueError):
            competitor_payload(bad[0], 7, **bad[1])


async def test_competitor_write_needs_operator_approval(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import replace

    from zai_topvisor import semantics

    sent = []

    async def fake_request(runtime, endpoint, payload, *, read=True):
        sent.append((endpoint, payload, read))
        return {"result": 1}

    monkeypatch.setattr(semantics, "request", fake_request)
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    config = replace(settings(tmp_path), write_enabled=True)
    async with Client(create_server(config, transport="stdio")) as client:
        args = {"action": "delete", "project_id": 7, "ids": [5]}
        ticket = (await client.call_tool("topvisor_competitors_write", args)).data
        assert ticket["needs_operator_approval"] and sent == []
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_competitors_write", {**args, "approval_id": ticket["approval_id"]}
            )
        operator_accepts(ticket)
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_competitors_write", {**args, "ids": [6], "approval_id": ticket["approval_id"]}
            )
        done = (
            await client.call_tool(
                "topvisor_competitors_write", {**args, "approval_id": ticket["approval_id"]}
            )
        ).data
        assert done["applied"] and sent == [
            ("del/projects_2/competitors", {"project_id": 7, "ids": [5]}, False),
            ("get/projects_2/competitors", {"project_id": 7, "limit": 100, "offset": 0}, True),
        ]
        with pytest.raises(ToolError):  # single use
            await client.call_tool(
                "topvisor_competitors_write", {**args, "approval_id": ticket["approval_id"]}
            )


async def test_optin_tools_and_launch_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    async with Client(create_server(settings(tmp_path), transport="stdio")) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {"topvisor_report", "topvisor_semantics_price", "topvisor_semantics_launch"} <= names
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_semantics_launch",
                {"kind": "volumes", "project_id": 7, "approved_cost": "1", "confirm_cost": True},
            )


def test_payloads_follow_openapi_required_fields():
    # get/content_2/apometr/updates: region_index + date required, no paging.
    endpoint, payload = report_payload("search_updates", None, region_index=1, date1="2026-10-01")
    assert endpoint == "get/content_2/apometr/updates"
    assert payload == {"region_index": 1, "date": "2026-10-01"}
    with pytest.raises(ValueError):
        report_payload("search_updates", None)
    # date1/date2 (or dates) are mandatory for summary and snapshot selectors.
    with pytest.raises(ValueError):
        report_payload("positions_summary", 7, region_index=0)
    with pytest.raises(ValueError):
        report_payload("snapshots_history", 7, region_index=0, date1="2026-10-01")
    # keywords_2/collect: to_group_id only with in_one_group=true.
    collect = paid_payload("collect", 7, keywords=["диван"], group_id=5)
    assert collect["in_one_group"] is True and collect["to_group_id"] == 5


async def test_paid_launch_needs_matching_price_and_operator_approval(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import replace

    from zai_topvisor import semantics

    sent = []

    async def fake_request(runtime, endpoint, payload, *, read=True):
        sent.append(endpoint)
        return {"result": "2"} if endpoint.endswith("/price") else {"result": {"id": 9}}

    monkeypatch.setattr(semantics, "request", fake_request)
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    config = replace(
        settings(tmp_path),
        write_enabled=True,
        check_projects=frozenset({7}),
        check_max_cost="5",
        check_daily_budget="10",
    )
    args = {
        "kind": "relevants",
        "project_id": 7,
        "approved_cost": "2",
        "confirm_cost": True,
        "keywords": ["a"],
        "url": "site.ru",
    }
    async with Client(create_server(config, transport="stdio")) as client:
        ticket = (await client.call_tool("topvisor_semantics_launch", args)).data
        assert ticket["needs_operator_approval"] and sent == ["get/projects_2/tasks/relevants/price"]
        operator_accepts(ticket)
        done = (
            await client.call_tool(
                "topvisor_semantics_launch", {**args, "approval_id": ticket["approval_id"]}
            )
        ).data
    assert done["submitted"] and sent[-1] == "add/projects_2/tasks/relevants"


async def test_paid_launches_share_the_daily_budget(tmp_path: Path, monkeypatch) -> None:
    """Regression: semantics launches used to bypass TOPVISOR_CHECK_DAILY_BUDGET entirely."""
    from dataclasses import replace

    from zai_topvisor import semantics

    sent = []

    async def fake_request(runtime, endpoint, payload, *, read=True):
        sent.append(endpoint)
        return {"result": "2"} if endpoint.endswith("/price") else {"result": {"id": 9}}

    monkeypatch.setattr(semantics, "request", fake_request)
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")
    config = replace(
        settings(tmp_path),
        write_enabled=True,
        check_projects=frozenset({7}),
        check_max_cost="2",
        check_daily_budget="3",
    )
    args = {"kind": "volumes", "project_id": 7, "approved_cost": "2", "confirm_cost": True}
    async with Client(create_server(config, transport="stdio")) as client:

        async def approved_launch():
            ticket = (await client.call_tool("topvisor_semantics_launch", args)).data
            operator_accepts(ticket)
            return await client.call_tool(
                "topvisor_semantics_launch", {**args, "approval_id": ticket["approval_id"]}
            )

        first = (await approved_launch()).data
        assert first["submitted"] and len(first["task_id"]) == 32
        with pytest.raises(ToolError, match="provider_disabled"):  # daily budget exhausted
            await approved_launch()
    assert sent.count("edit/keywords_2/volumes/go") == 1


def _paid_config(tmp_path: Path, **overrides):
    from dataclasses import replace

    return replace(
        settings(tmp_path),
        write_enabled=True,
        check_projects=frozenset({7, 8}),
        check_max_cost="5",
        check_daily_budget="100",
        **overrides,
    )


def _fake_provider(monkeypatch, sent: list, fail: set | None = None):
    from zai_topvisor import semantics
    from zai_topvisor.transport import ProviderTimeoutError

    async def fake_request(runtime, endpoint, payload, *, read=True):
        sent.append(endpoint)
        if fail and endpoint in fail:
            fail.discard(endpoint)
            raise ProviderTimeoutError("reply lost after dispatch")
        if endpoint.endswith("/price"):
            return {"result": "2"}
        return {"result": {"id": 9}}

    monkeypatch.setattr(semantics, "request", fake_request)
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "all")


INDEXING = {
    "kind": "indexing",
    "project_id": 7,
    "approved_cost": "2",
    "confirm_cost": True,
    "urls": ["site.ru/a"],
}


async def _approved(client, tool: str, args: dict) -> dict:
    ticket = (await client.call_tool(tool, args)).data
    operator_accepts(ticket)
    return {**args, "approval_id": ticket["approval_id"]}


def test_approval_is_bound_to_account_user_actor_and_request(tmp_path: Path) -> None:
    from zai_topvisor.approvals import ApprovalStore

    db = tmp_path / "state.sqlite"
    store = ApprovalStore(db, "acct-a", "1")
    ticket = store.prepare("tool", {"x": 1}, "s", actor="alice")
    store.accept(ticket["approval_id"], ticket["digest"])
    for other, actor, request in (
        (ApprovalStore(db, "acct-b", "1"), "alice", {"x": 1}),  # another account, same database
        (ApprovalStore(db, "acct-a", "2"), "alice", {"x": 1}),  # another Topvisor user
        (store, "mallory", {"x": 1}),
        (store, "alice", {"x": 2}),
    ):
        with pytest.raises(PermissionError):
            other.consume(ticket["approval_id"], "tool", request, actor=actor)
    store.consume(ticket["approval_id"], "tool", {"x": 1}, actor="alice")
    assert store.consumed_for(ticket["approval_id"], "tool", {"x": 1}, "alice")
    with pytest.raises(PermissionError):  # single use
        store.consume(ticket["approval_id"], "tool", {"x": 1}, actor="alice")


async def test_approval_cannot_cross_accounts_sharing_a_directory(tmp_path: Path, monkeypatch) -> None:
    """Regression: account A's indexing approval authorised spending on account B (shared JSON file)."""
    sent: list = []
    _fake_provider(monkeypatch, sent)
    account_a = _paid_config(tmp_path, state_path=tmp_path / "a.sqlite", account_id="A")
    account_b = _paid_config(tmp_path, state_path=tmp_path / "b.sqlite", account_id="B")
    async with Client(create_server(account_a, transport="stdio")) as client:
        approved = await _approved(client, "topvisor_semantics_launch", INDEXING)
    async with Client(create_server(account_b, transport="stdio")) as client:
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_semantics_launch", approved)
    assert "add/projects_2/tasks/indexing" not in sent


async def test_relevance_and_indexing_approvals_are_bound_to_the_project(tmp_path: Path, monkeypatch) -> None:
    """Regression: relevants/indexing payloads carry no project_id, so the digest ignored the project."""
    sent: list = []
    _fake_provider(monkeypatch, sent)
    async with Client(create_server(_paid_config(tmp_path), transport="stdio")) as client:
        approved = await _approved(client, "topvisor_semantics_launch", INDEXING)
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_semantics_launch", {**approved, "project_id": 8})
    assert "add/projects_2/tasks/indexing" not in sent


def test_operator_command_targets_the_server_state_database(tmp_path: Path, monkeypatch) -> None:
    """Regression: operator_command had no --path, so a --config server's approval was not found."""
    from types import SimpleNamespace

    from zai_topvisor.approvals import ApprovalStore, main
    from zai_topvisor.semantics import approval_ticket

    state = tmp_path / "with space" / "state.sqlite"
    runtime = SimpleNamespace(
        config=SimpleNamespace(state_path=state, account_id="default", user_id="1"),
        state=SimpleNamespace(get=lambda: SimpleNamespace(actor="local-operator")),
    )
    ticket = approval_ticket(runtime, "tool", {"x": 1}, "s")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("TOPVISOR_STATE_PATH", raising=False)
    operator_accepts(ticket)
    ApprovalStore(state, "default", "1").consume(ticket["approval_id"], "tool", {"x": 1}, "local-operator")
    # The CLI also resolves the state path from the server's --config, relative to that file.
    monkeypatch.setenv("TOPVISOR_STATE_PATH", "unused")
    config = tmp_path / "with space" / "mcp.local.json"
    config.write_text('{"env": {"TOPVISOR_STATE_PATH": "state.sqlite"}}', encoding="utf-8")
    second = approval_ticket(runtime, "tool", {"x": 2}, "s")
    args = ["--config", str(config), "--approval-id", second["approval_id"], "--digest", second["digest"]]
    assert main([*args, "--accept"]) == 0
    with pytest.raises(SystemExit):  # never silently creates an empty store elsewhere
        main(["--path", str(tmp_path / "missing.sqlite"), "--list"])


def test_approval_consumption_is_a_durable_sqlite_commit(tmp_path: Path) -> None:
    """Regression: the JSON approval file was replaced without fsync, so a crash could revive it."""
    import sqlite3

    from zai_topvisor.approvals import ApprovalStore

    state = tmp_path / "state.sqlite"
    store = ApprovalStore(state, "default", "1")
    ticket = store.prepare("tool", {"x": 1}, "s", actor="me")
    store.accept(ticket["approval_id"], ticket["digest"])
    store.consume(ticket["approval_id"], "tool", {"x": 1}, actor="me")
    db = store.connect()
    assert db.execute("PRAGMA synchronous").fetchone()[0] >= 2  # FULL
    assert db.execute("PRAGMA journal_mode").fetchone()[0] in {"delete", "truncate", "persist", "wal"}
    row = sqlite3.connect(state).execute("SELECT consumed FROM approvals").fetchone()
    assert row[0] is not None and not list(tmp_path.glob("*.json"))


async def test_semantics_launch_replays_receipt_and_fences_unknown_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: after a lost reply a fresh approved copy dispatched the paid task again."""
    import sqlite3

    from zai_topvisor.check_store import CheckStore
    from zai_topvisor.policy import PolicyStore

    go = "add/projects_2/tasks/indexing"
    sent: list = []
    _fake_provider(monkeypatch, sent, fail={go})
    config = _paid_config(tmp_path)
    async with Client(create_server(config, transport="stdio")) as client:
        lost = await _approved(client, "topvisor_semantics_launch", INDEXING)
        with pytest.raises(ToolError):
            await client.call_tool("topvisor_semantics_launch", lost)
        with pytest.raises(ToolError):  # same approval: outcome unknown, never re-dispatched
            await client.call_tool("topvisor_semantics_launch", lost)
        fresh = await _approved(client, "topvisor_semantics_launch", INDEXING)
        with pytest.raises(ToolError):  # a new approval is fenced too
            await client.call_tool("topvisor_semantics_launch", fresh)
        assert sent.count(go) == 1
        # Operator verifies in Topvisor and reconciles (after the two-minute window).
        with sqlite3.connect(config.state_path) as db:
            db.execute("UPDATE paid_tasks SET dispatched=dispatched-300")
        CheckStore(PolicyStore(config.state_path, config.account_id, 20, 20)).reconcile(
            lost["approval_id"], "not_dispatched"
        )
        done = (await client.call_tool("topvisor_semantics_launch", fresh)).data
        assert done["submitted"] and done["task_id"] == fresh["approval_id"] and not done["replayed"]
        replay = (await client.call_tool("topvisor_semantics_launch", fresh)).data
        assert replay["replayed"] and replay["task_id"] == done["task_id"]
    assert sent.count(go) == 2


async def test_competitor_write_is_not_repeated_after_lost_reply(tmp_path: Path, monkeypatch) -> None:
    """Regression: competitor writes had no durable operation record; a fresh approval re-sent them."""
    from dataclasses import replace

    endpoint = "add/projects_2/competitors"
    sent: list = []
    _fake_provider(monkeypatch, sent, fail={endpoint})
    args = {"action": "add", "project_id": 7, "url": "x.ru"}
    async with Client(create_server(replace(settings(tmp_path), write_enabled=True), transport="stdio")) as c:
        with pytest.raises(ToolError):
            await c.call_tool(
                "topvisor_competitors_write", await _approved(c, "topvisor_competitors_write", args)
            )
        with pytest.raises(ToolError):  # pending: unknown outcome is never resubmitted
            await c.call_tool(
                "topvisor_competitors_write", await _approved(c, "topvisor_competitors_write", args)
            )
        assert sent.count(endpoint) == 1
        other = {**args, "url": "y.ru"}
        first = (
            await c.call_tool(
                "topvisor_competitors_write", await _approved(c, "topvisor_competitors_write", other)
            )
        ).data
        again = (
            await c.call_tool(
                "topvisor_competitors_write", await _approved(c, "topvisor_competitors_write", other)
            )
        ).data
        assert first["applied"] and first["readback"] == {"id": 9} and again == first
    assert sent.count(endpoint) == 2
