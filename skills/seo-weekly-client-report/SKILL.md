---
name: seo-weekly-client-report
description: Agency weekly SEO client report combining Topvisor rankings with optional Yandex Webmaster/Metrika, Roistat ROI and Keys.so visibility. Use for "еженедельный отчёт клиенту", "SEO report for client", "сводный отчёт".
license: LicenseRef-ZAI-ONE
compatibility: Requires topvisor-mcp. Optional - yandex-mcp, roistat-mcp, keysso-mcp (sections skipped if absent).
metadata:
  service: topvisor
  optional-mcps: yandex roistat keysso
---
# SEO weekly client report (cross-service)

Free reads only across all services. Output: [templates/client-report.md](templates/client-report.md).

## Steps
1. Ask/confirm client, site and period (default: last 7 days vs previous 7).
2. Rankings: run skill `topvisor-weekly-report` steps (see
   [references/report-template.md](references/report-template.md)); keep only the summary + 10 movers.
3. Detect connected MCPs by available tools (`yandex_*`, `roistat_*`, `keysso_*`). For each one present:
   - Yandex Webmaster: top queries impressions/clicks/CTR for both periods.
   - Yandex Metrika: organic visits and goals for both periods.
   - Roistat: analytics by channel, SEO/organic row — visits, leads, revenue, ROI.
   - Keys.so: domain visibility for the site and 2–3 competitors.
   Skip absent services; mark them "not connected".
4. Fill the template; every figure with source + dates. No paid calls (no rank checks, no paid
   Keys.so/Arsenkin jobs) unless the user explicitly asks.
5. End with 3 wins, 2 risks, next steps.
