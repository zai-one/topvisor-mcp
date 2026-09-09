from __future__ import annotations

from typing import Any

import pytest

from zai_topvisor.adapter import (
    ADD_FOLDER_OPERATION,
    ADD_GROUP_OPERATION,
    ADD_KEYWORD_OPERATION,
    ADD_PROJECT_OPERATION,
    ADD_REGION_OPERATION,
    ADD_SEARCHER_OPERATION,
    ALLOWED_OPERATIONS,
    FOLDERS_OPERATION,
    GROUPS_OPERATION,
    IMPORT_KEYWORDS_OPERATION,
    IMPORT_REGIONS_OPERATION,
    MAX_KEYWORD_LEN,
    PROJECTS_OPERATION,
    REGIONS_OPERATION,
    RENAME_GROUP_OPERATION,
    SET_KEYWORD_TAGS_OPERATION,
    SET_KEYWORD_TARGET_OPERATION,
    TOGGLE_GROUP_OPERATION,
    WRITE_ALLOWLIST,
    TopvisorAdapter,
)
from zai_topvisor.transport import ProviderError


class RecordingHttp:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, str], dict[str, Any] | None, dict[str, Any] | None]] = []
        self.response = response or {"result": [], "total": 0}

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        assert idempotent is True
        self.calls.append((method, url, headers or {}, payload, params))
        return self.response


@pytest.mark.asyncio
async def test_projects_uses_official_read_path_server_credentials_and_status_fields() -> None:
    http = RecordingHttp()
    adapter = TopvisorAdapter(" 504903 ", " secret ", http=http)

    result = await adapter.projects(limit=25, include_positions_summary=True)

    assert result == {"result": [], "total": 0}
    assert len(http.calls) == 1
    request = http.calls[0]
    assert request[0:2] == ("POST", "https://api.topvisor.com/v2/json/get/projects_2/projects")
    assert request[2] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Id": "504903",
        "Authorization": "bearer secret",
        "User-Agent": "ZAI-MCP-Platform/0.2.0 Topvisor",
    }
    assert request[3] == {
        "limit": 25,
        "offset": 0,
        "fields": [
            "id",
            "name",
            "url",
            "on",
            "status_positions",
            "positions_time",
            "positions_percent",
            "status_volumes",
            "status_claster",
        ],
        "include_positions_summary": True,
    }
    assert request[4] is None


@pytest.mark.asyncio
async def test_keywords_is_bounded_to_one_project_and_metadata_fields() -> None:
    http = RecordingHttp()
    adapter = TopvisorAdapter("504903", "secret", http=http)

    await adapter.keywords("42", limit=500, fields=["id", "name", "group_name", "target"])

    assert http.calls[0][1] == "https://api.topvisor.com/v2/json/get/keywords_2/keywords"
    assert http.calls[0][3] == {
        "project_id": 42,
        "limit": 500,
        "offset": 0,
        "fields": ["id", "name", "group_name", "target"],
        "show_trash": False,
    }


@pytest.mark.asyncio
async def test_operation_allowlist_rejects_writes_paid_checks_and_path_escape_before_network() -> None:
    http = RecordingHttp()
    adapter = TopvisorAdapter("504903", "secret", http=http)

    attempts = (
        ("edit", "keywords_2", "checker/go"),
        ("add", "projects_2", "projects"),
        ("get", "bank_2", "info"),
        ("get", "projects_2/../bank_2", "info"),
    )
    for action, service, method in attempts:
        with pytest.raises(ValueError, match="invalid path segment|operation is not allowed"):
            await adapter.read(action, service, method, {})

    assert {
        PROJECTS_OPERATION,
        ("get", "keywords_2", "keywords"),
        FOLDERS_OPERATION,
        GROUPS_OPERATION,
        REGIONS_OPERATION,
        ("get", "positions_2", "history"),
    } == ALLOWED_OPERATIONS
    assert http.calls == []


