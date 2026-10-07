# AI Flow only: pause Market One, simplify to one channel

## What we're improving
nikita paused Market One (@market_one_news) on 2026-10-07 to focus on AI Flow
(@ai_flow_daily). Both channels ran from one codebase with a multi-channel layer
(`channels/<name>/profile.py`, prefixed settings, a PIPELINE registry, a dashboard
switcher). That layer, and Market One's own code, got in the way of AI Flow. The goal:
one simple single-channel project, renamed **aif-channel**, with Market One saved so an
AI coding agent can bring it back. Previous AI Flow specs are in docs/.

## Contract
GOAL: AI Flow runs from `/home/nikita/systems/aif-channel` as `aif-channel` and
`aif-dashboard-api`, posting exactly as before. History is kept, and the dashboard shows
only AI Flow. Market One can be restored from the tag `market-one-final` and
`archive/market-one/`.

CONSTRAINTS:
- No change to anything AI Flow sends a model: prompts, models, schemas, settings, limits.
- Same SQLite database (moved, not rebuilt), same Redis group, same Vercel project.
- Minimal files and folders; plain LangGraph wiring per the LangGraph skill.
- nikita renames the GitHub repo to `aif-channel` himself.

FORMAT: `main.py`, `config.py`, `schema.sql`, `prompts/`, `pipeline/` (graph.py and
stations.py), `nodes/`, `utils/`, `dashboard/`, `deploy/`, `tools/`, `tests/`, `docs/`,
`archive/market-one/`. The dashboard API token lives only in `.env`.

FAILURE (any of these = not done):
1. AI Flow stops posting, loses history, or re-posts old items after the move.
2. Any model request differs from before (fingerprint of all 13 stations on a frozen DB).
3. Market One can't be rebuilt from the tag plus the archive.
4. Market One code, settings or switcher left outside the archive, or anything still
   pointing at `/home/nikita/systems/news-channels`.
5. The leaked dashboard token still works, or a secret is committed.
6. The dashboard doesn't build, or shows the wrong channel.

## Built on top of
- LangGraph `StateGraph` with explicit `add_edge` / `add_conditional_edges`
  (langgraph-fundamentals skill); compiled once at import.
- Verification harness (in the session scratchpad, not the repo): fake OpenRouter
  transport recording every request, deterministic fake embeddings, frozen DB copy;
  plus a dashboard API snapshot and the compiled graph's node/edge list.

## Gotchas we're handling
- A rename breaks absolute paths: systemd units, the dashboard venv (scripts hard-code
  their path, so it is rebuilt), logrotate, the yt-dlp cron line, the log file name.
- `.env` keys lost their `AI_` / `AI_NEWS_` prefixes; values are unchanged.
- The live DB keeps unused calendar columns and table from Market One; harmless,
  and schema.sql no longer creates them.
- Comments after an empty value in `.env` become the value; the example avoids that.
- Prompts that mention markets in their examples (story placement, the repeat check)
  are AI Flow's real prompts and stay word for word.

## Build sequence
1. Stop and disable Market One; tag `market-one-final`. ✓
2. Baselines on the old code: request fingerprint, graph shape, dashboard API, tests. ✓
3. Archive Market One (prompts, settings, models, graph, schema, deploy, restore notes). ✓
4. Single-channel config, prompts/, pipeline/, no calendar; compare fingerprint. ✓
5. Dashboard backend and frontend for one channel; compare API output; build. ✓
6. Deploy files, README, SPEC; rotate the dashboard token. ✓
7. Cutover: stop old service, move DB and archive data, install new units, verify live.

## How to run and test
- `/usr/bin/python3 tests/test_ai_channel.py` (34), `tests/test_media.py` (23),
  `/usr/bin/python3 -m unittest tests/test_reader_memory.py` (28)
- `python3 main.py check`, `python3 tools/rehearse.py --limit 3` (real models, sends nothing)
- `cd dashboard/frontend && npx tsc --noEmit && npm run build`

## Status
_Updated: 2026-10-07_
- Steps 1-6 done and verified: all 14 recorded model requests are identical to the old
  code, the graph has the same 13 nodes and 20 edges, the dashboard API returns the same
  data for 8 endpoints, the tests pass at the old counts, the website builds clean, and a
  rehearsal ran three real items through the whole graph with real models.
- Intended differences: `MARKETS` setting renamed `SORTER_AXIS_VALUES`; the sorter's cap
  reason reads "nobody can use it today"; error alerts say "AI Flow"; log names
  `aif-channel.*`; the dashboard no longer accepts `?channel=`.
- The new dashboard token is in `.env`; the Vercel `DASHBOARD_TOKEN` must be updated to
  match, or the dashboard shows "API offline".
