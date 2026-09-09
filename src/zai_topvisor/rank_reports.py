"""Bounded saved-position comparison; never starts a ranking check."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

from zai_topvisor.adapter import TopvisorAdapter
from zai_topvisor.transport import ProviderError


def rank(value):
    if value is None:
        return None, "missing"
    if value in ("--", "‑‑"):
        return None, "not_in_depth"
    if type(value) is int and 1 <= value <= 10000:
        return value, "ranked"
    if isinstance(value, str) and value.isascii() and value.isdecimal() and 1 <= len(value) <= 5:
        number = int(value)
        if 1 <= number <= 10000:
            return number, "ranked"
    return None, "invalid"


def csv_text(rows):
    stream = io.StringIO(newline="")
    fields = [
        "keyword_id",
        "keyword",
        "before",
        "after",
        "delta",
        "before_status",
        "after_status",
        "before_url",
        "after_url",
        "url_changed",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        cells = {}
        for key in fields:
            value = row[key]
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            cells[key] = value
        writer.writerow(cells)
    return stream.getvalue()


async def report(runtime, project_id, region_index, before_date, after_date, limit, offset, format):
    if format not in {"json", "csv"}:
        raise ValueError("format must be json or csv")
    arguments = TopvisorAdapter.validate_history(
        project_id, [region_index], [before_date, after_date], limit, offset
    )
    if before_date >= after_date or limit > 250:
        raise ValueError("provide ordered distinct dates and limit at most 250")
    adapter = runtime.topvisor()
    payload = await runtime.read(
        "topvisor",
        "rank_changes",
        arguments,
        lambda: adapter.positions_history(
            project_id, [region_index], [before_date, after_date], limit, offset
        ),
    )
    keywords = payload.get("result", {}).get("keywords") if isinstance(payload.get("result"), dict) else None
    if not isinstance(keywords, list) or len(keywords) > limit:
        raise ProviderError("unexpected saved-ranking result; use raw history for inspection")
    rows, ids, by_url = [], set(), {}
    for keyword in keywords:
        if not isinstance(keyword, dict):
            raise ProviderError("invalid saved keyword record")
        identifier = keyword.get("id")
        if type(identifier) is not int or identifier < 1 or identifier in ids:
            raise ProviderError("missing or repeated keyword ID in saved history")
        ids.add(identifier)
        positions = keyword.get("positionsData", {})
        if not isinstance(positions, dict):
            raise ProviderError("invalid saved positions")
        values = []
        for date in (before_date, after_date):
            cell = positions.get(f"{date}:{project_id}:{region_index}", {})
            if not isinstance(cell, dict):
                raise ProviderError("invalid saved position cell")
            position, status = rank(cell.get("position"))
            url = cell.get("relevant_url")
            values.append((position, status, url if isinstance(url, str) and url else None))
        before, after = values
        delta = before[0] - after[0] if before[0] is not None and after[0] is not None else None
        row = dict(
            keyword_id=identifier,
            keyword=keyword.get("name") if isinstance(keyword.get("name"), str) else None,
            before=before[0],
            after=after[0],
            delta=delta,
            before_status=before[1],
            after_status=after[1],
            before_url=before[2],
            after_url=after[2],
            url_changed=(before[2] != after[2]) if before[2] and after[2] else None,
        )
        rows.append(row)
        url_key = after[2] or before[2]
        summary = by_url.setdefault(
            url_key, dict(url=url_key, keywords=0, improved=0, declined=0, unchanged=0, not_comparable=0)
        )
        summary["keywords"] += 1
        group = (
            "not_comparable"
            if delta is None
            else "improved"
            if delta > 0
            else "declined"
            if delta < 0
            else "unchanged"
        )
        summary[group] += 1
    next_offset = payload.get("nextOffset")
    if type(next_offset) is not int or not offset < next_offset <= 100000:
        next_offset = offset + len(keywords) if len(keywords) == limit and offset + limit <= 100000 else None
    result = dict(
        project_id=project_id,
        region_index=region_index,
        before_date=before_date,
        after_date=after_date,
        rows=rows,
        by_url=list(by_url.values()),
        source={
            "endpoint": "get/positions_2/history",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "offset": offset,
            "limit": limit,
            "returned_keywords": len(keywords),
            "next_offset": next_offset,
            "provider_completeness": "not_asserted",
            "snapshot": "saved_history_read_at_request_time",
        },
        notes=[
            "Positive delta means improved rank. Missing/not-in-depth values are not zero.",
            "URL totals cover this page only; grouping prefers after URL, then before URL.",
        ],
    )
    # Clean literal credentials and structured fields BEFORE serializing CSV.
    result = runtime.clean(result)
    if format == "csv":
        result["csv"] = csv_text(result.pop("rows"))
    if len(json.dumps(result, ensure_ascii=False).encode()) > 262144:
        raise ValueError("ranking report too large; lower limit")
    return result


def register_report(server, runtime):
    @server.tool(auth=runtime.require_scopes("topvisor:read"))
    async def topvisor_rank_changes(
        project_id: int,
        region_index: int,
        before_date: str,
        after_date: str,
        limit: int = 100,
        offset: int = 0,
        format: str = "json",
    ) -> dict:
        """Compare one page of saved ranks and relevant URLs on two dates; JSON/CSV, no paid checks."""
        return await report(runtime, project_id, region_index, before_date, after_date, limit, offset, format)
