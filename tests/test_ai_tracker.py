import pytest
from fastmcp import Client
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from test_adapter import RecordingHttp
from test_server import Recorder, config

from zai_topvisor.adapter import TopvisorAdapter
from zai_topvisor.server import create_server


async def test_history_serp_feature_filter_is_validated_and_forwarded():
    http = RecordingHttp({"result": {"keywords": []}})
    adapter = TopvisorAdapter("123", "fixture", http=http)
    await adapter.positions_history(7, [1], ["2026-10-08"], serp_features=["aiOverviewExists", "video"])
    body = http.calls[0][3]
    assert body["filter_by_serp_features"] == ["aiOverviewExists", "video"]
    assert body["positions_fields"] == ["position", "relevant_url"]


@pytest.mark.parametrize("features", [["ai_overview"], "aiOverviewExists", [1]])
async def test_unknown_serp_feature_never_reaches_provider(features):
    http = RecordingHttp()
    with pytest.raises(ValueError):
        await TopvisorAdapter("123", "fixture", http=http).positions_history(
            7, [1], ["2026-10-08"], serp_features=features
        )
    assert not http.calls


async def test_ai_tracker_reads_use_fixed_read_endpoints():
    http = RecordingHttp({"result": {}})
    adapter = TopvisorAdapter("123", "fixture", http=http)
    await adapter.ai_tracker_settings(7, show_available_models=True)
    await adapter.ai_tracker_summary(7, "gpt", ["2026-10-01", "2026-10-08"], competitor_id=9)
    await adapter.ai_tracker_history(7, ["gpt", "alice"], ["2026-10-08"], sentiments=["bad"], limit=10)
    urls = [call[1] for call in http.calls]
    assert [url.rsplit("/json/", 1)[1] for url in urls] == [
        "get/aiTracker_2/settings",
        "get/aiTracker_2/summary",
        "get/aiTracker_2/history",
    ]
    assert http.calls[0][3] == {"project_id": 7, "showAvailableModels": True}
    assert http.calls[1][3] == {
        "project_id": 7,
        "model_key": "gpt",
        "dates": ["2026-10-01", "2026-10-08"],
        "type_range": 100,
        "show_count_mentioned": True,
        "show_visibility": True,
        "show_sentiments": True,
        "competitor_id": 9,
    }
    assert http.calls[2][3] == {
        "project_id": 7,
        "models_keys": ["gpt", "alice"],
        "dates": ["2026-10-08"],
        "type_range": 100,
        "history_fields": ["mentioned", "position", "sentiment"],
        "filter_by_sentiment": ["bad"],
        "limit": 10,
        "offset": 0,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"models_keys": [], "dates": ["2026-10-08"]},
        {"models_keys": ["gpt"] * 11, "dates": ["2026-10-08"]},
        {"models_keys": ["../x"], "dates": ["2026-10-08"]},
        {"models_keys": ["gpt"], "dates": ["2026-13-01"]},
        {"models_keys": ["gpt"], "dates": ["2026-10-08"], "history_fields": ["cost"]},
        {"models_keys": ["gpt"], "dates": ["2026-10-08"], "sentiments": ["angry"]},
    ],
)
async def test_invalid_ai_history_never_reaches_provider(kwargs):
    http = RecordingHttp()
    with pytest.raises(ValueError):
        await TopvisorAdapter("123", "fixture", http=http).ai_tracker_history(7, **kwargs)
    assert not http.calls


def test_paid_and_destructive_ai_tracker_methods_are_not_allowed():
    for method in (("checker", "go"), ("history",)):
        action = "edit" if method[0] == "checker" else "del"
        with pytest.raises(ValueError):
            TopvisorAdapter.validate_operation(action, "aiTracker_2", *method)


async def test_ai_tracker_tools_are_read_only_and_executable(tmp_path):
    recorder = Recorder()
    server = create_server(
        config(tmp_path, RSAKeyPair.generate()), transport="stdio", http_factory=recorder.factory
    )
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        for name in (
            "topvisor_ai_tracker_settings",
            "topvisor_ai_tracker_summary",
            "topvisor_ai_tracker_history",
        ):
            assert tools[name].annotations.readOnlyHint is True
            assert tools[name].annotations.destructiveHint is False
        assert tools["topvisor_check_launch"].annotations.destructiveHint is True
        result = await client.call_tool(
            "topvisor_ai_tracker_summary", {"project_id": 7, "model_key": "gpt", "dates": ["2026-10-08"]}
        )
    assert "payload" in result.data
    assert len(recorder.calls) == 1
