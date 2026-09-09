"""Price, explicitly launch and inspect one project's bounded region selection."""

from __future__ import annotations

import argparse
import json
import re
import time
from decimal import Decimal, InvalidOperation

from zai_topvisor.adapter import MAX_ID
from zai_topvisor.check_store import CheckStore
from zai_topvisor.transport import ProviderError


def units(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 24:
        raise ValueError("cost must be a bounded nonnegative decimal")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not 0 <= amount <= 1000000 or amount * 1000000 != int(amount * 1000000):
            raise ValueError("cost must have at most six decimal places")
        return int(amount * 1000000)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("invalid cost") from exc


def amount(value):
    return format(Decimal(value) / 1000000, "f")


def selection(project_id, region_indexes):
    if type(project_id) is not int or not 1 <= project_id <= MAX_ID:
        raise ValueError("one project ID required")
    if (
        not isinstance(region_indexes, list)
        or not 1 <= len(region_indexes) <= 10
        or any(type(v) is not int or not 0 <= v <= MAX_ID for v in region_indexes)
        or len(set(region_indexes)) != len(region_indexes)
    ):
        raise ValueError("provide 1-10 distinct project region indexes")
    return {
        "filters": [{"name": "id", "operator": "EQUALS", "values": [project_id]}],
        "regions_indexes": sorted(region_indexes),
        "do_snapshots": 0,
    }


async def request(runtime, endpoint, payload, *, read=True):
    # Internal fixed routes only; no generic method is exposed to callers.
    if endpoint not in {
        "get/positions_2/checker/price",
        "edit/positions_2/checker/go",
        "get/projects_2/projects",
    }:
        raise ValueError("unsupported rank-check endpoint")
    adapter = runtime.topvisor()

    async def fetch():
        response = await adapter.http.request(
            "POST",
            adapter.base_url + "/" + endpoint,
            headers=adapter._headers(),
            payload=payload,
            idempotent=read,
        )
        return adapter.validate_response(response)

    return await runtime.read("topvisor", "ranking_check", payload, fetch)


async def price(runtime, payload, project_id):
    value = await request(runtime, "get/positions_2/checker/price", {**payload, "apply_discount": True})
    result = value.get("result")
    owners = result.get("pricesByUsers") if isinstance(result, dict) else None
    owner_id = str(int(runtime.config.user_id))
    if not isinstance(owners, dict) or set(owners) != {owner_id}:
        raise ProviderError("price must belong only to the configured account owner")
    row = owners[owner_id]
    if (
        not isinstance(row, dict)
        or row.get("projectsIds") != [project_id]
        or type(row["projectsIds"][0]) is not int
    ):
        raise ProviderError("price does not cover exactly the selected project")
    return units(row.get("price"))


def quote_view(record):
    return {
        "check_id": record["check_id"],
        "project_id": record["project_id"],
        "selection": json.loads(record["payload"]),
        "estimated_cost": amount(record["cost"]),
        "cost_unit": "provider_account_currency",
        "expires_at_unix": record["expires"],
        "state": record["state"],
        "paid_dispatch": False,
        "notes": [
            "This price is an estimate, not a provider-enforced billing cap.",
            "Project contents or provider prices can change between price and dispatch.",
        ],
    }


def register_checks(server, runtime):
    @server.tool(auth=runtime.require_scopes("topvisor:read"))
    async def topvisor_check_quote(project_id: int, region_indexes: list[int]) -> dict:
        """Get a five-minute price quote for one owned project and explicit regions; no paid dispatch."""
        payload = selection(project_id, region_indexes)
        cost = await price(runtime, payload, project_id)
        record = runtime.checks.create(runtime.state.get().actor, project_id, payload, cost)
        return quote_view(record)

    @server.tool(auth=runtime.require_scopes("topvisor:read", "topvisor:write"))
    async def topvisor_check_launch(check_id: str, approved_cost: str, confirm_cost: bool = False) -> dict:
        """Launch an approved quote once, under operator project/estimate budgets. Outcome may be unknown."""
        config, actor = runtime.config, runtime.state.get().actor
        approved = units(approved_cost)
        if not confirm_cost or not config.write_enabled or units(config.check_max_cost) <= 0:
            raise PermissionError("explicit cost confirmation and operator check limits required")
        record = runtime.checks.get(actor, check_id)
        if record["project_id"] not in config.check_projects:
            raise PermissionError("project not enabled for paid rank checks")
        if approved != record["cost"] or approved > units(config.check_max_cost):
            raise PermissionError("approved estimate differs from quote or exceeds operator limit")
        if record["state"] == "accepted":
            return {**json.loads(record["result"]), "replayed": True}
        if record["state"] != "quoted" or record["expires"] <= time.time():
            raise ProviderError("quote expired or consumed; inspect its status")
        payload = json.loads(record["payload"])
        if await price(runtime, payload, record["project_id"]) != record["cost"]:
            raise ProviderError("price changed; request and approve a new quote")
        # Committed before possibly dispatched request; every exception leaves the fence in place.
        runtime.checks.claim(actor, check_id, units(config.check_daily_budget))
        response = await request(runtime, "edit/positions_2/checker/go", payload, read=False)
        result = response.get("result")
        if (
            not isinstance(result, dict)
            or result.get("projectsIds") != [record["project_id"]]
            or type(result["projectsIds"][0]) is not int
        ):
            raise ProviderError("dispatch acknowledgement unexpected; operator reconciliation required")
        answer = {
            "check_id": check_id,
            "project_id": record["project_id"],
            "state": "accepted",
            "submitted": True,
            "completed": False,
            "replayed": False,
            "estimated_cost": amount(record["cost"]),
            "billing_cap_enforced_by_provider": False,
            "next_step": "inspect project status and reconcile locally before another check",
        }
        runtime.checks.accepted(actor, check_id, answer)
        return answer

    @server.tool(auth=runtime.require_scopes("topvisor:read"))
    async def topvisor_check_status(check_id: str) -> dict:
        """Read your local check receipt and aggregate project status; does not infer job completion."""
        record = runtime.checks.get(runtime.state.get().actor, check_id)
        response = await request(
            runtime,
            "get/projects_2/projects",
            {
                "id": record["project_id"],
                "limit": 1,
                "fields": ["id", "status_positions", "status_positions_percent", "positions_time"],
            },
        )
        rows = response.get("result")
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
            or type(rows[0].get("id")) is not int
            or rows[0]["id"] != record["project_id"]
        ):
            raise ProviderError("project status unavailable")
        return {
            "check_id": check_id,
            "state": record["state"],
            "project": rows[0],
            "completion_of_this_check": "not_asserted",
            "notes": [
                "Project status is aggregate; other clients can also run checks.",
                "Reconcile using the local operator command after verifying provider outcome.",
            ],
        }


def reconcile_main(argv=None):
    from zai_topvisor.config import ServiceConfig
    from zai_topvisor.onboarding import load_config
    from zai_topvisor.policy import PolicyStore

    parser = argparse.ArgumentParser(description="Reconcile a ranking check after inspecting Topvisor")
    parser.add_argument("--config", required=True)
    parser.add_argument("--check-id", required=True)
    parser.add_argument("--outcome", choices=["completed", "not_dispatched"], required=True)
    parser.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if re.fullmatch(r"[a-f0-9]{32}", args.check_id) is None:
            raise ValueError("invalid identifier")
        load_config(args.config)
        config = ServiceConfig.from_env()
        policy = PolicyStore(
            config.state_path,
            config.account_id,
            config.rate_limit,
            config.principal_rate_limit,
            config.max_concurrency,
        )
        CheckStore(policy).reconcile(args.check_id, args.outcome)
    except Exception:
        parser.exit(2, "reconciliation failed; check local configuration and receipt\n")
    print(json.dumps({"check_id": args.check_id, "outcome": args.outcome, "provider_contacted": False}))
