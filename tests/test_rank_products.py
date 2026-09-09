from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from zai_topvisor.check_store import CheckStore
from zai_topvisor.config import ServiceConfig
from zai_topvisor.policy import PolicyStore
from zai_topvisor.rank_checks import units
from zai_topvisor.server import AdmittedHttpClient, create_server
from zai_topvisor.transport import ProviderError, ProviderTransportError

SECRET = "synthetic-product-token"
BEFORE, AFTER = "2026-09-01", "2026-09-02"


class Provider:
    def __init__(self):
        self.calls = []
        self.cost = "0.12"
        self.fail_launch = False
        self.history = {
            "result": {
                "keywords": [
                    {
                        "id": 1,
                        "name": "=SUM(1,2) " + SECRET,
                        "positionsData": {
                            BEFORE + ":7:0": {"position": 12, "relevant_url": "https://example.com/old"},
                            AFTER + ":7:0": {"position": 3, "relevant_url": "https://example.com/new"},
                        },
                    },
                    {
                        "id": 2,
                        "name": "Запрос",
                        "positionsData": {
                            BEFORE + ":7:0": {"position": "--"},
                            AFTER + ":7:0": {"position": 0},
                        },
                    },
                ]
            }
        }

    def factory(self, store, execution, actor):
        owner = self

        class Http(AdmittedHttpClient):
            async def request(self, method, url, *, payload=None, idempotent=False, **kwargs):
                await self._admit_attempt(1)
                owner.calls.append((url, payload, idempotent))
                if url.endswith("/history"):
                    return owner.history
                if url.endswith("/price"):
                    return {"result": {"pricesByUsers": {"1": {"projectsIds": [7], "price": owner.cost}}}}
                if url.endswith("/go"):
                    assert idempotent is False
                    if owner.fail_launch:
                        raise ProviderTransportError("unknown delivery")
                    return {"result": {"projectsIds": [7]}}
                assert url.endswith("/get/projects_2/projects")
                return {"result": [{"id": 7, "status_positions_percent": 100}]}

        return Http(store, execution, actor)


@pytest.fixture
def config(tmp_path):
    return ServiceConfig(
        "1",
        SECRET,
        tmp_path / "state.sqlite",
        write_enabled=True,
        check_projects=frozenset({7}),
        check_max_cost="1",
        check_daily_budget="1",
    )


async def test_rank_report_missing_zero_urls_csv_and_no_paid_call(config):
    provider = Provider()
    async with Client(create_server(config, transport="stdio", http_factory=provider.factory)) as client:
        args = dict(project_id=7, region_index=0, before_date=BEFORE, after_date=AFTER)
        result = (await client.call_tool("topvisor_rank_changes", args)).data
        assert result["rows"][0]["delta"] == 9 and result["rows"][0]["url_changed"] is True
        assert result["rows"][1]["before"] is None and result["rows"][1]["before_status"] == "not_in_depth"
        assert result["rows"][1]["after"] is None and result["rows"][1]["after_status"] == "invalid"
        assert result["rows"][1]["delta"] is None
        assert result["by_url"][0]["url"] == "https://example.com/new"
        assert result["source"]["provider_completeness"] == "not_asserted"
        result = (await client.call_tool("topvisor_rank_changes", {**args, "format": "csv"})).data
        assert "'=SUM" in result["csv"] and "Запрос" in result["csv"]
        assert SECRET not in json.dumps(result) and "***redacted***" in result["csv"]
    assert len(provider.calls) == 2 and all(url.endswith("/history") for url, _, _ in provider.calls)


@pytest.mark.parametrize(
    "changes",
    [
        dict(region_index=-1),
        dict(before_date=AFTER),
        dict(after_date="2026-02-30"),
        dict(limit=251),
        dict(format="html"),
    ],
)
async def test_bad_report_never_calls_provider(config, changes):
    provider = Provider()
    async with Client(create_server(config, transport="stdio", http_factory=provider.factory)) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_rank_changes",
                {**dict(project_id=7, region_index=0, before_date=BEFORE, after_date=AFTER), **changes},
            )
    assert not provider.calls


async def test_report_duplicate_keywords_rejected(config):
    provider = Provider()
    provider.history["result"]["keywords"][1]["id"] = 1
    async with Client(create_server(config, transport="stdio", http_factory=provider.factory)) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_rank_changes",
                dict(project_id=7, region_index=0, before_date=BEFORE, after_date=AFTER),
            )


async def quote(client):
    return (await client.call_tool("topvisor_check_quote", {"project_id": 7, "region_indexes": [0]})).data


async def launch(client, record, **changes):
    return (
        await client.call_tool(
            "topvisor_check_launch",
            dict(
                check_id=record["check_id"],
                approved_cost=changes.pop("approved_cost", record["estimated_cost"]),
                confirm_cost=True,
                **changes,
            ),
        )
    ).data


