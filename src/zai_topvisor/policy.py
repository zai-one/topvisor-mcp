"""Durable replay protection, per-attempt admission and metadata-only audit."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from zai_topvisor.transport import ProviderAdmissionDenied, ProviderError


class PolicyStore:
    def __init__(
        self, path: Path, account: str, rate_limit: int, principal_rate_limit: int, max_concurrency: int = 1
    ):
        self.path = path
        self.account = account
        self.rate_limit = rate_limit
        self.principal_rate_limit = principal_rate_limit
        self.max_concurrency = max_concurrency
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS nonces(nonce TEXT PRIMARY KEY, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS calls(
                    execution_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, actor TEXT NOT NULL,
                    account TEXT NOT NULL, args_hash TEXT NOT NULL, started REAL NOT NULL,
                    outcome TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(
                    execution_id TEXT NOT NULL, attempt INTEGER NOT NULL, actor TEXT NOT NULL,
                    account TEXT NOT NULL, started REAL NOT NULL,
                    PRIMARY KEY(execution_id, attempt));
                CREATE INDEX IF NOT EXISTS attempts_window ON attempts(account, started);
                CREATE TABLE IF NOT EXISTS leases(
                    execution_id TEXT PRIMARY KEY, account TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cooldowns(account TEXT PRIMARY KEY, until_time REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS writes(
                    account TEXT NOT NULL, actor TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    tool TEXT NOT NULL, args_hash TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, PRIMARY KEY(account, actor, idempotency_key));
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def begin(
        self,
        execution_id: str,
        request_id: str,
        actor: str,
        args_hash: str,
        nonce: str | None = None,
        expires: float | None = None,
    ) -> None:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM nonces WHERE expires < ?", (now,))
            if nonce is not None:
                if expires is None or expires <= now:
                    raise PermissionError("expired delegation")
                try:
                    db.execute("INSERT INTO nonces VALUES(?, ?)", (nonce, expires))
                except sqlite3.IntegrityError as exc:
                    raise PermissionError("delegation already used") from exc
            db.execute(
                "INSERT INTO calls VALUES(?, ?, ?, ?, ?, ?, 'started')",
                (execution_id, request_id, actor, self.account, args_hash, now),
            )

    def admit(self, execution_id: str, actor: str, attempt: int) -> None:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM leases WHERE expires <= ?", (now,))
            cooldown = db.execute(
                "SELECT until_time FROM cooldowns WHERE account = ?", (self.account,)
            ).fetchone()
            if cooldown and cooldown[0] > now:
                raise ProviderAdmissionDenied(
                    "provider cooldown active", retry_after_seconds=max(1, int(cooldown[0] - now + 1))
                )
            active = db.execute(
                "SELECT COUNT(*) FROM leases WHERE account = ? AND execution_id != ?",
                (self.account, execution_id),
            ).fetchone()[0]
            if active >= self.max_concurrency:
                raise ProviderAdmissionDenied("provider concurrency limit reached", retry_after_seconds=1)
            total, own = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(actor = ?), 0) FROM attempts "
                "WHERE account = ? AND started > ?",
                (actor, self.account, now - 60),
            ).fetchone()
            if total >= self.rate_limit or own >= self.principal_rate_limit:
                raise ProviderAdmissionDenied("request rate limit reached", retry_after_seconds=60)
            db.execute(
                "INSERT INTO attempts VALUES(?, ?, ?, ?, ?)",
                (execution_id, attempt, actor, self.account, now),
            )
            db.execute(
                "INSERT OR REPLACE INTO leases VALUES(?, ?, ?)", (execution_id, self.account, now + 90)
            )

    def cooldown(self, seconds: int) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO cooldowns VALUES(?, ?) ON CONFLICT(account) DO UPDATE SET "
                "until_time = MAX(until_time, excluded.until_time)",
                (self.account, time.time() + max(1, seconds)),
            )

    def finish(self, execution_id: str, outcome: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE calls SET outcome = ? WHERE execution_id = ?", (outcome, execution_id))
            db.execute("DELETE FROM leases WHERE execution_id = ?", (execution_id,))

    def reserve_write(self, actor: str, key: str, tool: str, digest: str) -> dict[str, Any] | None:
        if not 1 <= len(key) <= 128:
            raise ValueError("idempotency key must contain 1 to 128 characters")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT args_hash, status, result FROM writes "
                "WHERE account=? AND actor=? AND idempotency_key=?",
                (self.account, actor, key),
            ).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ProviderError("idempotency key was used for a different write")
                if existing[1] == "applied":
                    return json.loads(existing[2])
                # Never expire pending writes: an interrupted upstream may have applied.
                raise ProviderError("write is pending manual reconciliation")
            db.execute(
                "INSERT INTO writes VALUES(?, ?, ?, ?, ?, 'pending', NULL)",
                (self.account, actor, key, tool, digest),
            )
        return None

    def settle_write(self, actor: str, key: str, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE writes SET status='applied', result=? "
                "WHERE account=? AND actor=? AND idempotency_key=? AND status='pending'",
                (json.dumps(payload), self.account, actor, key),
            )
