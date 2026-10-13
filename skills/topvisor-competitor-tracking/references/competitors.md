# Competitor tracking in Topvisor via MCP

- **Classic rankings:** add competitor domains in the Topvisor UI (project settings → competitors). The
  MCP reads your project's saved positions; competitor positions/SERP snapshots (`snapshots_2`) are not
  exposed by this server yet — compare in the UI or export.
- **AI tracker:** `topvisor_ai_tracker_settings` lists models and competitors; `topvisor_ai_tracker_summary`
  accepts `competitor_id` to read a competitor's mentions/visibility/sentiment for the same dates.
- **Proxy signal:** keywords where your relevant URL disappears or drops out of TOP-10 between two dates
  (`topvisor_rank_changes`) usually mark the queries a competitor took.
- Keyword-level competitor research (domains, overlaps, ads) is better done with keysso-mcp
  (skill `keysso-competitor-research`) if it is installed.
