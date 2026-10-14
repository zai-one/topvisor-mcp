# Topvisor errors

| Situation | What to do |
|---|---|
| `provider_error` with retryable hint | wait and retry once |
| rate limited / cooldown | wait for the stated cooldown; do not loop |
| validation error (dates, IDs, limits) | fix arguments; dates are YYYY-MM-DD, ≤31 dates, ≤10 regions |
| write disabled | operator must enable writes (TOPVISOR_WRITE_ENABLED); tell the user |
| quote expired | request a new `topvisor_check_quote`, re-confirm price |
| launch outcome unknown | never relaunch; run `topvisor-check-reconcile` / check UI |
| missing scope | token lacks `topvisor:read`/`topvisor:write` |
