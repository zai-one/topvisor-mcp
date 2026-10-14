from __future__ import annotations

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
    assert competitor_payload("add", 7, urls=["https://x.ru"]) == {"project_id": 7, "urls": ["x.ru"]}
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
    from zai_topvisor.approvals import ApprovalStore

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
        ApprovalStore(tmp_path / "topvisor-approvals.json").accept(ticket["approval_id"], ticket["digest"])
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
            ("del/projects_2/competitors", {"project_id": 7, "ids": [5]}, False)
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
    from zai_topvisor.approvals import ApprovalStore

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
        ApprovalStore(tmp_path / "topvisor-approvals.json").accept(ticket["approval_id"], ticket["digest"])
        done = (
            await client.call_tool(
                "topvisor_semantics_launch", {**args, "approval_id": ticket["approval_id"]}
            )
        ).data
    assert done["submitted"] and sent[-1] == "add/projects_2/tasks/relevants"
