from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from zai_topvisor.adapter import TopvisorAdapter
from zai_topvisor.agent_layer import DESCRIPTION_LIMIT, INSTRUCTIONS_LIMIT, selected_tools
from zai_topvisor.agent_profile import PROFILE
from zai_topvisor.config import ServiceConfig
from zai_topvisor.server import create_server
from zai_topvisor.tools import positions_matrix

ROOT = Path(__file__).resolve().parents[1]
TOOLS_LIST_BUDGET = 40_000  # bytes of tools/list JSON for the full default toolset


def settings(tmp_path: Path) -> ServiceConfig:
    return ServiceConfig(
        user_id="1",
        api_key="synthetic-key",
        state_path=tmp_path / "state.sqlite",
        public_key=RSAKeyPair.generate().public_key,
    )


async def test_token_budget_and_agent_surface(tmp_path: Path) -> None:
    async with Client(create_server(settings(tmp_path), transport="stdio")) as client:
        instructions = client.initialize_result.instructions or ""
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert len(instructions) <= INSTRUCTIONS_LIMIT
        assert names == {name for group in PROFILE.toolsets.values() for name in group}
        for tool in tools:
            assert tool.description and len(tool.description) <= DESCRIPTION_LIMIT, tool.name
            assert tool.title and tool.annotations is not None
        history = next(tool for tool in tools if tool.name == "topvisor_positions_history")
        assert history.inputSchema["properties"]["format"]["enum"] == ["raw", "matrix"]
        size = len(json.dumps([tool.model_dump(exclude_none=True) for tool in tools]))
        assert size <= TOOLS_LIST_BUDGET
        uris = {str(item.uri) for item in await client.list_resources()}
        assert {"topvisor://playbook", "topvisor://toolsets", "topvisor://guide/pricing"} <= uris
        guide = await client.read_resource("topvisor://guide/errors")
        assert "Topvisor errors" in guide[0].text
        prompts = {prompt.name for prompt in await client.list_prompts()}
        assert prompts == {"weekly_report", "check_positions"}
        rendered = await client.get_prompt("check_positions", {"project": "42"})
        assert "42" in rendered.messages[0].content.text


async def test_read_only_mode_removes_every_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TOPVISOR_READ_ONLY", "1")
    monkeypatch.setenv("TOPVISOR_TOOLSETS", "positions,checks")
    async with Client(create_server(settings(tmp_path), transport="stdio")) as client:
        tools = await client.list_tools()
    assert all(tool.annotations.readOnlyHint for tool in tools)
    names = {tool.name for tool in tools}
    assert "topvisor_check_launch" not in names and "topvisor_check_quote" in names
    assert "topvisor_ai_tracker_summary" not in names and "topvisor_balance" in names


def test_unknown_toolset_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown TOPVISOR_TOOLSETS"):
        selected_tools(PROFILE, {"a"}, set(), {"TOPVISOR_TOOLSETS": "nope"})


def test_static_budget_script_passes() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import token_budget

    assert token_budget.problems() == []


def test_positions_matrix_is_compact() -> None:
    payload = {
        "result": {
            "keywords": [
                {"id": 1, "name": "a", "positionsData": {"2026-10-01:7:0": {"position": 4}}},
                {"id": 2, "name": "b", "positionsData": {"2026-10-01:7:0": {"position": "--"}}},
                {"id": 3, "name": "c", "positionsData": {"2026-10-01:7:0": {"position": "12"}}},
            ]
        }
    }
    matrix = positions_matrix(payload, 7, [0], ["2026-10-01", "2026-10-08"])
    assert matrix["columns"] == ["keyword_id", "keyword", "region_index", "2026-10-01", "2026-10-08"]
    # Decimal strings rank like rank_changes; "--" (checked, not in depth) differs from no data.
    assert matrix["rows"] == [[1, "a", 0, 4, None], [2, "b", 0, "--", None], [3, "c", 0, 12, None]]
    assert matrix["next_offset"] is None and matrix["returned_keywords"] == 3


def test_positions_matrix_keeps_paging() -> None:
    # A 300-keyword project read 100 at a time must not look complete after the first page.
    keywords = [{"id": i, "name": f"k{i}", "positionsData": {}} for i in range(1, 101)]
    payload = {"result": {"keywords": keywords}, "nextOffset": 100}
    matrix = positions_matrix(payload, 7, [0], ["2026-10-01"], limit=100, offset=0)
    assert len(matrix["rows"]) == 100
    assert (matrix["limit"], matrix["offset"], matrix["next_offset"]) == (100, 0, 100)
    # Without provider nextOffset a full page still points at the next one.
    payload = {"result": {"keywords": keywords}}
    assert positions_matrix(payload, 7, [0], ["2026-10-01"], limit=100, offset=200)["next_offset"] == 300
    last = {"result": {"keywords": keywords[:40]}}
    assert positions_matrix(last, 7, [0], ["2026-10-01"], limit=100, offset=200)["next_offset"] is None


def test_balance_payload_is_validated() -> None:
    assert TopvisorAdapter.validate_payload(("get", "bank_2", "info"), {})["fields"]
    with pytest.raises(ValueError):
        TopvisorAdapter.validate_payload(("get", "bank_2", "info"), {"user": 1})
