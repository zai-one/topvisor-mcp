"""Operator approvals for paid or writing calls: prepare -> operator accepts outside MCP -> apply.

The MCP tool only *prepares* an approval (stores the request digest). The operator accepts it with
``topvisor-approval --path STATE_DB --approval-id ID --digest D --accept``; the agent cannot. Apply
succeeds once, only for the exact same request, before the approval expires.

Approvals live in the server's SQLite state database, next to the durable idempotency ledger and
paid-task reservations, so consuming an approval is a durable SQLite commit and can share one
transaction with the operation reservation. Each approval is bound to the configured account_id,
the Topvisor user ID, the preparing actor and the exact request (which names its project).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

TTL_SECONDS = 30 * 60
# Consumed approvals are kept so a replay of the same approval can return its stored receipt.
KEEP_CONSUMED_SECONDS = 30 * 86400


def request_digest(tool: str, request: dict[str, Any], account: str = "", user_id: str = "") -> str:
    body = json.dumps(
        {"tool": tool, "account": account, "user_id": user_id, "request": request},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def valid_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


class ApprovalStore:
    def __init__(self, path: Path, account: str = "default", user_id: str = "") -> None:
        self.path = Path(path)
        self.account, self.user_id = account, user_id
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS approvals(
                id TEXT PRIMARY KEY, account TEXT NOT NULL, user_id TEXT NOT NULL, actor TEXT,
                tool TEXT NOT NULL, digest TEXT NOT NULL, summary TEXT NOT NULL,
                accepted INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL, consumed REAL)""")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        # Rollback journal + FULL sync: a commit survives a host crash before dispatch.
        db.execute("PRAGMA synchronous=FULL")
        return db

    def digest(self, tool: str, request: dict[str, Any]) -> str:
        return request_digest(tool, request, self.account, self.user_id)

    def prepare(
        self, tool: str, request: dict[str, Any], summary: str, actor: str | None = None
    ) -> dict[str, Any]:
        approval_id, digest, now = uuid4().hex, self.digest(tool, request), time.time()
        with self.connect() as db:
            db.execute(
                "DELETE FROM approvals WHERE (consumed IS NULL AND expires<=?) OR consumed<=?",
                (now, now - KEEP_CONSUMED_SECONDS),
            )
            db.execute(
                "INSERT INTO approvals(id,account,user_id,actor,tool,digest,summary,expires) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    approval_id,
                    self.account,
                    self.user_id,
                    actor,
                    tool,
                    digest,
                    summary[:500],
                    now + TTL_SECONDS,
                ),
            )
        return {"approval_id": approval_id, "digest": digest, "expires_in_s": TTL_SECONDS}

    def accept(self, approval_id: str, digest: str) -> dict[str, Any]:
        with self.connect() as db:
            changed = db.execute(
                "UPDATE approvals SET accepted=1 WHERE id=? AND digest=? AND consumed IS NULL AND expires>?",
                (str(approval_id), str(digest), time.time()),
            ).rowcount
            row = db.execute(
                "SELECT tool,summary,account FROM approvals WHERE id=?", (str(approval_id),)
            ).fetchone()
        if changed != 1 or row is None:
            raise ValueError("approval not found, expired, used or digest mismatch")
        return {"approval_id": approval_id, "tool": row[0], "summary": row[1], "account": row[2]}

    def _matches(self, row: Any, tool: str, request: dict[str, Any], actor: str | None) -> bool:
        return row is not None and tuple(row[:5]) == (
            self.account,
            self.user_id,
            actor,
            tool,
            self.digest(tool, request),
        )

    def _row(self, db: sqlite3.Connection, approval_id: str) -> Any:
        return db.execute(
            "SELECT account,user_id,actor,tool,digest,accepted,expires,consumed FROM approvals WHERE id=?",
            (str(approval_id),),
        ).fetchone()

    def consume(
        self,
        approval_id: str,
        tool: str,
        request: dict[str, Any],
        actor: str | None = None,
        db: sqlite3.Connection | None = None,
    ) -> None:
        """Single-use check: accepted, same account, user, actor and identical request, not expired.

        Pass ``db`` (an open ``BEGIN IMMEDIATE`` transaction on the same state database) to commit the
        consumption atomically with the caller's operation reservation.
        """
        if db is None:
            with self.connect() as own:
                own.execute("BEGIN IMMEDIATE")
                self.consume(approval_id, tool, request, actor, own)
            return
        row = self._row(db, approval_id)
        if row is None or not row[5] or row[7] is not None or row[6] <= time.time():
            raise PermissionError("approval is not accepted by the operator (or expired or used)")
        if not self._matches(row, tool, request, actor):
            raise PermissionError("approval does not match this exact request, account or caller")
        db.execute("UPDATE approvals SET consumed=? WHERE id=?", (time.time(), str(approval_id)))

    def consumed_for(self, approval_id: str, tool: str, request: dict[str, Any], actor: str | None) -> bool:
        """True when this approval was already used for exactly this request by this caller."""
        with self.connect() as db:
            row = self._row(db, approval_id)
        return self._matches(row, tool, request, actor) and row[7] is not None

    def pending(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,account,actor,tool,digest,summary,expires FROM approvals "
                "WHERE accepted=0 AND consumed IS NULL AND expires>? ORDER BY expires",
                (time.time(),),
            ).fetchall()
        keys = ("approval_id", "account", "actor", "tool", "digest", "summary", "expires")
        return [dict(zip(keys, row, strict=True)) for row in rows]


def state_path(config: str | None = None) -> Path:
    """Same state database resolution as the server: --config file, then environment."""
    if config:
        from zai_topvisor.onboarding import load_config

        load_config(config)
    return Path(os.environ.get("TOPVISOR_STATE_PATH", "state/topvisor.sqlite"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operator approval for paid/writing MCP calls")
    parser.add_argument("--path", type=Path, help="server state database (TOPVISOR_STATE_PATH)")
    parser.add_argument(
        "--config", help="the server's operator JSON settings (same as topvisor-mcp --config)"
    )
    parser.add_argument("--list", action="store_true", help="show pending approvals")
    parser.add_argument("--approval-id")
    parser.add_argument("--digest")
    parser.add_argument("--accept", action="store_true")
    args = parser.parse_args(argv)
    path = args.path or state_path(args.config)
    if not path.is_file():
        parser.exit(2, f"state database not found: {path}; pass the server's --path or --config\n")
    store = ApprovalStore(path)
    if args.list or not args.accept:
        print(json.dumps(store.pending(), ensure_ascii=False, indent=2))
        return 0
    if not args.approval_id or not args.digest:
        parser.error("--accept needs --approval-id and --digest")
    print(json.dumps(store.accept(args.approval_id, args.digest), ensure_ascii=False))
    return 0


def cli() -> int:
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
