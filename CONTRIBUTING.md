# Contributing to TOTF Analyzer

## Build & Test Commands

```bash
# Backend tests (isolate from parent agent PYTHONPATH/VIRTUAL_ENV)
env -u PYTHONPATH -u VIRTUAL_ENV .venv/bin/pytest

# Frontend TypeScript check & production bundle
cd web && npx tsc --noEmit && npm run build

# Run local API + UI server (serves web/dist at http://127.0.0.1:8000)
env -u PYTHONPATH -u VIRTUAL_ENV .venv/bin/totf-analyzer serve --host 127.0.0.1 --port 8000

# Run Streamable HTTP MCP server (http://127.0.0.1:8010/mcp)
env -u PYTHONPATH -u VIRTUAL_ENV .venv/bin/totf-analyzer mcp --host 127.0.0.1 --port 8010
```

## System Architecture

`totf-analyzer` parses Thrill of the Fight 2 (`T2SR` schema-15) session zip archives into deterministic, strictly factual combat telemetry, serving both a local React web dashboard and a Streamable HTTP MCP server.

- **`src/totf_analyzer/parser/`**: Low-level binary readers (`t2sr.py`, `session.py`) for `metadata.json`, `punches.bin`, `events.bin`, `punishment.bin`, `stiffness.bin`, `guard.bin`, and 21-joint `skeleton.bin` streams.
- **`src/totf_analyzer/models/`**: Pydantic v2 schemas (`analytics.py`) defining `FightAnalytics` and per-field confidence provenance (`confirmed`, `inferred`, `unavailable`).
- **`src/totf_analyzer/analytics/`**: Cross-stream biomechanics and striking computation (`metrics.py`) — bell-to-bell round windows, punch-to-scored-hit matching, trajectory classification, guard boxes, punch retraction, footwork/angle cuts, centerline head movement, combination chains, and vulnerability timing windows.
- **`src/totf_analyzer/api/`**: FastAPI HTTP server (`app.py`) serving `/api/sessions`, `/api/game-recordings`, `/api/sessions/import`, `/api/sessions/{name}/report`, and the compiled React SPA in `web/dist`.
- **`src/totf_analyzer/mcp_server/`**: Streamable HTTP MCP server (`server.py`) exposing compact summaries and drill-down tools (`list_recordings`, `analyze_recording`, `get_fighter_stats`, `get_punches`, `get_key_moments`, `get_series`).
- **`web/`**: React 19 + TypeScript + Vite + Tailwind CSS (`Apex Telemetry` design system from Stitch project `811732486051757994`) + Recharts dashboard. Reference Stitch HTML/PNG exports live in `docs/stitch/`.

## Separation of Concerns

1. **Parser vs. Analytics**: Binary framing and dequantization belong strictly in `parser/`. Coordinate-frame projections, thresholds, and aggregations belong in `analytics/metrics.py`.
2. **Measurements Only — Zero Coaching Opinions**: Neither the Python backend nor the React dashboard may invent coaching narratives, grades, or unmeasured physics quantities (such as simulated Newtons or cardio VO2 estimates). Every number rendered in `web/` must trace directly to `FightAnalytics`.
3. **Compact MCP vs. Full HTTP Report**: MCP tools omit bulky `series`, `punches`, and `key_moments` arrays by default to protect LLM context windows; the HTTP `/report` endpoint returns the complete `FightAnalytics` payload for instant client-side slicing in `web/`.

## Security Rules

- **Path Traversal Containment**: Session zip resolution in both `api/app.py` and `mcp_server/server.py` must validate `.zip` extensions, resolve symlinks, and enforce containment within `TOTF_RECORDINGS` / `TOTF_GAME_RECORDINGS` (`is_relative_to`).
- **Loopback Binding by Default**: Both `serve` (`127.0.0.1:8000`) and `mcp` (`127.0.0.1:8010`) bind to localhost unless explicitly overridden.
- **No Secrets in Source**: Never commit API keys, personal paths outside standard defaults, or raw player PII into git. `Recordings/` is gitignored.

## 10 Commandments for Future Developers

1. **Never fabricate metrics**: If a T2SR stream lacks a measurement (e.g., AI tracks without kinematic punch speed), surface `null` / `—` and record a `DecodeNote` with `confidence="unavailable"`.
2. **Respect bell-to-bell windows**: Fight-level footwork, guard percentages, and head-slip metrics must exclude pre-round warnings, inter-round breaks, and post-bell walks.
3. **Keep `decode_status` honest**: Every new derived metric must document its exact geometric or timing definition in `_static_notes()` and `README.md`.
4. **Preserve MCP payload budgets**: Default `analyze_recording` and `get_fighter_stats` payloads must remain under 80 KB on full 3-round bouts.
5. **Isolate Python environments**: Always run `.venv/bin/pytest` with `env -u PYTHONPATH -u VIRTUAL_ENV` when invoking from external agent shells.
6. **Type-check the frontend**: Every UI change in `web/src/` must pass `npx tsc --noEmit` and `npm run build` cleanly with strict TypeScript enabled.
7. **Synchronize TypeScript and Pydantic models**: Any field added to `src/totf_analyzer/models/analytics.py` must be reflected in `web/src/types.ts`.
8. **Test against real T2SR data and synthetic fixtures**: Maintain deterministic unit tests alongside real session regression checks in `tests/`.
9. **Keep visual hierarchy legible**: Follow the `Apex Telemetry` token palette (`Space Grotesk`, `Inter`, `JetBrains Mono`, Red `#ff5451` vs Cyan `#4cd7f6`) without cluttering views with decorative filler.
10. **Leave the repo buildable**: Never commit broken tests, half-wired UI controls, or stale `README.md` documentation.
