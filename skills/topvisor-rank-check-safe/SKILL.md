---
name: topvisor-rank-check-safe
description: Safely run a paid Topvisor rank check - balance, price quote, explicit user approval, single launch, status polling, reconcile. Use for "обнови позиции", "запусти съём позиций", "fresh rank check".
license: LicenseRef-ZAI-ONE
compatibility: Requires topvisor-mcp with TOPVISOR_CHECK_PROJECTS / budgets configured by the operator.
metadata:
  service: topvisor
---
# Safe paid rank check

Money is spent only in step 4. Read [references/pricing.md](references/pricing.md) first.

## Steps
1. Resolve `project_id` and region indexes (`topvisor_list_projects`, `topvisor_get_project_setup`).
2. `topvisor_balance` → note `balance_all`.
3. `topvisor_check_quote(project_id, regions)` → show the user: price, regions, quote expiry (5 min),
   balance after. If balance < price, stop and say so.
4. Only after an explicit "yes/да" for that price: `topvisor_check_launch` with the quote. One call.
5. Poll `topvisor_check_status` (every 1–2 min, max ~15 min); report progress briefly.
6. When done → continue with skill `topvisor-weekly-report` or `topvisor_rank_changes`.

## Guardrails
- Quote expired or arguments changed → new quote and new approval.
- Outcome `unknown` → never relaunch; tell the user to run `topvisor-check-reconcile` or check the UI.
- Budget refusal from the server is final; do not split the check to bypass it.
- Errors: [references/errors.md](references/errors.md).