@pytest.mark.asyncio
async def test_project_structure_and_region_catalog_use_confirmed_paths() -> None:
    http = RecordingHttp()
    adapter = TopvisorAdapter("504903", "secret", http=http)

    await adapter.folders(42, limit=10)
    await adapter.groups(42, limit=10)
    await adapter.search_regions("yandex", "Москва", country_code="ru")

    assert [call[1] for call in http.calls] == [
        "https://api.topvisor.com/v2/json/get/keywords_2/folders",
        "https://api.topvisor.com/v2/json/get/keywords_2/groups",
        "https://api.topvisor.com/v2/json/get/system_2/common/regions",
    ]
    assert http.calls[2][3] == {
        "searcher_key": 0,
        "search": "Москва",
        "only_countries": False,
        "limit": 50,
        "offset": 0,
        "country_code": "RU",
    }


@pytest.mark.asyncio
async def test_payload_rejects_unknown_filters_unbounded_values_and_compound_fields() -> None:
    http = RecordingHttp()
    adapter = TopvisorAdapter("504903", "secret", http=http)

    with pytest.raises(ValueError, match="unsupported Topvisor parameters"):
        await adapter.read("get", "projects_2", "projects", {"filters": []})
    with pytest.raises(ValueError, match="between 1 and 500"):
        await adapter.projects(limit=501)
    with pytest.raises(ValueError, match="project_id"):
        await adapter.keywords(0)
    with pytest.raises(ValueError, match="unsupported Topvisor fields item"):
        await adapter.keywords(42, fields=["position:2026-07-18:42:1"])
    with pytest.raises(ValueError, match="must be a boolean"):
        await adapter.read("get", "keywords_2", "keywords", {"project_id": 42, "show_trash": 1})

    assert http.calls == []


@pytest.mark.asyncio
async def test_credentials_and_base_url_fail_closed_without_network() -> None:
    http = RecordingHttp()

    with pytest.raises(ValueError, match="official API v2"):
        TopvisorAdapter("504903", "secret", "http://api.topvisor.com/v2/json", http=http)
    with pytest.raises(ValueError, match="official API v2"):
        TopvisorAdapter("504903", "secret", "https://attacker.invalid/v2/json", http=http)

    with pytest.raises(ValueError, match="positive integer"):
        await TopvisorAdapter("not-an-id", "secret", http=http).projects()
    with pytest.raises(ProviderError, match="not configured"):
        await TopvisorAdapter("504903", "", http=http).projects()

    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"error": {"code": "AUTH_FAILED", "message": "fixture-secret"}},
        {"errors": [{"error_code": 42, "message": "fixture-secret"}]},
        {"success": False, "message": "fixture-secret"},
        {"status": "failed", "detail": "fixture-secret"},
    ],
)
async def test_application_error_envelopes_fail_closed_without_echoing_details(
    response: dict[str, Any],
) -> None:
    http = RecordingHttp(response)
    adapter = TopvisorAdapter("504903", "secret", http=http)

    with pytest.raises(ProviderError, match="application error") as captured:
        await adapter.projects()

    assert "fixture-secret" not in str(captured.value)
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_empty_error_collections_do_not_reject_successful_topvisor_response() -> None:
    response = {"result": [{"id": 1}], "errors": [], "error": None, "success": True}
    adapter = TopvisorAdapter("504903", "secret", http=RecordingHttp(response))

    assert await adapter.projects() == response