async def test_quote_launch_receipt_replay_reconciliation_and_budget(config):
    provider = Provider()
    server = create_server(config, transport="stdio", http_factory=provider.factory)
    async with Client(server) as client:
        record = await quote(client)
        assert record["paid_dispatch"] is False and record["estimated_cost"] == "0.12"
        assert len(provider.calls) == 1
        result = await launch(client, record)
        assert result["submitted"] and not result["completed"]
        assert (await launch(client, record))["replayed"]
        status = (await client.call_tool("topvisor_check_status", {"check_id": record["check_id"]})).data
        assert status["state"] == "accepted" and status["completion_of_this_check"] == "not_asserted"
        newer = await quote(client)
        with pytest.raises(ToolError):
            await launch(client, newer)
    assert len([u for u, _, _ in provider.calls if u.endswith("/go")]) == 1
    store = CheckStore(PolicyStore(config.state_path, config.account_id, 20, 20))
    store.reconcile(record["check_id"], "completed")
    async with Client(create_server(config, transport="stdio", http_factory=provider.factory)) as client:
        assert (await launch(client, newer))["submitted"]


async def test_unknown_launch_survives_restart_other_actor_and_new_quote(config):
    provider = Provider()
    provider.fail_launch = True
    async with Client(create_server(config, transport="stdio", http_factory=provider.factory)) as client:
        record = await quote(client)
        with pytest.raises(ToolError):
            await launch(client, record)
    provider.fail_launch = False
    for settings in [config, replace(config, principal_id="bob")]:
        async with Client(
            create_server(settings, transport="stdio", http_factory=provider.factory)
        ) as client:
            with pytest.raises(ToolError):
                await launch(client, record)
            newer = await quote(client)
            with pytest.raises(ToolError):
                await launch(client, newer)
    assert len([u for u, _, _ in provider.calls if u.endswith("/go")]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        dict(write_enabled=False),
        dict(check_max_cost="0"),
        dict(check_projects=frozenset()),
        dict(check_max_cost="0.1"),
    ],
)
async def test_operator_limits_prevent_dispatch(config, changes):
    provider = Provider()
    async with Client(
        create_server(replace(config, **changes), transport="stdio", http_factory=provider.factory)
    ) as client:
        record = await quote(client)
        with pytest.raises(ToolError):
            await launch(client, record)
    assert len(provider.calls) == 1


async def test_explicit_approval_cost_change_and_expiry(config):
    provider = Provider()
    async with Client(create_server(config, transport="stdio", http_factory=provider.factory)) as client:
        record = await quote(client)
        with pytest.raises(ToolError):
            await client.call_tool(
                "topvisor_check_launch", dict(check_id=record["check_id"], approved_cost="0.12")
            )
        with pytest.raises(ToolError):
            await launch(client, record, approved_cost="0.13")
        provider.cost = "0.13"
        with pytest.raises(ToolError):
            await launch(client, record)
        with PolicyStore(config.state_path, config.account_id, 20, 20).connect() as db:
            db.execute("UPDATE rank_checks SET expires=0")
        with pytest.raises(ToolError):
            await launch(client, record)
    assert not any(u.endswith("/go") for u, _, _ in provider.calls)


@pytest.mark.parametrize("value", [True, None, "nan", "inf", "-0.1", "0.0000001", "1000001", "x"])
def test_invalid_estimate_units(value):
    with pytest.raises(ValueError):
        units(value)


async def test_project_fence_is_atomic_and_daily_budget_shared(config):
    store = CheckStore(PolicyStore(config.state_path, config.account_id, 20, 20))
    a = store.create("alice", 7, {}, 120000)
    b = store.create("bob", 7, {}, 120000)
    results = await asyncio.gather(
        *(
            asyncio.to_thread(store.claim, actor, record["check_id"], 1000000)
            for actor, record in [("alice", a), ("bob", b)]
        ),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    c = store.create("bob", 8, {}, 120000)
    with pytest.raises(PermissionError):
        store.claim("bob", c["check_id"], 200000)
    with pytest.raises((PermissionError, ProviderError)):
        store.get("bob", a["check_id"])


def test_reconcile_cannot_unlock_inflight_request_and_refunds_only_known_nondispatch(config, monkeypatch):
    store = CheckStore(PolicyStore(config.state_path, config.account_id, 20, 20))
    from zai_topvisor import check_store

    monkeypatch.setattr(check_store.time, "time", lambda: 1000000)
    record = store.create("alice", 7, {}, 120000)
    store.claim("alice", record["check_id"], 120000)
    with pytest.raises(ValueError, match="two minutes"):
        store.reconcile(record["check_id"], "not_dispatched")
    monkeypatch.setattr(check_store.time, "time", lambda: 1000121)
    store.reconcile(record["check_id"], "not_dispatched")
    new = store.create("bob", 7, {}, 120000)
    store.claim("bob", new["check_id"], 120000)
