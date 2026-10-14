"""Opt-in Topvisor semantics and analytics surface (topvisor-openapi, 2026-10).

Toolset `semantics`: free deduplication and clustering progress, priced keyword collection
(keywords_2/collect) and frequency checks (keywords_2/volumes). Paid launches reuse the operator
gate of paid rank checks: TOPVISOR_WRITE_ENABLED, the project in TOPVISOR_CHECK_PROJECTS, the
estimate within TOPVISOR_CHECK_MAX_COST, an explicit approved_cost equal to a fresh price and
confirm_cost=true.
Toolset `analytics`: read-only summaries (positions summary and chart, TOP snapshots, project
competitors, tasks, audit/indexing/watcher summaries, search-engine updates, bank history).
Clustering itself is started in the Topvisor UI: the public API exposes only its progress.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from zai_topvisor.adapter import MAX_ID
from zai_topvisor.rank_checks import amount, units
from zai_topvisor.transport import ProviderError

READS = {
    "positions_summary": "get/positions_2/summary",
    "summary_chart": "get/positions_2/summary/chart",
    "snapshots_history": "get/snapshots_2/history",
    "snapshots_competitors": "get/snapshots_2/competitors",
    "competitors": "get/projects_2/competitors",
    "tasks": "get/projects_2/tasks",
    "audit_summary": "get/audit_2/audit/summary",
    "indexing_summary": "get/audit_2/indexing/summary",
    "watcher_summary": "get/audit_2/watcher/summary",
    "search_updates": "get/content_2/apometr/updates",
    "bank_history": "get/bank_2/history",
}
SEMANTICS_FREE = {
    "deduplicate": "get/keywords_2/semantics/deduplicate",
    "cluster_progress": "get/keywords_2/claster/percent",
}
PAID = {
    "collect": ("get/keywords_2/collect/price", "edit/keywords_2/collect/go"),
    "volumes": ("get/keywords_2/volumes/price", "edit/keywords_2/volumes/go"),
}
ENDPOINTS = frozenset(
    {*READS.values(), *SEMANTICS_FREE.values(), *(e for pair in PAID.values() for e in pair)}
)
VOLUME_TYPES = {"base": 1, "phrase": 2, "exact": 3, "ordered": 5, "exact_ordered": 6}
COLLECT_SEARCHERS = {
    "yandex": 0,
    "google": 1,
    "bing": 5,
    "yandex_hints": 100,
    "google_hints": 101,
    "youtube_hints": 104,
    "bing_hints": 105,
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
PAID_LAUNCH = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}


def _id(value: object, field: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_ID:
        raise ValueError(f"{field} must be a positive integer ID")
    return value


def _day(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"{field} must use YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def phrases(value: object, maximum: int = 1000) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"keywords must be a list of 1-{maximum} phrases")
    clean = []
    for item in value:
        text = " ".join(item.split()) if isinstance(item, str) else ""
        if not 1 <= len(text) <= 255 or _CONTROL.search(text):
            raise ValueError("each keyword must contain 1-255 printable characters")
        clean.append(text)
    return list(dict.fromkeys(clean))


_DATED = frozenset({"positions_summary", "summary_chart", "snapshots_history", "snapshots_competitors"})


def report_payload(
    report: str,
    project_id: int | None,
    region_index: int | None = None,
    date1: str | None = None,
    date2: str | None = None,
    competitor_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[str, dict[str, Any]]:
    if report not in READS:
        raise ValueError("report must be one of: " + ", ".join(READS))
    if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
        raise ValueError("limit must be 1-1000 and offset >= 0")
    payload: dict[str, Any] = {}
    if report not in {"bank_history", "search_updates", "tasks"} or project_id is not None:
        payload["project_id"] = _id(project_id, "project_id")
    if report in {"positions_summary", "summary_chart", "snapshots_history", "snapshots_competitors"}:
        if region_index is None:
            raise ValueError(f"{report} requires region_index (topvisor_get_project_setup)")
        if type(region_index) is not int or region_index < 0:
            raise ValueError("region_index must be a non-negative integer")
        payload["region_index"] = region_index
        if report == "positions_summary":
            payload.update(show_dynamics=True, show_tops=True, show_avg=True, show_visibility=True)
    if report == "search_updates":
        # openapi get/content_2/apometr/updates: required region_index + date; no paging.
        if type(region_index) is not int or region_index < 0:
            raise ValueError("search_updates requires region_index (apometr region)")
        if date1 is None:
            raise ValueError("search_updates requires date1 (the day to read)")
        payload = {"region_index": region_index, "date": _day(date1, "date1")}
        return READS[report], payload
    if report in _DATED and (date1 is None or date2 is None):
        # openapi: date1+date2+type_range or dates are mandatory for these selectors.
        raise ValueError(f"{report} requires date1 and date2 (YYYY-MM-DD)")
    if date1 is not None or date2 is not None:
        payload["date1"], payload["date2"] = _day(date1, "date1"), _day(date2, "date2")
        if payload["date1"] > payload["date2"]:
            raise ValueError("date1 must not be after date2")
        payload["type_range"] = 0
    if competitor_id is not None:
        payload["competitor_id"] = _id(competitor_id, "competitor_id")
    if report in {"competitors", "tasks", "bank_history", "snapshots_competitors"}:
        payload.update(limit=limit, offset=offset)
    if report == "tasks" and "project_id" in payload:
        payload["filters"] = [
            {"name": "project_id", "operator": "EQUALS", "values": [payload.pop("project_id")]}
        ]
    return READS[report], payload


def paid_payload(
    kind: str,
    project_id: int,
    *,
    keywords: list[str] | None = None,
    searcher: str = "yandex",
    region_key: int = 213,
    volume_types: list[str] | None = None,
    group_id: int | None = None,
    minus_keywords: list[str] | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    if kind not in PAID:
        raise ValueError("kind must be collect or volumes")
    payload: dict[str, Any] = {"project_id": _id(project_id, "project_id")}
    region = _id(region_key, "region_key")
    if kind == "volumes":
        if searcher not in {"yandex", "google"}:
            raise ValueError("volumes searcher must be yandex or google")
        types = volume_types or ["base", "exact"]
        if not set(types) <= set(VOLUME_TYPES):
            raise ValueError("volume_types must be from: " + ", ".join(VOLUME_TYPES))
        payload["qualifiers"] = [
            {
                "id": f"{searcher}-{region}-{name}",
                "searcher_key": 0 if searcher == "yandex" else 1,
                "region_key": region,
                "type": VOLUME_TYPES[name],
            }
            for name in dict.fromkeys(types)
        ]
        payload["target_type"] = "keywords"
        if group_id is not None:
            payload["filters"] = [
                {"name": "group_id", "operator": "EQUALS", "values": [_id(group_id, "group_id")]}
            ]
        return payload
    if searcher not in COLLECT_SEARCHERS:
        raise ValueError("collect searcher must be one of: " + ", ".join(COLLECT_SEARCHERS))
    qualifier: dict[str, Any] = {"searcher_key": COLLECT_SEARCHERS[searcher], "region_key": region}
    if depth is not None:
        if type(depth) is not int or not 1 <= depth <= 10:
            raise ValueError("depth must be 1-10")
        qualifier["depth"] = depth
    payload["keywords"] = phrases(keywords, 100)
    payload["qualifiers"] = [qualifier]
    if minus_keywords:
        payload["keywords_minus"] = phrases(minus_keywords, 500)
    if group_id is not None:
        # openapi: to_group_id is accepted only together with in_one_group=true.
        payload["in_one_group"] = True
        payload["to_group_id"] = _id(group_id, "group_id")
    return payload


def price_units(response: Any) -> int:
    result = response.get("result") if isinstance(response, dict) else None
    if isinstance(result, dict):
        result = result.get("price", result.get("sum"))
    if result is None or isinstance(result, (dict, list, bool)):
        raise ProviderError("price format unexpected; check in the Topvisor UI")
    return units(result)


async def request(
    runtime: Any, endpoint: str, payload: dict[str, Any], *, read: bool = True
) -> dict[str, Any]:
    if endpoint not in ENDPOINTS:
        raise ValueError("unsupported semantics/analytics endpoint")
    adapter = runtime.topvisor()

    async def fetch() -> dict[str, Any]:
        response = await adapter.http.request(
            "POST",
            adapter.base_url + "/" + endpoint,
            headers=adapter._headers(),
            payload=payload,
            idempotent=read,
        )
        return adapter.validate_response(response)

    return await runtime.read(
        "topvisor", "semantics" if "keywords_2" in endpoint else "analytics", payload, fetch
    )


def register_semantics(server: Any, runtime: Any) -> None:
    read_scope = runtime.require_scopes("topvisor:read")

    @server.tool(auth=read_scope, annotations=READ_ONLY)
    async def topvisor_report(
        report: Literal[
            "positions_summary",
            "summary_chart",
            "snapshots_history",
            "snapshots_competitors",
            "competitors",
            "tasks",
            "audit_summary",
            "indexing_summary",
            "watcher_summary",
            "search_updates",
            "bank_history",
        ],
        project_id: int | None = None,
        region_index: int | None = None,
        date1: str | None = None,
        date2: str | None = None,
        competitor_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Read Topvisor summaries: positions summary/chart (tops, avg, visibility), snapshots, competitors.

        Also tasks, site audit / indexing / watcher summaries, search-engine updates (apometr) and bank
        history. Free; never starts checks. region_index from topvisor_get_project_setup; summaries and
        snapshots need date1+date2; search_updates needs region_index + date1.
        """
        endpoint, payload = report_payload(
            report, project_id, region_index, date1, date2, competitor_id, limit, offset
        )
        return {"report": report, "payload": await request(runtime, endpoint, payload)}

    @server.tool(auth=read_scope, annotations=READ_ONLY)
    async def topvisor_semantics_tools(
        action: Literal["deduplicate", "cluster_progress"],
        keywords: list[str] | None = None,
        project_id: int | None = None,
        ignore_word_order: bool = True,
        ignore_stop_words: bool = True,
    ) -> dict[str, Any]:
        """Free semantics helpers: deduplicate implicit duplicate phrases, or read clustering progress (%)."""
        if action == "deduplicate":
            payload: dict[str, Any] = {
                "keywords": phrases(keywords, 10_000),
                "ignoreWordsOrder": ignore_word_order,
                "ignoreStopWords": ignore_stop_words,
            }
        else:
            payload = {"project_id": _id(project_id, "project_id")}
        return {"action": action, "payload": await request(runtime, SEMANTICS_FREE[action], payload)}

    @server.tool(auth=read_scope, annotations=READ_ONLY)
    async def topvisor_semantics_price(
        kind: Literal["collect", "volumes"],
        project_id: int,
        keywords: list[str] | None = None,
        searcher: str = "yandex",
        region_key: int = 213,
        volume_types: list[str] | None = None,
        group_id: int | None = None,
        minus_keywords: list[str] | None = None,
        depth: int | None = None,
    ) -> dict[str, Any]:
        """Price keyword collection (collect: seeds -> new phrases in a group) or a frequency check (volumes).

        Free; returns estimated_cost to show the user before topvisor_semantics_launch.
        """
        payload = paid_payload(
            kind,
            project_id,
            keywords=keywords,
            searcher=searcher,
            region_key=region_key,
            volume_types=volume_types,
            group_id=group_id,
            minus_keywords=minus_keywords,
            depth=depth,
        )
        cost = price_units(await request(runtime, PAID[kind][0], payload))
        return {
            "kind": kind,
            "selection": payload,
            "estimated_cost": amount(cost),
            "paid_dispatch": False,
            "next": "show the cost; after explicit OK call topvisor_semantics_launch with approved_cost",
        }

    @server.tool(auth=runtime.require_scopes("topvisor:read", "topvisor:write"), annotations=PAID_LAUNCH)
    async def topvisor_semantics_launch(
        kind: Literal["collect", "volumes"],
        project_id: int,
        approved_cost: str,
        confirm_cost: bool = False,
        keywords: list[str] | None = None,
        searcher: str = "yandex",
        region_key: int = 213,
        volume_types: list[str] | None = None,
        group_id: int | None = None,
        minus_keywords: list[str] | None = None,
        depth: int | None = None,
    ) -> dict[str, Any]:
        """Launch a priced collect/volumes task once the user approved the exact cost (spends balance).

        Needs confirm_cost=true, operator write + paid-check limits, and a fresh price equal to approved_cost.
        """
        config = runtime.config
        approved = units(approved_cost)
        if not confirm_cost or not config.write_enabled or units(config.check_max_cost) <= 0:
            raise PermissionError("explicit cost confirmation and operator check limits required")
        if project_id not in config.check_projects:
            raise PermissionError("project not enabled for paid Topvisor tasks")
        payload = paid_payload(
            kind,
            project_id,
            keywords=keywords,
            searcher=searcher,
            region_key=region_key,
            volume_types=volume_types,
            group_id=group_id,
            minus_keywords=minus_keywords,
            depth=depth,
        )
        cost = price_units(await request(runtime, PAID[kind][0], payload))
        if cost != approved or approved > units(config.check_max_cost):
            raise PermissionError("price changed or exceeds the operator limit; request a new price")
        response = await request(runtime, PAID[kind][1], payload, read=False)
        return {
            "kind": kind,
            "submitted": True,
            "completed": False,
            "estimated_cost": amount(cost),
            "result": response.get("result"),
            "next": "poll topvisor_report(report='tasks'), then topvisor_list_keywords",
        }
