# Ranking changes and controlled checks

## Compare saved rankings

Ask your assistant:

> Use topvisor_rank_changes for project 123, region index 0, before_date 2026-09-01 and after_date 2026-09-08. Show which queries fell and group them by relevant URL. Export the same selection as CSV.

Find the region **index** in `topvisor_get_project_setup`; it is different from the geographical region key used when adding a region. The report reads existing history and never starts a paid check.

`topvisor_rank_changes` accepts one project, one region index, two ordered dates, `limit` (1–250), `offset` (0–100000), and `format` (`json` or `csv`). Positive `delta` means the numeric rank improved. Missing values and the provider's `--` marker remain unranked, never zero. URL totals cover the returned page, grouped by the later relevant URL, falling back to the earlier one. They are not totals for the whole project. `source` includes the request bounds, retrieval time, continuation offset when available and `provider_completeness: not_asserted`. Reading several pages is not an atomic snapshot. CSV escapes formula-leading text; it is still business data.

## Quote, confirm, launch

1. Call `topvisor_check_quote(project_id=123, region_indexes=[0])`. This reads a price; it does not launch a check. The quote lasts five minutes and belongs to the requesting account and client. This version supports projects owned by the configured Topvisor user. SERP snapshots are disabled for this operation.
2. Review the selected project, region indexes and `estimated_cost`. To launch, call `topvisor_check_launch(check_id="RETURNED_ID", approved_cost="RETURNED_COST", confirm_cost=true)` with read and write permissions. The operator must first enable the configuration below.
3. Inspect `topvisor_check_status(check_id="RETURNED_ID")`. A successful submission is `accepted`, not completed. Provider status is aggregate project state and may also reflect checks started elsewhere.

Merge these settings into your existing `mcp.local.json` `env` object, using your project ID and amounts in your Topvisor account's currency:

```json
{
  "TOPVISOR_WRITE_ENABLED": "true",
  "TOPVISOR_CHECK_PROJECTS": "123",
  "TOPVISOR_CHECK_MAX_COST": "1",
  "TOPVISOR_CHECK_DAILY_BUDGET": "5"
}
```

The daily budget is shared across clients of the configured account and resets at UTC midnight. The exact quote amount is checked again just before launch; a price change requires a new quote. Up to ten explicit region indexes are supported. Amounts have at most six decimal places. Defaults are zero and an empty project list, so paid launches are disabled.

These settings limit **quoted estimates**, not the provider's actual bill. Topvisor's price and launch endpoints are separate: changes to project contents, account settings or prices between requests can affect the charge. There is no atomic provider-enforced price cap in this workflow. Use a controlled project and account limits appropriate to your needs.

## After a launch or uncertain result

The quote is marked as dispatching and its estimate reserved before the paid request. A timeout, cancellation or unexpected acknowledgement leaves that reservation and a project fence in place. Reusing the same quote, issuing a new one or using another client cannot resubmit that project through this MCP while the fence is active. An accepted quote returns its stored receipt on replay without another request.

Check the outcome in Topvisor. For an unknown dispatch, wait at least two minutes after submission so an active request cannot be unlocked. Then run the local operator command, outside the MCP conversation:

```sh
topvisor-check-reconcile --config /absolute/path/mcp.local.json --check-id RETURNED_ID --outcome completed --confirm
```

For a source checkout, prefix it with `uv run --frozen`. Use `not_dispatched` only after establishing that the request was never accepted; this releases the estimated reservation. `completed` retains the reservation for that UTC day. Reconciliation removes the project fence and never contacts Topvisor. It is an operator assertion, not automatic verification. Do not clear the database or change account IDs to repeat an unknown operation. Existing keyword-management operations keep their earlier preview and replay behavior.

## Русский

### Сравнение позиций

`topvisor_rank_changes` читает сохранённые позиции одного проекта и одного индекса региона за две даты. Пример: проект 123, `region_index: 0`, `before_date: 2026-09-01`, `after_date: 2026-09-08`, `format: csv`. Индекс берётся из настроек проекта и отличается от географического кода региона.

Положительная разница означает улучшение позиции. Отсутствие значения и `--` не превращаются в ноль. Сводка по URL относится к текущей странице: сначала используется релевантный адрес второй даты, при его отсутствии — первой. Лимит — до 250 запросов за вызов; источник содержит offset, время чтения и следующий offset, если он доступен. Полнота всего проекта не утверждается. CSV остаётся коммерческими данными, несмотря на экранирование формул.

### Платная проверка

Получите `topvisor_check_quote` с проектом и явными индексами регионов. Оценка действует пять минут, принадлежит вашему клиенту и не запускает проверку. Поддерживаются собственные проекты настроенного пользователя Topvisor; снимки выдачи для этого запуска отключены.

После проверки стоимости вызовите `topvisor_check_launch` с `check_id`, точным `approved_cost` из оценки и `confirm_cost: true`. Нужны права чтения и записи, включённый `TOPVISOR_WRITE_ENABLED`, разрешённый проект и ненулевые лимиты `TOPVISOR_CHECK_MAX_COST` / `TOPVISOR_CHECK_DAILY_BUDGET` из примера выше. Суммы задаются в валюте вашего аккаунта; суточный лимит общий для клиентов и считается по UTC. Перед отправкой цена запрашивается повторно, изменение цены требует новой оценки.

Лимиты ограничивают оценку, а не фактический счёт провайдера: между запросами цены и запуска проект или тариф может измениться. В этом сценарии нет атомарного ограничения списания на стороне Topvisor.

`topvisor_check_status` показывает локальное подтверждение отправки и общее состояние проекта. Принятый запуск ещё не означает завершение, а состояние проекта не доказывает исход конкретного запроса. При неизвестном исходе повтор того же или нового запуска блокируется для всех клиентов этого проекта. После проверки в кабинете оператор снимает блокировку командой `topvisor-check-reconcile` из примера. `completed` сохраняет оценку в бюджете дня; `not_dispatched` освобождает её и допустим только при доказанном отсутствии отправки. Команда локальная, сама исход не проверяет.

Для неизвестного исхода команда сверки требует подождать не менее двух минут после отправки: запрос ещё мог выполняться. Это ожидание не заменяет проверку исхода в Topvisor.

## Provider references

[Saved history](https://topvisor.com/ru/api/positions-2/get-history/), [price estimate](https://topvisor.com/ru/api/positions-2/get-checker-price/), [launch acknowledgement](https://topvisor.com/ru/api/positions-2/edit-checker-go/). No live account was used to develop the fixtures.