class RecordingWriteHttp:
    """Records requests (including the idempotent flag) without touching the network."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[
            tuple[str, str, dict[str, str], dict[str, Any] | None, dict[str, Any] | None, bool]
        ] = []
        self.response = response if response is not None else {"result": {"id": 7}}

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((method, url, headers or {}, payload, params, idempotent))
        return self.response


def test_write_allowlist_is_frozen_to_reversible_operations_with_platform_tiers() -> None:
    assert WRITE_ALLOWLIST == {
        ("add", "keywords_2", "keywords"): "medium",
        ("add", "keywords_2", "groups"): "medium",
        ("edit", "keywords_2", "groups", "rename"): "medium",
        ("edit", "keywords_2", "groups", "on"): "medium",
        ADD_PROJECT_OPERATION: "medium",
        ADD_FOLDER_OPERATION: "medium",
        IMPORT_KEYWORDS_OPERATION: "medium",
        SET_KEYWORD_TARGET_OPERATION: "medium",
        SET_KEYWORD_TAGS_OPERATION: "medium",
        ADD_SEARCHER_OPERATION: "medium",
        ADD_REGION_OPERATION: "medium",
        IMPORT_REGIONS_OPERATION: "medium",
    }
    # Every allowlisted tier is a real platform tier and matches its action class.
    for operation, tier in WRITE_ALLOWLIST.items():
        assert tier in {"low", "medium", "high"}
        assert operation[0] in {"add", "edit"}
        assert 3 <= len(operation) <= 5
        assert tier == "medium"


def test_risk_tier_is_fail_closed_high_for_del_and_unknown_actions() -> None:
    assert TopvisorAdapter.risk_tier(ADD_KEYWORD_OPERATION) == "medium"
    assert TopvisorAdapter.risk_tier(ADD_GROUP_OPERATION) == "medium"
    assert TopvisorAdapter.risk_tier(RENAME_GROUP_OPERATION) == "medium"
    assert TopvisorAdapter.risk_tier(TOGGLE_GROUP_OPERATION) == "medium"
    # del is not executable but must still classify as high-risk.
    assert TopvisorAdapter.risk_tier(("del", "keywords_2", "keywords")) == "high"
    assert TopvisorAdapter.risk_tier(("del", "keywords_2", "groups")) == "high"
    assert TopvisorAdapter.risk_tier(("del", "projects_2", "projects")) == "high"
    # Unknown action defaults to high.
    assert TopvisorAdapter.risk_tier(("frobnicate", "keywords_2", "keywords")) == "high"
    for bad in ("edit/keywords_2/groups", ("edit", "keywords_2"), ("edit", "keywords_2", "GROUPS!")):
        with pytest.raises(ValueError, match="write operation"):
            TopvisorAdapter.risk_tier(bad)


def test_validate_write_is_fail_closed() -> None:
    # Read operations and non-allowlisted writes are rejected before any bounds.
    for operation in (
        ("get", "keywords_2", "keywords"),
        ("del", "keywords_2", "keywords"),
        ("add", "bank_2", "transfer"),
        ("edit", "keywords_2", "groups"),  # generic group edit does not exist
    ):
        with pytest.raises(ValueError, match="not allowed"):
            TopvisorAdapter.validate_write(operation, {"project_id": 1})
    with pytest.raises(ValueError, match="invalid path segment"):
        TopvisorAdapter.validate_write(("add", "keywords_2", "../groups"), {"project_id": 1})

    # add keyword bounds (single phrase via `name`, not an array).
    with pytest.raises(ValueError, match="missing required"):
        TopvisorAdapter.validate_write(ADD_KEYWORD_OPERATION, {"name": "seo"})
    with pytest.raises(ValueError, match="missing required"):
        TopvisorAdapter.validate_write(ADD_KEYWORD_OPERATION, {"project_id": 42})
    with pytest.raises(ValueError, match="unsupported Topvisor write parameters"):
        TopvisorAdapter.validate_write(
            ADD_KEYWORD_OPERATION, {"project_id": 42, "name": "seo", "keywords": ["x"]}
        )
    with pytest.raises(ValueError, match="name must be a string"):
        TopvisorAdapter.validate_write(ADD_KEYWORD_OPERATION, {"project_id": 42, "name": ["seo"]})
    with pytest.raises(ValueError, match="name must be between"):
        TopvisorAdapter.validate_write(ADD_KEYWORD_OPERATION, {"project_id": 42, "name": "  "})
    with pytest.raises(ValueError, match="name must be between"):
        TopvisorAdapter.validate_write(
            ADD_KEYWORD_OPERATION, {"project_id": 42, "name": "k" * (MAX_KEYWORD_LEN + 1)}
        )
    with pytest.raises(ValueError, match="project_id must be between"):
        TopvisorAdapter.validate_write(ADD_KEYWORD_OPERATION, {"project_id": 0, "name": "seo"})
    with pytest.raises(ValueError, match="to_id must be between"):
        TopvisorAdapter.validate_write(ADD_KEYWORD_OPERATION, {"project_id": 42, "name": "seo", "to_id": 0})
    with pytest.raises(ValueError, match="unsupported Topvisor to_type"):
        TopvisorAdapter.validate_write(
            ADD_KEYWORD_OPERATION, {"project_id": 42, "name": "seo", "to_type": "nowhere"}
        )

    # add group bounds.
    with pytest.raises(ValueError, match="missing required"):
        TopvisorAdapter.validate_write(ADD_GROUP_OPERATION, {"project_id": 42})
    with pytest.raises(ValueError, match="name must be a string"):
        TopvisorAdapter.validate_write(ADD_GROUP_OPERATION, {"project_id": 42, "name": 7})
    with pytest.raises(ValueError, match="on must be a boolean"):
        TopvisorAdapter.validate_write(ADD_GROUP_OPERATION, {"project_id": 42, "name": "x", "on": 1})

    # rename group bounds: project_id + id + name are all required.
    with pytest.raises(ValueError, match="missing required"):
        TopvisorAdapter.validate_write(RENAME_GROUP_OPERATION, {"project_id": 42, "name": "x"})
    with pytest.raises(ValueError, match="missing required"):
        TopvisorAdapter.validate_write(RENAME_GROUP_OPERATION, {"project_id": 42, "id": 5})
    with pytest.raises(ValueError, match="id must be between"):
        TopvisorAdapter.validate_write(RENAME_GROUP_OPERATION, {"project_id": 42, "id": 0, "name": "x"})

    # toggle group bounds: project_id + id + on all required, on is a boolean.
    with pytest.raises(ValueError, match="missing required"):
        TopvisorAdapter.validate_write(TOGGLE_GROUP_OPERATION, {"project_id": 42, "id": 5})
    with pytest.raises(ValueError, match="on must be a boolean"):
        TopvisorAdapter.validate_write(TOGGLE_GROUP_OPERATION, {"project_id": 42, "id": 5, "on": "yes"})


def test_validate_write_normalizes_accepted_payloads() -> None:
    op, add_kw = TopvisorAdapter.validate_write(
        ADD_KEYWORD_OPERATION,
        {"project_id": "42", "name": " seo ", "to_id": "9", "to_type": "in_group"},
    )
    assert op == ("add", "keywords_2", "keywords")
    assert add_kw == {"project_id": 42, "name": "seo", "to_id": 9, "to_type": "in_group"}

    _, add_group = TopvisorAdapter.validate_write(
        ADD_GROUP_OPERATION, {"project_id": 42, "name": " Brand ", "on": True}
    )
    assert add_group == {"project_id": 42, "names": ["Brand"], "on": True}

    rename_op, rename = TopvisorAdapter.validate_write(
        RENAME_GROUP_OPERATION, {"project_id": 42, "id": "5", "name": " Renamed "}
    )
    assert rename_op == ("edit", "keywords_2", "groups", "rename")
    assert rename == {"project_id": 42, "id": 5, "name": "Renamed"}

    _, toggle = TopvisorAdapter.validate_write(
        TOGGLE_GROUP_OPERATION, {"project_id": 42, "id": 5, "on": False}
    )
    assert toggle == {"project_id": 42, "id": 5, "on": False}


def test_project_semantic_and_region_writes_are_typed_and_bounded() -> None:
    _, project = TopvisorAdapter.validate_write(
        ADD_PROJECT_OPERATION,
        {"url": " example.com/ ", "name": " Brand ", "tags": [1, "2"], "on": True},
    )
    assert project == {
        "url": "example.com",
        "name": "Brand",
        "tags": [1, 2],
        "on": 1,
    }

    keyword_rows = [
        {
            "query": " Кабель Draka ",
            "target_url": "https://example.com/product",
            "tags": [2],
            "group_folder_path": "Draka/Кабели",
            "group_name": "Силовые",
        }
    ]
    payload, normalized = TopvisorAdapter.prepare_keyword_import(42, keyword_rows)
    assert payload["project_id"] == 42
    assert payload["keywords"].splitlines() == [
        "name;tags;target;group_folder_path;group_name",
        "Кабель Draka;2;https://example.com/product;Draka/Кабели;Силовые",
    ]
    assert normalized[0]["normalized_query"] == "кабель draka"

    _, region = TopvisorAdapter.validate_write(
        ADD_REGION_OPERATION,
        {
            "project_id": 42,
            "searcher_key": "yandex",
            "region_key": "225",
            "region_depth": 3,
            "region_device": "desktop",
        },
    )
    assert region == {
        "project_id": 42,
        "searcher_key": 0,
        "region_key": 225,
        "region_depth": 3,
        "region_device": 0,
    }

    _, google_region = TopvisorAdapter.validate_write(
        ADD_REGION_OPERATION,
        {
            "project_id": 42,
            "searcher_key": "1",
            "region_key": 225,
            "region_depth": 5,
            "region_device": "mobile",
        },
    )
    assert google_region["searcher_key"] == 1
    assert google_region["region_device"] == 2
    assert google_region["region_depth"] == 5

    with pytest.raises(ValueError, match="between 1 and 3"):
        TopvisorAdapter.validate_write(
            ADD_REGION_OPERATION,
            {"project_id": 42, "searcher_key": "yandex", "region_key": 225, "region_depth": 4},
        )
    with pytest.raises(ValueError, match="documented Topvisor searcher"):
        TopvisorAdapter.validate_write(
            ADD_SEARCHER_OPERATION, {"project_id": 42, "searcher_key": "duckduckgo"}
        )

    with pytest.raises(ValueError, match="between 1 and 1000"):
        TopvisorAdapter.prepare_keyword_import(42, [{"query": f"keyword {index}"} for index in range(1001)])
    with pytest.raises(ValueError, match="between 1 and 10"):
        TopvisorAdapter.validate_write(
            SET_KEYWORD_TAGS_OPERATION,
            {"project_id": 42, "id": 7, "tags": [11], "action": "set"},
        )


@pytest.mark.asyncio
async def test_keyword_import_posts_documented_csv_payload_without_retry() -> None:
    http = RecordingWriteHttp({"result": {"countAdded": 1}})
    adapter = TopvisorAdapter("504903", "secret", http=http)

    await adapter.apply_write(
        IMPORT_KEYWORDS_OPERATION,
        {"project_id": 42, "keywords": [{"query": "seo", "group_name": "Brand"}]},
    )

    method, url, _headers, payload, _params, idempotent = http.calls[0]
    assert (method, url) == (
        "POST",
        "https://api.topvisor.com/v2/json/add/keywords_2/keywords/import",
    )
    assert payload is not None
    assert payload["project_id"] == 42
    assert payload["keywords"].splitlines()[0] == ("name;tags;target;group_folder_path;group_name")
    assert idempotent is False


@pytest.mark.asyncio
async def test_add_region_posts_documented_searchers_regions_path_and_numeric_enums() -> None:
    http = RecordingWriteHttp({"result": True})
    adapter = TopvisorAdapter("504903", "secret", http=http)

    await adapter.apply_write(
        ADD_REGION_OPERATION,
        {
            "project_id": 42,
            "searcher_key": "google",
            "region_key": 225,
            "region_device": "desktop",
            "region_depth": 5,
        },
    )

    method, url, _headers, payload, _params, idempotent = http.calls[0]
    assert (method, url) == (
        "POST",
        "https://api.topvisor.com/v2/json/add/positions_2/searchers_regions",
    )
    assert payload == {
        "project_id": 42,
        "searcher_key": 1,
        "region_key": 225,
        "region_device": 0,
        "region_depth": 5,
    }
    assert idempotent is False


@pytest.mark.asyncio
async def test_apply_write_posts_write_path_without_coalescing_or_blind_retry() -> None:
    http = RecordingWriteHttp({"result": {"id": 101}})
    adapter = TopvisorAdapter("504903", "secret", http=http)

    result = await adapter.apply_write(ADD_KEYWORD_OPERATION, {"project_id": 42, "name": "seo", "to_id": 9})

    assert result == {"result": {"id": 101}}
    assert len(http.calls) == 1
    method, url, headers, payload, params, idempotent = http.calls[0]
    assert (method, url) == ("POST", "https://api.topvisor.com/v2/json/add/keywords_2/keywords")
    assert headers["User-Id"] == "504903"
    assert headers["Authorization"] == "bearer secret"
    assert payload == {"project_id": 42, "name": "seo", "to_id": 9}
    assert params is None
    # A production mutation is never retried blindly: POST stays non-idempotent.
    assert idempotent is False


@pytest.mark.asyncio
async def test_apply_write_posts_four_segment_group_edit_path() -> None:
    http = RecordingWriteHttp({"result": True})
    adapter = TopvisorAdapter("504903", "secret", http=http)

    await adapter.apply_write(RENAME_GROUP_OPERATION, {"project_id": 42, "id": 5, "name": "Brand"})

    method, url, _headers, payload, _params, idempotent = http.calls[0]
    assert (method, url) == (
        "POST",
        "https://api.topvisor.com/v2/json/edit/keywords_2/groups/rename",
    )
    assert payload == {"project_id": 42, "id": 5, "name": "Brand"}
    assert idempotent is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"result": None, "errors": [{"code": 53, "string": "fixture-secret"}]},
        {"error": {"code": "WRITE_DENIED", "message": "fixture-secret"}},
        {"success": False, "message": "fixture-secret"},
    ],
)
async def test_apply_write_rejects_application_error_envelope(response: dict[str, Any]) -> None:
    http = RecordingWriteHttp(response)
    adapter = TopvisorAdapter("504903", "secret", http=http)

    with pytest.raises(ProviderError, match="application error") as captured:
        await adapter.apply_write(ADD_GROUP_OPERATION, {"project_id": 42, "name": "Brand"})

    assert "fixture-secret" not in str(captured.value)
    assert len(http.calls) == 1  # the write was attempted exactly once, not retried


@pytest.mark.asyncio
async def test_apply_write_validates_before_any_network_call() -> None:
    http = RecordingWriteHttp()
    adapter = TopvisorAdapter("504903", "secret", http=http)

    with pytest.raises(ValueError, match="not allowed"):
        await adapter.apply_write(("del", "keywords_2", "keywords"), {"project_id": 42})
    with pytest.raises(ValueError, match="missing required"):
        await adapter.apply_write(ADD_KEYWORD_OPERATION, {"project_id": 42})

    assert http.calls == []


@pytest.mark.asyncio
async def test_readback_re_reads_the_affected_project_keywords() -> None:
    http = RecordingWriteHttp({"result": [{"id": 1, "group_id": 9}], "total": 1})
    adapter = TopvisorAdapter("504903", "secret", http=http)

    result = await adapter.readback(ADD_KEYWORD_OPERATION, {"project_id": 42, "name": "seo", "to_id": 9})

    assert result == {"result": [{"id": 1, "group_id": 9}], "total": 1}
    assert len(http.calls) == 1
    method, url, _headers, payload, _params, idempotent = http.calls[0]
    assert (method, url) == ("POST", "https://api.topvisor.com/v2/json/get/keywords_2/keywords")
    assert payload is not None and payload["project_id"] == 42
    assert idempotent is True  # readback is a coalesced idempotent read


@pytest.mark.asyncio
async def test_folder_and_group_reads_never_send_show_trash() -> None:
    # Topvisor answers application error 2002 when keywords_2/folders or
    # keywords_2/groups receive show_trash at all, including show_trash=false.
    http = RecordingHttp()
    adapter = TopvisorAdapter("504903", "secret", http=http)

    await adapter.folders("42", limit=5)
    await adapter.groups("42", limit=5)

    assert "show_trash" not in http.calls[0][3]
    assert "show_trash" not in http.calls[1][3]
    assert "show_trash" not in TopvisorAdapter.validate_folders(42, 5, 0, False, "flat")
    assert "show_trash" not in TopvisorAdapter.validate_groups(42, 5, 0, False)


@pytest.mark.asyncio
async def test_folder_and_group_reads_reject_show_trash_before_network() -> None:
    http = RecordingHttp()
    adapter = TopvisorAdapter("504903", "secret", http=http)

    for call in (
        lambda: adapter.folders("42", show_trash=True),
        lambda: adapter.groups("42", show_trash=True),
    ):
        with pytest.raises(ValueError, match="show_trash is not supported"):
            await call()
    assert http.calls == []

    with pytest.raises(ValueError, match="show_trash is not supported"):
        TopvisorAdapter.validate_folders(42, 5, 0, True, "flat")
    with pytest.raises(ValueError, match="show_trash is not supported"):
        TopvisorAdapter.validate_groups(42, 5, 0, True)

    for operation in (FOLDERS_OPERATION, GROUPS_OPERATION):
        with pytest.raises(ValueError, match="unsupported Topvisor parameters: show_trash"):
            TopvisorAdapter.validate_payload(operation, {"project_id": 42, "show_trash": False})
