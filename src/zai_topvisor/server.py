from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

from zai_topvisor import __version__
from zai_topvisor.adapter import TopvisorAdapter
from zai_topvisor.coalescing import AsyncSingleFlight
from zai_topvisor.config import ServiceConfig
from zai_topvisor.errors import SafeToolError, safe_provider_error
from zai_topvisor.onboarding import check_config, load_config
from zai_topvisor.policy import PolicyStore
from zai_topvisor.sanitizer import sanitize_provider_response
from zai_topvisor.tools import register_tools
from zai_topvisor.transport import (
    JsonHttpClient,
    ProviderAdmissionDenied,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeoutError,
    request_hash,
)

T = TypeVar("T")
OPERATION_TIMEOUT_SECONDS = 75.0


class RequestOwnedFlight(AsyncSingleFlight):
    async def run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        return await factory()


class AdmittedHttpClient(JsonHttpClient):
    def __init__(self, store: PolicyStore, execution_id: str, actor: str):
        super().__init__(timeout=60)
        self.store, self.execution_id, self.actor = store, execution_id, actor
        self.attempt_count = 0

    async def _admit_attempt(self, attempt: int) -> None:
        # One MCP tool can run several reads/readbacks; count every HTTP attempt.
        self.attempt_count += 1
        self.store.admit(self.execution_id, self.actor, self.attempt_count)


@dataclass
class CallState:
    execution_id: str
    actor: str
    adapter: TopvisorAdapter


class Runtime:
    def __init__(self, config: ServiceConfig, transport: str, http_factory: Callable[..., Any] | None):
        self.config, self.transport = config, transport
        self.http_factory = http_factory or AdmittedHttpClient
        self.store = PolicyStore(
            config.state_path,
            config.account_id,
            config.rate_limit,
            config.principal_rate_limit,
            config.max_concurrency,
        )
        self.state: ContextVar[CallState] = ContextVar("topvisor_call")
        self.topvisor_write_enabled = config.write_enabled

    def require_scopes(self, *scopes: str) -> Callable[[Any], bool]:
        def check(context: Any) -> bool:
            available = (
                self.config.local_scopes
                if self.transport == "stdio"
                else (context.token.scopes if context.token else [])
            )
            return set(scopes) <= set(available)

        return check

    def identity(self) -> str:
        if self.transport == "stdio":
            return self.config.principal_id
        token = get_access_token()
        claims = token.claims if token else {}
        actor, expires = claims.get("sub"), claims.get("exp")
        if (
            not isinstance(actor, str)
            or not 1 <= len(actor) <= 256
            or claims.get("account_id") != self.config.account_id
            or not isinstance(expires, (int, float))
            or isinstance(expires, bool)
            or not math.isfinite(expires)
            or expires <= time.time()
        ):
            raise PermissionError("account-bound authenticated identity required")
        return actor

    def clean(self, value: Any) -> Any:
        def literal(item: Any) -> Any:
            if isinstance(item, str):
                return item.replace(self.config.api_key, "***redacted***")
            if isinstance(item, list):
                return [literal(child) for child in item]
            if isinstance(item, dict):
                return {literal(key): literal(child) for key, child in item.items()}
            return item

        return literal(sanitize_provider_response(value))

    @staticmethod
    def safe_error(provider: str, exc: Exception) -> SafeToolError:
        return safe_provider_error(provider, exc)

    def topvisor(self) -> TopvisorAdapter:
        return self.state.get().adapter

    async def execute(
        self, tool: str, arguments: dict[str, Any], factory: Callable[[], Awaitable[Any]]
    ) -> Any:
        execution_id = uuid4().hex
        begun = False
        context_token = None
        try:
            actor = self.identity()
            self.store.begin(
                execution_id, uuid4().hex, actor, request_hash({"tool": tool, "arguments": arguments})
            )
            begun = True
            http = self.http_factory(self.store, execution_id, actor)
            adapter = TopvisorAdapter(
                self.config.user_id, self.config.api_key, http=http, coalescer=RequestOwnedFlight()
            )
            context_token = self.state.set(CallState(execution_id, actor, adapter))
            async with asyncio.timeout(OPERATION_TIMEOUT_SECONDS):
                result = await factory()
            self.store.finish(execution_id, "success")
            return self.clean(result)
        except asyncio.CancelledError:
            if begun:
                self.store.finish(execution_id, "cancelled")
            raise
        except Exception as exc:
            if begun:
                self.store.finish(execution_id, "error")
            if isinstance(exc, SafeToolError):
                raise
            if isinstance(exc, TimeoutError):
                exc = ProviderTimeoutError("operation deadline exceeded")
            raise safe_provider_error("topvisor", exc) from None
        finally:
            if context_token is not None:
                self.state.reset(context_token)

    async def read(
        self,
        provider: str,
        operation: str,
        arguments: Any,
        factory: Callable[[], Awaitable[T]],
        *,
        validate: Callable[[], Any] | None = None,
    ) -> T:
        try:
            if validate:
                validate()
            return self.clean(await factory())
        except (ProviderError, PermissionError, ValueError) as exc:
            self._cooldown(exc)
            raise safe_provider_error(provider, exc) from None

    def _cooldown(self, exc: Exception) -> None:
        if isinstance(exc, ProviderRateLimited) and not isinstance(exc, ProviderAdmissionDenied):
            self.store.cooldown(exc.retry_after_seconds or 60)

    async def write(
        self,
        provider: str,
        tool: str,
        arguments: dict[str, Any],
        idempotency_key: str | None,
        *,
        enabled: bool,
        validate: Callable[[], Any],
        apply_fn: Callable[[], Awaitable[Any]],
        readback_fn: Callable[[Any], Awaitable[Any]] | None = None,
    ) -> Any:
        try:
            if not enabled:
                raise ProviderError("Topvisor write runtime is not enabled")
            validate()
            digest = request_hash({"provider": provider, "tool": tool, "arguments": arguments})
            key = (idempotency_key.strip() if isinstance(idempotency_key, str) else "") or digest
            actor = self.state.get().actor
            cached = self.store.reserve_write(actor, key, tool, digest)
            if cached is not None:
                return cached
            # A timeout, failure or cancellation leaves pending durable state.
            # No blind retry of a possibly applied write, including after restart.
            result = await apply_fn()
            readback = await readback_fn(result) if readback_fn else None
            payload = self.clean(
                {
                    "applied": True,
                    "provider": provider,
                    "tool": tool,
                    "result": result,
                    "readback": readback,
                    "idempotency_key": key,
                }
            )
            self.store.settle_write(actor, key, payload)
            return payload
        except (ProviderError, PermissionError, ValueError) as exc:
            self._cooldown(exc)
            raise safe_provider_error(provider, exc) from None


