"""Opt-in Topvisor semantics and analytics surface (topvisor-openapi, 2026-10).

Toolset `semantics`: free deduplication and clustering progress, priced keyword collection
(keywords_2/collect), frequency checks (keywords_2/volumes), relevance checks and indexing
requests (projects_2/tasks). Paid launches reuse the operator gate of paid rank checks:
TOPVISOR_WRITE_ENABLED, the project in TOPVISOR_CHECK_PROJECTS, the estimate within
TOPVISOR_CHECK_MAX_COST and the daily TOPVISOR_CHECK_DAILY_BUDGET (shared with rank checks), an
explicit approved_cost equal to a fresh price, confirm_cost=true and an operator-accepted
approval_id (topvisor-approval).
Toolset `competitors_write`: approval-gated competitor add/del/import/edit.
Toolset `analytics`: read-only summaries (positions summary and chart, TOP snapshots, project
competitors, tasks, audit/indexing/watcher summaries, search-engine updates, bank history).
Clustering itself is started in the Topvisor UI: the public API exposes only its progress.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from datetime import date
from typing import Any, Literal

from zai_topvisor.adapter import MAX_ID
from zai_topvisor.approvals import ApprovalStore, valid_id
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
    # openapi projects_2/tasks: relevance check and indexing request (priced, then paid).
    "relevants": ("get/projects_2/tasks/relevants/price", "add/projects_2/tasks/relevants"),
    "indexing": ("get/projects_2/tasks/indexing/price", "add/projects_2/tasks/indexing"),
}
COMPETITOR_WRITES = {
    "add": "add/projects_2/competitors",
    "delete": "del/projects_2/competitors",
    "import": "add/projects_2/competitors/import",
    "rename": "edit/projects_2/competitors/name",
    "brand": "edit/projects_2/competitors/brand",
    "enable": "edit/projects_2/competitors/on",
    "move": "edit/projects_2/competitors/move",
}
ENDPOINTS = frozenset(
    {
        *READS.values(),
        *SEMANTICS_FREE.values(),
        *(e for pair in PAID.values() for e in pair),
        *COMPETITOR_WRITES.values(),
    }
)
DEVICES = {"desktop": 0, "tablet": 1, "mobile": 2}
INDEXING_SEARCHERS = {"yandex": "0", "google": "1", "bing": "5"}
_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}(/[^\s<>]{0,2000})?")
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
    # openapi: positions_2/summary(+chart) require region_index; snapshots_2/* have no such field.
    if report in {"positions_summary", "summary_chart"}:
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
    url: str | None = None,
    urls: list[str] | None = None,
    indexing_searchers: list[str] | None = None,
    device: str = "desktop",
    launch: bool = False,
) -> dict[str, Any]:
    if kind not in PAID:
        raise ValueError("kind must be one of: " + ", ".join(PAID))
    _id(project_id, "project_id")
    if kind == "relevants":
        if device not in DEVICES:
            raise ValueError("device must be desktop, tablet or mobile")
        if searcher not in {"yandex", "google"}:
            raise ValueError("relevants searcher must be yandex or google")
        payload = {
            "keywords": phrases(keywords, 1000),
            "qualifiers": [
                {
                    "searcher_key": 0 if searcher == "yandex" else 1,
                    "region_key": _id(region_key, "region_key"),
                    "region_device": DEVICES[device],
                }
            ],
        }
        if launch:
            payload["url"] = _host(url, "url")
        return payload
    if kind == "indexing":
        engines = indexing_searchers or ["yandex"]
        if not set(engines) <= set(INDEXING_SEARCHERS):
            raise ValueError("indexing_searchers must be from: yandex, google, bing")
        payload = {"indexing_searchers_keys": [INDEXING_SEARCHERS[e] for e in dict.fromkeys(engines)]}
        if urls:
            if not isinstance(urls, list) or len(urls) > 10_000:
                raise ValueError("urls must be a list of at most 10000 URLs")
            payload["urls"] = [_host(u, "urls") for u in urls]
        else:
            raise ValueError("indexing needs urls (project-domain pages)")
        return payload
    payload: dict[str, Any] = {"project_id": project_id}
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


def _host(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a URL")
    text = re.sub(r"^https?://", "", value.strip()).removeprefix("www.").rstrip("/")
    if not _HOST.fullmatch(text):
        raise ValueError(f"{field} must be a URL without spaces or < >")
    return text


def competitor_payload(action: str, project_id: int, **a: Any) -> dict[str, Any]:
    """Validate one competitor write per openapi projects_2/competitors."""
    if action not in COMPETITOR_WRITES:
        raise ValueError("action must be one of: " + ", ".join(COMPETITOR_WRITES))
    payload: dict[str, Any] = {"project_id": _id(project_id, "project_id")}
    a = {k: v for k, v in a.items() if v is not None}
    if action == "add":
        urls = a.get("urls")
        if not isinstance(urls, list) or not 1 <= len(urls) <= 100:
            raise ValueError("add needs urls (1-100)")
        payload["urls"] = [_host(u, "urls") for u in urls]
        if "names" in a:
            payload["names"] = phrases(a["names"], 100)
        return payload
    if action in {"delete", "enable"}:
        ids = a.get("ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
            raise ValueError(f"{action} needs ids (1-100)")
        payload["ids"] = [_id(i, "ids") for i in dict.fromkeys(ids)]
        if action == "enable":
            if a.get("on") not in (True, False):
                raise ValueError("enable needs on=true|false")
            payload["on"] = 0 if a["on"] else -1
        return payload
    if action == "import":
        text = a.get("competitors")
        if not isinstance(text, str) or not 1 <= len(text) <= 200_000:
            raise ValueError("import needs competitors as CSV text")
        payload["competitors"] = text
        return payload
    payload["id"] = _id(a.get("id"), "id")
    if action == "rename":
        payload["name"] = phrases([a.get("name")], 1)[0] if isinstance(a.get("name"), str) else _bad("name")
    elif action == "brand":
        if "name" in a:
            payload["name"] = phrases([a["name"]], 1)[0]
        if "aliases" in a:
            payload["aliases"] = phrases(a["aliases"], 100)
    else:
        payload["to_id"] = _id(a.get("to_id"), "to_id")
        if a.get("to_type", "after") not in {"before", "after"}:
            raise ValueError("to_type must be before or after")
        payload["to_type"] = a.get("to_type", "after")
    return payload


def _bad(field: str) -> Any:
    raise ValueError(f"{field} is required")


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


def approvals(runtime: Any) -> ApprovalStore:
    # Same SQLite state database as the idempotency ledger and paid-task reservations.
    config = runtime.config
    return ApprovalStore(config.state_path, config.account_id, config.user_id)


def _quoted(path: Any) -> str:
    text = str(path.absolute())
    return subprocess.list2cmdline([text]) if os.name == "nt" else shlex.quote(text)


def approval_ticket(runtime: Any, tool: str, request_body: dict[str, Any], summary: str) -> dict[str, Any]:
    ticket = approvals(runtime).prepare(tool, request_body, summary, runtime.state.get().actor)
    return {
        "needs_operator_approval": True,
        **ticket,
        "summary": summary,
        "request": request_body,
        "operator_command": f"topvisor-approval --path {_quoted(runtime.config.state_path)} "
        f"--approval-id {ticket['approval_id']} --digest {ticket['digest']} --accept",
        "hint": "Show the request; the operator (not the agent) runs operator_command, then repeat the "
        "same call with approval_id.",
    }


def _approval_id(value: object) -> str:
    if not valid_id(value):
        raise PermissionError("approval is not accepted by the operator (or expired or used)")
    return str(value)


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
        history. Free; never starts checks. Summaries need region_index (topvisor_get_project_setup);
        summaries and snapshots need date1+date2; search_updates needs region_index + date1.
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
        kind: Literal["collect", "volumes", "relevants", "indexing"],
        project_id: int,
        keywords: list[str] | None = None,
        searcher: str = "yandex",
        region_key: int = 213,
        volume_types: list[str] | None = None,
        group_id: int | None = None,
        minus_keywords: list[str] | None = None,
        depth: int | None = None,
        url: str | None = None,
        urls: list[str] | None = None,
        indexing_searchers: list[str] | None = None,
        device: Literal["desktop", "tablet", "mobile"] = "desktop",
    ) -> dict[str, Any]:
        """Price a paid task: collect (seeds -> phrases), volumes (frequency), relevants (relevance check
        of url for keywords), indexing (send urls to search engines).

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
            url=url,
            urls=urls,
            indexing_searchers=indexing_searchers,
            device=device,
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
        kind: Literal["collect", "volumes", "relevants", "indexing"],
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
        url: str | None = None,
        urls: list[str] | None = None,
        indexing_searchers: list[str] | None = None,
        device: Literal["desktop", "tablet", "mobile"] = "desktop",
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Launch a priced paid task once the user approved the exact cost (spends balance).

        Needs confirm_cost=true, operator write + paid-check limits, a fresh price equal to approved_cost
        and an operator approval: the first call returns approval_id; repeat with it once accepted.
        """
        config = runtime.config
        approved = units(approved_cost)
        if (
            not confirm_cost
            or not config.write_enabled
            or units(config.check_max_cost) <= 0
            or units(config.check_daily_budget) <= 0
        ):
            raise PermissionError("explicit cost confirmation and operator check limits required")
        if project_id not in config.check_projects:
            raise PermissionError("project not enabled for paid Topvisor tasks")
        options = {
            "keywords": keywords,
            "searcher": searcher,
            "region_key": region_key,
            "volume_types": volume_types,
            "group_id": group_id,
            "minus_keywords": minus_keywords,
            "depth": depth,
            "url": url,
            "urls": urls,
            "indexing_searchers": indexing_searchers,
            "device": device,
        }
        payload = paid_payload(kind, project_id, **options)
        launch_payload = paid_payload(kind, project_id, launch=True, **options)
        tool = "topvisor_semantics_launch"
        # project_id is part of the approved request: relevants/indexing payloads do not carry it.
        ticket_request = {
            "kind": kind,
            "project_id": project_id,
            "payload": launch_payload,
            "approved_cost": amount(approved),
        }
        actor, store = runtime.state.get().actor, approvals(runtime)
        if approval_id:
            approval_id = _approval_id(approval_id)
            prior = runtime.checks.task(actor, approval_id)
            if prior is not None:
                # The approval is the operation identity: never dispatch it twice.
                if not store.consumed_for(approval_id, tool, ticket_request, actor):
                    raise PermissionError("approval does not match this exact request")
                if prior["state"] == "accepted":
                    return {**json.loads(prior["result"]), "replayed": True}
                raise ProviderError(
                    "dispatch outcome of this approval is unknown or reconciled; "
                    "operator reconciliation (topvisor-check-reconcile) required"
                )
        cost = price_units(await request(runtime, PAID[kind][0], payload))
        if cost != approved or approved > units(config.check_max_cost):
            raise PermissionError("price changed or exceeds the operator limit; request a new price")
        if not approval_id:
            return approval_ticket(runtime, tool, ticket_request, f"{kind} {amount(cost)}")
        # Approval use, budget reservation and the project fence commit in one durable SQLite
        # transaction before the possibly dispatched request. An unknown outcome stays counted
        # against TOPVISOR_CHECK_DAILY_BUDGET (shared with paid rank checks) and blocks further paid
        # tasks for the project until topvisor-check-reconcile.
        task_id = runtime.checks.claim_task(
            actor,
            project_id,
            kind,
            cost,
            units(config.check_daily_budget),
            operation_id=approval_id,
            consume=lambda db: store.consume(approval_id, tool, ticket_request, actor, db),
        )
        response = await request(runtime, PAID[kind][1], launch_payload, read=False)
        answer = {
            "kind": kind,
            "task_id": task_id,
            "submitted": True,
            "completed": False,
            "replayed": False,
            "estimated_cost": amount(cost),
            "result": response.get("result"),
            "next": "poll topvisor_report(report='tasks'), then topvisor_list_keywords",
        }
        runtime.checks.task_accepted(task_id, answer)
        return answer

    @server.tool(
        auth=runtime.require_scopes("topvisor:read", "topvisor:write"),
        annotations={**PAID_LAUNCH, "destructiveHint": True},
    )
    async def topvisor_competitors_write(
        action: Literal["add", "delete", "import", "rename", "brand", "enable", "move"],
        project_id: int,
        urls: list[str] | None = None,
        names: list[str] | None = None,
        ids: list[int] | None = None,
        id: int | None = None,
        name: str | None = None,
        aliases: list[str] | None = None,
        on: bool | None = None,
        to_id: int | None = None,
        to_type: Literal["before", "after"] | None = None,
        competitors: str | None = None,
        approval_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Change project competitors: add urls, delete/enable ids, import CSV, rename, brand (AI answers
        name/aliases), move. Needs TOPVISOR_WRITE_ENABLED and an operator approval: the first call
        returns approval_id; repeat with it once accepted. Identical repeats return the stored result
        (pass a new idempotency_key to redo a completed change on purpose).
        """
        if not runtime.config.write_enabled:
            raise PermissionError("Topvisor writes are disabled by the operator")
        payload = competitor_payload(
            action,
            project_id,
            urls=urls,
            names=names,
            ids=ids,
            id=id,
            name=name,
            aliases=aliases,
            on=on,
            to_id=to_id,
            to_type=to_type,
            competitors=competitors,
        )
        endpoint = COMPETITOR_WRITES[action]
        tool = "topvisor_competitors_write"
        ticket_request = {"endpoint": endpoint, "payload": payload}
        if not approval_id:
            return approval_ticket(runtime, tool, ticket_request, endpoint)
        approvals(runtime).consume(_approval_id(approval_id), tool, ticket_request, runtime.state.get().actor)

        async def apply() -> Any:
            return (await request(runtime, endpoint, payload, read=False)).get("result")

        async def readback(_result: Any) -> Any:
            listing = {"project_id": project_id, "limit": 100, "offset": 0}
            return (await request(runtime, READS["competitors"], listing)).get("result")

        # Durable idempotency ledger (as for other writes): the operation is reserved as pending
        # before dispatch; an identical repeat returns the stored result, and an unconfirmed one
        # stays pending (never resubmitted) until the operator reconciles it.
        written = await runtime.write(
            "topvisor",
            tool,
            ticket_request,
            idempotency_key,
            enabled=runtime.config.write_enabled,
            validate=lambda: None,
            apply_fn=apply,
            readback_fn=readback,
        )
        return {"action": action, **written}
