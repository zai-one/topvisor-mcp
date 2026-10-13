# Topvisor money rules

- Reads (projects, keywords, saved positions, AI tracker, balance, quotes) are free API calls.
- A rank check (`topvisor_check_launch`) spends account balance. The amount depends on keyword count,
  engines, regions and depth, so **only `topvisor_check_quote` is a valid price**; never estimate from memory.
- Quotes live 5 minutes and are bound to project + regions. Launch only the quote the user approved.
- Operator budgets (per project / per estimate) are enforced server-side; a launch over budget is refused.
- Before quoting, read `topvisor_balance` and warn when `balance_all` < quote.
- A launch whose outcome is `unknown` may have been charged: do not relaunch; reconcile first.
- Official API reference: https://topvisor.com/api/v2/ (bank_2/info, positions_2/checker).
