# Topvisor MCP maintenance

This independent repository owns the Topvisor adapter and MCP tools.
Follow the workspace task protocol when under ZAI. Use Python scripts and
offline fixtures; never call live Topvisor or execute paid checks in tests.
Preserve scopes, dry-run defaults, idempotency and readback when wiring runtime.
Extraction is incomplete until the original tool contracts and standalone
stdio/HTTP lifecycle are verified.

Use Python for scripts. Preserve existing MCP names/schemas and server-owned
authorization, account boundaries, budgets, approvals and unknown-outcome state.
Do not use live provider accounts or credentials in tests. Keep setup local and explicit.
Run scripts/verify.py and scripts/verify_install.py before releases.
Use Issues for requested changes. Preserve LICENSE, NOTICE and third-party licenses.
Never publish operational handoffs, private extraction refs, credentials or runtime state.
Production deployment is a separate action.
When operating in a workspace with a task/verifier protocol, follow that protocol.
