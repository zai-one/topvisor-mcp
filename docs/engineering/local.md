# Project development guidance

- Python 3.12+; independent Topvisor adapter.
- Preserve scopes, dry-run defaults, paging, paid budgets, idempotency and readback.
- Checks: `uv run python scripts/verify.py`; `python scripts/check_engineering.py --check`. Run install checks before release.

Read only the task-relevant public documentation. Personal workspace notes are optional and remain outside Git.

- [README](../../README.md): supported features and installation.
- [Contributing](../../CONTRIBUTING.md): development and release checks.

Agent usage playbooks live in `skills/` and MCP `topvisor://playbook` / `topvisor://guide/{topic}`. Keep topic copies and installed resources consistent; run token-budget and clean-install checks before releases.
