"""Durable quotes and project fences for explicitly approved paid rank checks."""

from __future__ import annotations

import json
import time
from uuid import uuid4

from zai_topvisor.transport import ProviderError


class CheckStore:
    def __init__(self, policy):
        self.policy = policy
        with policy.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rank_checks(
                id TEXT PRIMARY KEY, account TEXT NOT NULL, actor TEXT NOT NULL,
                project INTEGER NOT NULL, payload TEXT NOT NULL, cost INTEGER NOT NULL,
                created REAL NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL,
                reserved INTEGER NOT NULL DEFAULT 0, dispatched REAL, result TEXT)""")

    def create(self, actor, project, payload, cost):
        identifier, now = uuid4().hex, time.time()
        with self.policy.connect() as db:
            db.execute(
                "INSERT INTO rank_checks(id,account,actor,project,payload,cost,created,expires,state) "
                "VALUES(?,?,?,?,?,?,?,?,'quoted')",
                (identifier, self.policy.account, actor, project, json.dumps(payload), cost, now, now + 300),
            )
        return self.get(actor, identifier)

    def get(self, actor, identifier):
        if not isinstance(identifier, str) or len(identifier) != 32:
            raise ValueError("valid check_id required")
        with self.policy.connect() as db:
            row = db.execute(
                "SELECT id,project,payload,cost,expires,state,result FROM rank_checks "
                "WHERE id=? AND account=? AND actor=?",
                (identifier, self.policy.account, actor),
            ).fetchone()
        if row is None:
            raise PermissionError("check quote is unavailable for this account and actor")
        return dict(
            zip(("check_id", "project_id", "payload", "cost", "expires", "state", "result"), row, strict=True)
        )

    def claim(self, actor, identifier, daily_budget):
        with self.policy.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            # UTC day, measured after acquiring the transaction lock.
            day = int(now // 86400) * 86400
            row = db.execute(
                "SELECT project,cost,expires,state FROM rank_checks WHERE id=? AND account=? AND actor=?",
                (identifier, self.policy.account, actor),
            ).fetchone()
            if not row or row[3] != "quoted" or row[2] <= now:
                raise ProviderError("quote expired, consumed or awaiting reconciliation")
            if db.execute(
                "SELECT 1 FROM rank_checks WHERE account=? AND project=? "
                "AND state IN ('dispatching','accepted') LIMIT 1",
                (self.policy.account, row[0]),
            ).fetchone():
                raise ProviderError("this project has a check awaiting operator reconciliation")
            total = db.execute(
                "SELECT COALESCE(SUM(reserved),0) FROM rank_checks WHERE account=? AND dispatched>=?",
                (self.policy.account, day),
            ).fetchone()[0]
            if total + row[1] > daily_budget:
                raise PermissionError("daily ranking-check estimate budget exhausted")
            db.execute(
                "UPDATE rank_checks SET state='dispatching',reserved=cost,dispatched=? WHERE id=?",
                (now, identifier),
            )

    def accepted(self, actor, identifier, result):
        with self.policy.connect() as db:
            changed = db.execute(
                "UPDATE rank_checks SET state='accepted',result=? "
                "WHERE id=? AND account=? AND actor=? AND state='dispatching'",
                (json.dumps(result), identifier, self.policy.account, actor),
            ).rowcount
            if changed != 1:
                raise ProviderError("rank-check state changed; reconcile before another dispatch")

    def reconcile(self, identifier, outcome):
        if outcome not in {"completed", "not_dispatched"}:
            raise ValueError("explicit reconciliation outcome required")
        with self.policy.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,dispatched FROM rank_checks WHERE id=? AND account=?",
                (identifier, self.policy.account),
            ).fetchone()
            if not row or row[0] not in {"dispatching", "accepted"}:
                raise ValueError("no unresolved rank check in this account")
            # Standalone calls have a 75-second deadline; include IO/clock margin.
            if row[0] == "dispatching" and (row[1] is None or time.time() < row[1] + 120):
                raise ValueError(
                    "wait at least two minutes after dispatch before reconciling unknown outcome"
                )
            db.execute(
                "UPDATE rank_checks SET state=?,reserved=CASE WHEN ?='not_dispatched' THEN 0 "
                "ELSE reserved END WHERE id=? AND account=?",
                ("reconciled_" + outcome, outcome, identifier, self.policy.account),
            )
