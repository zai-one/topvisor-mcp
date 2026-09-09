# Topvisor MCP

Independent Topvisor MCP with the original six read tools and eleven typed or
legacy write tools. The adapter and tool functions are owned by this repository;
their committed extraction sources are recorded in `SOURCE_PROVENANCE.json`.
The frozen original MCP schemas are in `contracts/topvisor.json`.

## Standalone installation

Requires Python 3.12–3.14. Run `uv sync --frozen --all-groups` from a checkout,
or install the built `zai-topvisor-mcp` wheel with its locked dependencies.
No AI Kit or `mcp_platform` installation or ZAI-specific filesystem is required.

Export `TOPVISOR_USER_ID` and `TOPVISOR_API_KEY_FILE`, pointing to an owner-private
credential file. `uv run topvisor-mcp` starts stdio for the local OS operator.
State defaults to `state/topvisor.sqlite`; use a persistent private directory.
The stdio process must not be turned into an unauthenticated network bridge.

`uv run topvisor-mcp --transport http` binds `127.0.0.1:8812/mcp`. HTTP additionally
requires `TOPVISOR_MCP_PUBLIC_KEY_FILE`. The trusted issuer's RS256 bearer token
must match `TOPVISOR_MCP_ISSUER` and `TOPVISOR_MCP_AUDIENCE`, with a nonempty `sub`,
valid `exp`, `account_id` matching `TOPVISOR_ACCOUNT_ID`, and `topvisor:read`
and/or `topvisor:write` scopes. Use TLS for connections beyond the local host.
The example variable file is `.env.example`; the CLI does not load it implicitly.

## Writes, limits and state

Typed writes default to dry-run. Actual writes also need
`TOPVISOR_WRITE_ENABLED=true`. Delete and paid checker execution remain excluded.
Each allowed write is validated, reserved in a persistent idempotency ledger,
executed without blind retries, and followed by the original bounded readback.
An omitted idempotency key derives from the operation and canonical JSON request hash.
An explicitly reused key must have identical arguments and the same actor/account.

After success, repeats return the stored result. Interrupted, failed or unconfirmed
writes stay `pending` across restarts and are not resubmitted automatically.
Reconcile their actual provider outcome before deciding how to proceed; changing
the key alone is not proof that repeating a write is safe. Pending metadata can
be inspected with `SELECT account, actor, idempotency_key, tool, status FROM writes`
in the local state database. There is no automatic pending-write reset command.

Every HTTP attempt, including read retries and readback, passes the durable
account and principal limits. Defaults: 20 attempts/minute per account and
principal, two concurrent calls. Upstream cooldown survives restart. A call
deadline cancels owned upstream work before releasing its lease. API keys are
removed from responses and errors; audit records contain hashes and metadata.

All processes serving one provider account must share one local SQLite file on
one host. Multi-host replicas with separate ledgers are not supported. Back up
the state together with release metadata; do not erase pending writes on rollback.

## Embedding in a gateway

The package exports `zai_topvisor.adapter.TopvisorAdapter` and
`zai_topvisor.tools.register_tools(server, runtime)`. Registration accepts a
runtime providing `topvisor()`, `require_scopes`, `read`, `write`, `safe_error`
and `topvisor_write_enabled`. This lets the gateway keep its own authentication,
audit, quotas and write ledger while using the very same adapter and tool code.
The standalone SQLite runtime is not invoked in this embedding mode.

Install an exact wheel/version and verify its SHA-256 before installation.
The platform integration contains only compatibility types and policy binding;
it must not copy or maintain a second Topvisor implementation.

## Verification and release

`uv run python scripts/verify.py` runs lint and offline tests. `uv build` produces
wheel and sdist; the Dockerfile builds a non-root HTTP service. Tests use local
fixtures and synthetic credentials, with no live Topvisor requests.

The usage license is [LicenseRef-ZAI-ONE](../LICENSE). Live account validation is an operator step.