class ToolRegistrar:
    def __init__(self, server: FastMCP, runtime: Runtime):
        self.server, self.runtime = server, runtime

    def tool(self, **options: Any) -> Callable[..., Any]:
        def decorate(function: Callable[..., Any]) -> Any:
            signature = inspect.signature(function)

            @wraps(function)
            async def wrapped(*args: Any, **kwargs: Any) -> Any:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                return await self.runtime.execute(
                    function.__name__, dict(bound.arguments), lambda: function(*args, **kwargs)
                )

            return self.server.tool(**options)(wrapped)

        return decorate


def create_server(
    config: ServiceConfig, *, transport: str = "http", http_factory: Callable[..., Any] | None = None
) -> FastMCP:
    if transport not in {"stdio", "http"}:
        raise ValueError("unsupported transport")
    if transport == "http" and not config.public_key:
        raise ValueError("HTTP requires an RSA public verification key")
    auth = (
        JWTVerifier(
            public_key=config.public_key, algorithm="RS256", issuer=config.issuer, audience=config.audience
        )
        if transport == "http"
        else None
    )
    server = FastMCP("Topvisor MCP", version=__version__, auth=auth, mask_error_details=True)
    runtime = Runtime(config, transport, http_factory)
    register_tools(ToolRegistrar(server, runtime), runtime)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone Topvisor MCP")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8812)
    parser.add_argument("--config", help="Operator JSON settings; paths relative to this file")
    parser.add_argument(
        "--check-config", action="store_true", help="Check local settings without provider calls"
    )
    args = parser.parse_args()
    try:
        load_config(args.config)
        config = ServiceConfig.from_env()
        if args.check_config:
            result = check_config(config, args.transport)
            print(json.dumps(result, sort_keys=True))
            parser.exit(0 if result["ready"] else 2)
        server = create_server(config, transport=args.transport)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"configuration error: {type(exc).__name__}; check credential and policy files\n")
    if args.transport == "http":
        server.run(
            transport="http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
            show_banner=False,
            log_level="warning",
        )
    else:
        server.run(transport="stdio", show_banner=False, log_level="warning")
