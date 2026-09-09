from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def read_secret_file(value: str) -> str:
    if not value:
        raise ValueError("credential file required")
    path = Path(value)
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("credential file missing or too large")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("credential file must be owner-private")
    result = path.read_text(encoding="utf-8").strip()
    if not result:
        raise ValueError("credential file empty")
    return result


@dataclass(frozen=True)
class ServiceConfig:
    user_id: str
    api_key: str = field(repr=False)
    state_path: Path
    account_id: str = "default"
    principal_id: str = "local-operator"
    public_key: str = ""
    issuer: str = "topvisor-operator"
    audience: str = "topvisor-mcp"
    local_scopes: frozenset[str] = frozenset({"topvisor:read", "topvisor:write"})
    write_enabled: bool = False
    rate_limit: int = 20
    principal_rate_limit: int = 20
    max_concurrency: int = 2
    check_projects: frozenset[int] = frozenset()
    check_max_cost: str = "0"
    check_daily_budget: str = "0"

    def __post_init__(self) -> None:
        if not self.user_id.isdecimal() or not 1 <= int(self.user_id) <= 2_147_483_647:
            raise ValueError("valid Topvisor user ID required")
        if not self.api_key or len(self.api_key) > 4096:
            raise ValueError("valid API key required")
        if not all(
            isinstance(value, str) and 1 <= len(value) <= 256
            for value in (self.account_id, self.principal_id, self.issuer, self.audience)
        ):
            raise ValueError("identity fields required")
        if not self.local_scopes <= {"topvisor:read", "topvisor:write"}:
            raise ValueError("unknown local scope")
        if not 1 <= self.principal_rate_limit <= self.rate_limit <= 1000:
            raise ValueError("invalid request limits")
        if not 1 <= self.max_concurrency <= 20:
            raise ValueError("invalid concurrency limit")
        from zai_topvisor.rank_checks import units

        if len(self.check_projects) > 100 or any(
            type(v) is not int or not 1 <= v <= 2147483647 for v in self.check_projects
        ):
            raise ValueError("invalid paid-check project allowlist")
        maximum, daily = units(self.check_max_cost), units(self.check_daily_budget)
        if maximum > daily:
            raise ValueError("check maximum cannot exceed daily estimate budget")

    @classmethod
    def from_env(cls) -> ServiceConfig:
        public_path = os.environ.get("TOPVISOR_MCP_PUBLIC_KEY_FILE", "")
        enabled = os.environ.get("TOPVISOR_WRITE_ENABLED", "false")
        if enabled not in {"true", "false"}:
            raise ValueError("TOPVISOR_WRITE_ENABLED must be true or false")
        return cls(
            user_id=os.environ.get("TOPVISOR_USER_ID", ""),
            api_key=read_secret_file(os.environ.get("TOPVISOR_API_KEY_FILE", "")),
            state_path=Path(os.environ.get("TOPVISOR_STATE_PATH", "state/topvisor.sqlite")),
            account_id=os.environ.get("TOPVISOR_ACCOUNT_ID", "default"),
            principal_id=os.environ.get("TOPVISOR_LOCAL_PRINCIPAL", "local-operator"),
            public_key=Path(public_path).read_text(encoding="utf-8") if public_path else "",
            issuer=os.environ.get("TOPVISOR_MCP_ISSUER", "topvisor-operator"),
            audience=os.environ.get("TOPVISOR_MCP_AUDIENCE", "topvisor-mcp"),
            write_enabled=enabled == "true",
            rate_limit=int(os.environ.get("TOPVISOR_RATE_LIMIT", "20")),
            principal_rate_limit=int(os.environ.get("TOPVISOR_PRINCIPAL_RATE_LIMIT", "20")),
            max_concurrency=int(os.environ.get("TOPVISOR_MAX_CONCURRENCY", "2")),
            check_projects=frozenset(
                int(v) for v in os.environ.get("TOPVISOR_CHECK_PROJECTS", "").split(",") if v
            ),
            check_max_cost=os.environ.get("TOPVISOR_CHECK_MAX_COST", "0"),
            check_daily_budget=os.environ.get("TOPVISOR_CHECK_DAILY_BUDGET", "0"),
        )
