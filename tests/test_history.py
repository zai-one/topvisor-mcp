import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_adapter import RecordingHttp
from test_server import Recorder, config

from zai_topvisor.adapter import TopvisorAdapter
from zai_topvisor.server import create_server


async def test_explicit_history_uses_read_endpoint_and_project_region_index():
    http = RecordingHttp({"result": {"keywords": [{"id": 1, "positionsData": {}}]}})
    adapter = TopvisorAdapter("123", "fixture", http=http)
    await adapter.positions_history(7, [0, 2], ["2026-09-01", "2026-09-02"], limit=25, offset=50)
    method, url, _, body, _ = http.calls[0]
    assert method == "POST" and url.endswith("/get/positions_2/history")
    assert body == {
        "project_id": 7,
        "regions_indexes": [0, 2],
        "dates": ["2026-09-01", "2026-09-02"],
        "type_range": 100,
        "positions_fields": ["position", "relevant_url"],
        "limit": 25,
        "offset": 50,
    }


@pytest.mark.parametrize(
    "regions,dates",
    [
        ([], ["2026-09-01"]),
        ([True], ["2026-09-01"]),
        ([1], []),
        ([1], ["2026-02-30"]),
        ([1], ["20260901"]),
        ([1] * 11, ["2026-09-01"]),
    ],
)
async def test_invalid_history_never_reaches_provider(regions, dates):
    http = RecordingHttp()
    with pytest.raises(ValueError):
        await TopvisorAdapter("123", "fixture", http=http).positions_history(7, regions, dates)
    assert not http.calls


async def test_history_is_executable_through_mcp_and_preserves_safe_envelope(tmp_path):
    pair = RSAKeyPair.generate()
    recorder = Recorder()
    server = create_server(config(tmp_path, pair), transport="stdio", http_factory=recorder.factory)
    async with Client(server) as client:
        result = await client.call_tool(
            "topvisor_positions_history", {"project_id": 7, "region_indexes": [2], "dates": ["2026-09-01"]}
        )
    assert "payload" in result.data
    assert len(recorder.calls) == 1
