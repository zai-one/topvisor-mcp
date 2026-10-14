from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from test_agent_layer import settings

from zai_topvisor.semantics import ENDPOINTS, paid_payload, price_units, report_payload
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
    assert all(e.startswith(("get/", "edit/")) and "/del" not in e for e in ENDPOINTS)


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
