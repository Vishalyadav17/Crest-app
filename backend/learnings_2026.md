# Learnings 2026

- Phase 0: PostgreSQL TEXT→JSON CAST requires `CASE WHEN col IS NULL THEN NULL ELSE col::json END` to be NULL-safe.
- Phase 1: DB-backed cache.py must create its own SessionLocal() per call since cache_get/set are called without a db arg.
- Phase 2: APScheduler `max_instances=1, coalesce=True` prevents job pile-up on slow market-data fetches.
- Scanner v2: compute RS inline over universe, not rs_universe.compute_universe (fixed N500 cache key pollutes/poisons).
- Phase 3: FastAPI TestClient triggers app lifespan; use real PostgreSQL + `patch("auth.is_auth_enabled")` — never SQLite for integration tests.
- Phase 4: asyncio.get_event_loop() in lifespan bridges scheduler threads to async WS broadcaster cleanly.
- Phase 5: Extract JS modules as plain <script> tags (not ES modules) to avoid import/export rewrites for 77+ cross-module calls.
- Phase 6: Starlette middleware is LIFO — add SessionMiddleware last so it runs first; RequestLoggingMiddleware can then read session.
- Phase 7: structlog wraps stdlib logging via ProcessorFormatter; all getLogger() calls emit JSON automatically.

## 2026-05-31 (Opus, autopilot setup)
- Run backend via backend/.venv/bin/python, NOT system python3 (missing structlog/fastapi).
- App needs Postgres up (DATABASE_URL postgresql://postgres:password@localhost:5432/crest); if down, startup hangs at alembic.autogenerate forever. backend/data/crest.db is stale/unused.
- Startup log buffers — looks stuck at alembic lines but actually finishes in ~10-15s. Use long curl --max-time on cold start.
- Dev auth bypass: config.json auth.enabled=false -> is_authenticated() True, get_current_user_id() returns user 1. No OAuth needed.
- Logout endpoint already exists: POST /auth/logout in auth.py (not /api prefix). Step 2 backend = done; only FE button needed.
- Settings module must be m8 (m7 taken by m7_charts_extra.js).
- User 1 dashboard renders blank: no portfolio_snapshots row -> /api/portfolio/overview + /api/dashboard/bootstrap 500. Data-state (Step 1), not a render bug.

## Overnight autopilot run 2026-05-31 — Morning report

### What shipped
- **STEP 2 (logout button):** `8284bbf` — Added `.logout-btn` in header (red hover, scale-on-active micro-state). Wired to `POST /auth/logout` via delegated `data-action="logout"` listener. Backend endpoint existed; only FE needed.
- **STEP 3 (settings module m6):**
  - `66d7ed3` — Backend: `backend/modules/settings/routes.py` with `GET /api/settings/profile`, `POST /api/settings/refresh-holdings`, `GET+PUT /api/settings/preferences`. Registered in `main.py`. Fixed `_DEFAULT_USER_ID = 2` in `deps.py` (actual DB user is id=2).
  - `d9ebe43` — Frontend: `m6_settings.js` + CSS in `components.css`. Left rail + content pane layout. 7 sub-tabs: Profile (email/name/tier/member-since/sign-out), Holdings (refresh snapshot button), Preferences (3 toggles: privacy/digests/auto-prune), Model Config / MF Tools / Backup / Connections (titled empty states). All tabs screenshot-verified. All API calls return 200.
- **Polish:** `9b59348` — Widened score mini-bar label (68→82px) to reduce truncation in health score card.

### Key decision: module ID
Memory said m7 was taken — verified filesystem showed only m1–m5. Next free ID is m6, not m8. Used m6.

### Key fix: default user ID
`deps.py` hardcoded `_DEFAULT_USER_ID = 1` but the actual seeded DB user had id=2. Fixed to 2 and added `allowed_email` to config.json so auto_seed creates the right user on restart. Dashboard then shows real data.

### Auth note
`config.json auth.enabled=false` — still disabled for dev. When you're ready to re-enable: set `"enabled": true` and ensure `allowed_email` matches your Google account.

### Tests
23/23 passed (test_phase3.py) — 1 pre-existing YESBANK failure is the only red in full suite. No new failures introduced.

### Commit log
```
47009b3  baseline before autopilot steps 2-3
8284bbf  step2: logout endpoint + header button
66d7ed3  step3: settings backend routes + fix dev default user id=2
d9ebe43  step3: settings module m6 — 7 sub-tabs
9b59348  polish m1: widen score mini-bar label
```

### Nothing blocked
All 5 commits clean. Auth re-enable deferred to user decision.

- Full `pytest -x -q` hangs ~indefinitely (live yfinance/network test contends w/ running :8000 app); run per-file instead.
- `alreadyHit` defined inside `if (cmp)` block but used outside: always hoist scope-shared vars before the conditional.
- Telegram long-polling via `getUpdates` in APScheduler job (IntervalTrigger 5s) works on localhost — no webhook/ngrok needed.
- Jinja2 digest templates: test without sending via `/api/settings/test-digest?kind=morning` (returns HTMLResponse).

## Second overnight autopilot run 2026-05-31 — Morning report

### What shipped
- **STEP 4 (Telegram bot + email digest):** `83f5dfb`
  - `backend/services/email_service.py` — SMTP_SSL send (Gmail), `render_morning_digest`, `render_eod_digest` via Jinja2
  - `backend/templates/email/morning_digest.html` + `eod_digest.html` — dark-themed HTML templates
  - `backend/services/telegram_service.py` — `send_telegram` (async), `send_telegram_sync` (APScheduler-safe), `generate_link_code`, `poll_telegram_updates` (getUpdates long-poll), link/unlink/status handlers
  - `backend/.env.example` — SMTP_USER, SMTP_PASS, TELEGRAM_BOT_TOKEN, MASTER_ENCRYPT_KEY
  - `backend/scheduler.py` — 4 new jobs: morning digest (7:30), EOD digest (16:30), telegram poll (5s), trade pruner (21:30); price-alert trigger now sends Telegram notification
  - `backend/modules/settings/routes.py` — `/api/settings/test-digest`, `/api/settings/telegram/link-code`, `/api/settings/telegram/unlink`, `/api/settings/telegram/status`
  - `frontend/js/ui/m6_settings.js` — Connections tab: real Telegram link UI with link-code box + deep link, unlink button

- **STEP 5 (trade pruner):** `594fc8f`
  - `backend/services/trade_pruner.py` — `prune_open_recommendations` checks SL-hit and sharp drop (≥5% day drop) on open ScanPicks; sets `scan_result = 'sl_hit'` or `'pruned_macro'`
  - `backend/main.py` — `POST /api/scheduler/run-now/prune` for manual testing
  - Frontend: PRUNED badge in scanner picks (muted grey) for pruned/sl-hit picks

- **STEP 6 (swing UX):** `19fa403`
  - `backend/alembic/versions/d4e5f6a1b2c3_step6_swing_ux.py` — adds `hold_long_term` (bool) to swing_trades, `promoted_to_trade_id` (int FK) to scan_picks
  - `backend/crud/swings.py` — `set_hold_long_term`, `promote_pick_to_trade` (copies ScanPick → SwingTrade)
  - `backend/modules/swing_detector/routes.py` — `PUT /api/swing/trades/{id}/hold-long-term`, `POST /api/swing/promote-to-trade`
  - `frontend/js/ui/m3_swings.js` — drag-and-drop scanner picks → My Swings, LT toggle button per row, CMP autofill (blur on symbol input), PRUNED badge, `[→ My Trades]` tag on promoted picks; `alreadyHit` hoisted out of `if (cmp)` block (scope bug fix)

### BLOCKED — needs your input
1. **SMTP_USER + SMTP_PASS** — add to `.env` to enable Gmail digest sends. Format: `SMTP_USER=you@gmail.com`, `SMTP_PASS=<16-char app password>`.
2. **TELEGRAM_BOT_TOKEN** — create a bot via @BotFather, paste token into `.env`. Then go to the Settings → Connections tab in Crest to link your chat.
3. **Auth re-enable** — still `config.json auth.enabled=false`. Flip to `true` when ready for production.

### Verify templates without sending
`curl http://127.0.0.1:8000/api/settings/test-digest?kind=morning` — renders the morning digest HTML in the browser.

### Commit log
```
83f5dfb  step4: telegram bot + email digest (graceful no-op when creds absent)
594fc8f  step5: trade pruner (SL + sharp-drop), Telegram alert on price trigger
19fa403  step6: hold-long-term toggle, drag-to-MyTrades, CMP autofill, PRUNED badge, alreadyHit scope fix
```

### Tests
23/23 passed (test_phase3.py). 1 pre-existing YESBANK failure, no new failures.

- Step 7: SQLAlchemy COUNT queries in same function make win_rate accurate even on status-filtered paginated fetch.

## 2026-06-01 QA morning report

### Surfaces QA'd
shell · onboarding · m1-vault · m2-market-pulse · m3-alpha-scanner (scanner + my-trades + scan-vault tabs) · m4-wavesight · m5-watchlist (Lists panel + Info panel) · m6-settings (all 7 sub-tabs: profile, holdings, preferences, model-config, mf-tools, backup, connections)
Login: **DEFERRED** — only served when auth.enabled=true; not reachable in dev bypass mode.

### Gate findings applied (4 CSS-only changes, commit `7dc222e`)
1. `base.css` — `.account-id-avatar` `var(--fs-14)` → `14px` (token doesn't exist in theme.css scale)
2. `components.css` — `.v1-score-mini-label` 82→94px; "Risk Management" overflowed 6px, "Growth Potential" 9px; both zero overflow after fix (confirmed via DOM scrollWidth)
3. `components.css` — `.v1-score-mini-fill` + `transition:width var(--t-slow) var(--ease-out)` (bars now animate in on load)
4. `ui.css` — `.ui-table tbody tr:hover` + `border-left-color:rgba(177,197,255,0.2)` (Emil directional affordance on scanner/trades rows)

### Screenshots taken — states covered
All saved to `growpilot/screenshots/` (gitignored).

| Surface | States |
|---|---|
| Shell | loaded (nav, avatar, account menu visible) |
| Onboarding | step-1 plan-select loaded |
| Login | DEFERRED |
| M1 Vault | loaded (viewport + full-page, pre-fix + post-fix) |
| M2 Market Pulse | loading skeleton → populated (signal, sector heatmap, gainers/losers, breadth, news) |
| M3 Alpha Scanner | Scanner tab loaded · My Trades loaded · Scan Vault empty ("No scans for this period") |
| M4 Wavesight | chart loaded (RELIANCE.NS daily) |
| M5 Watchlist (Lists panel) | populated (Datacentre group, 2 items) · empty group (QA-Test-Empty, no items — test list created + deleted) |
| M5 Info panel | loaded (RELIANCE live price, 52W range, market cap, watchlist add-row, News) |
| M6 Settings — Profile | loaded |
| M6 Settings — Holdings | loaded |
| M6 Settings — Preferences | loaded (3 toggles) |
| M6 Settings — Model Config | empty state (icon + description, Step 10 badge) |
| M6 Settings — MF Tools | empty state (Step 5 badge) |
| M6 Settings — Backup | empty state (Step 9 badge) |
| M6 Settings — Connections | empty state (Telegram link UI, Step 10 badge) |

Error states: not triggerable without breaking API calls (no state/data changes permitted). Console errors: **0** across entire session.

### Commits
```
7dc222e  qa-pass: gate1+gate2 CSS fixes + fold stray learnings
23de82d  gitignore: exclude screenshots/ qa artifacts
9272c95  learnings: add proper QA morning report (was missing, only raw lines existed)
```

### Stray file cleanup
- `growpilot/learnings_2026.md` (4 CSS learnings at wrong path) → folded below, file deleted
- `grow/learnings_2026.md` (root of repo, untracked) → deleted

### Blocked / deferred
- Login surface: auth.enabled=false → `/login.html` never served in dev. Defer until OAuth re-enabled.
- M5 initial miss: `switchModule('m5')` threw JS error → incorrectly concluded m5 had no surface. Fixed: m5 is the Lists + Info right-panel inside M4; both states now screenshotted.
- Empty/error states initial miss: only loaded states captured first pass. Fixed: sub-tabs and empty states added in second pass.
- News timestamps "9131d ago": JS date-formatter bug. Deferred — JS change, outside pure-restyle constraint.

## CSS learnings (revamp, folded from stray root learnings_2026.md — 2026-06-01)
- `transition:all` on buttons causes layout reflows; always list specific properties.
- CSS specificity: module-level `td` selectors override global `td` mono rule — must re-declare explicitly.
- `border-radius:14px/12px/10px/6px` → token map: r-xl/r-lg/r-md/r-sm; sed batch-replace saves time.
- `@starting-style` replaces JS-mounted opacity tricks for card entry animations in modern browsers.

## 2026-06-01 QA pass — frontend revamp gate evidence
- shell: shots OK, impeccable=2 applied (--fs-14 undefined token→14px; dead reduced-motion entries noted), emil=account menu spring/exit asymmetry, sidebar cubic-bezier verified ✓
- login: DEFERRED — only served when auth.enabled=true; not reachable in dev bypass mode
- onboarding: shots OK, impeccable=0, emil=Continue button scale-press verified ✓
- m1-vault: shots OK, impeccable=2 applied (v1-score-mini-label 82→94px fixes Risk Management+Growth Potential overflow; v1-score-mini-fill transition added), emil=score bar fill animate-on-load tuned ✓
- m2-market-pulse: shots OK, impeccable=0 (pulse-dot animation ✓, signal banner border-left ✓), emil=signal dot spring pulse verified ✓; note: news timestamps "9131d ago" = date-calc data bug, deferred per no-state-change constraint
- m3-alpha-scanner: shots OK (scanner/my-trades/scan-vault tabs all), impeccable=0, emil=ui-table tbody tr:hover now flashes left-border blue tell (rgba 0.2) for directional affordance ✓
- m4-wavesight: shots OK, impeccable=0, emil=lc-layout-btn + lc-tool-btn hover transitions verified (120ms ease-out) ✓
- m6-settings: shots OK (profile+preferences sub-tabs), impeccable=0, emil=toggle spring thumb verified ✓, rail tab border-left transition verified ✓

- WS0: YESBANK fixture rotted (rallied near 52W high); replaced stage4[0] with TITAN (37/100, stable).
- send_telegram_sync: asyncio.get_event_loop() breaks in to_thread workers; use get_running_loop+asyncio.run fallback.
- yfinance group_by='ticker': access raw[ticker]['Close'], not raw['Close'][ticker].

- Kite MCP live tool discovery: POST /mcp initialize→grab mcp-session-id header→notifications/initialized→tools/list (no creds; SSE data: lines).
- Kite MCP = mcp.kite.trade/mcp streamable-HTTP, auth via login-tool OAuth (session-bound), 22 tools; we use read-only.
- LLM router: cryptography v48 is already in .venv — no re-install needed despite plan saying 42.0.8.
- Free-first routing: Groq hits on first try with Llama 3.3-70B; guardrails catch pro/non-free models before dispatch.
- Fernet token is self-contained (IV+ciphertext+HMAC); one ciphertext column, no separate nonce.
- Kite persistence: positions come as {net:[],day:[]} — flatten both arrays for sync_positions.
- PIECE 4 FE: embed AI verdicts in vault serializer (object_session) — single fetch, no N+1.
- uvicorn --reload reloads Python only; static JS stays browser-cached — hard reload (ignoreCache) to test FE.
- BYOK + Kite settings FE: provider allowlist hardcoded in m6 (_M6_PROVIDERS); add_credential ValueError on bad provider.
- Key test endpoint called chat() with no task/model → ValueError every time; now direct provider call.
- Free model ids rot fast: OpenRouter deepseek-r1:free/minimax gone, Cerebras only gpt-oss-120b/zai-glm-4.7. Query /models live.
- Groq decommissioned deepseek-r1-distill/qwen-qwq/gemma2; use qwen/qwen3-32b + openai/gpt-oss-120b. Key-test errors must clamp in UI (title tooltip).
- Daily scan moved to 21:00 IST (id=daily_scan), pref gate removed (always runs); manual /run-dry now 403; Mistral provider fully removed.
- Kite MCP login tool returns text blob (warning+markdown link), not dict/url. start_login must regex-extract kite.zerodha.com/connect/login URL.
- Kite equity = source of truth: sync_holdings upserts by (user_id,sym), not append (was double-counting manual+kite). MF aggregates across sources. Snapshot refresh on any kite /tool|/connect.
- Two trade models: scanner=ScanOutcome(crud/scan), manual=SwingTrade(crud/swings). Unifying onto SwingTrade. kite_reconcile.py auto-creates/updates/closes scanner trades from kite holdings+positions; manual untouched.
- ETF rule: BEES in symbol = ETF. recompute counts ETFs in equity_value/wealth but excludes from sector/mcap alloc; scanner skips BEES; alpha already excludes is_etf.
- My Trades consolidated onto SwingTrade single source (one table + scanner/manual dropdown). loadMySwings now aliases loadMyTrades. reconcile dedups by active sym. win_rate excludes trade_type=manual. ScanOutcome scanner-render fns now dead.
- Portfolio overview rewritten: per-bucket (stocks/gold/etf/mf) computed direct from holdings, NOT subtraction (old mf_inv=total-stocks leaked ETF cost into MF). asset_bucket(): GOLD/SILVER=gold, BEES/ETF/IETF=etf, else stock. Cards = value + invested + pnl% sub.
- Holding classification: pref holding_track_map {sym:long_term|swing|manual}. reconcile returns unclassified (kite stock, not etf/gold, not tracked). FE popup after refresh -> POST /api/portfolio/classify. Indian Equity page = /api/portfolio/long-term. swing/manual also create SwingTrade.
- Scanner v2 tradeability_flags lost on DB read (no ScanPick col); recover in _run_to_dict from audit_json.gate.flags. IPO picks can dup main scan — FE dedupes table by ipo symbols.
- Nightly basket automation: Sun 12pm establish (scanner_v2) + daily 21:00 track; net_guard skips if offline. Telegram HTML: escape < > & or 400.
- Adaptive entry band: price>=pivot*0.97 → breakout band [pivot*0.99,*1.03]; else tight pullback [CMP-4%, CMP+1%] capped under pivot.
- Mobile Telegram WRAPS <pre> (no horizontal scroll) → wide tables break. Fix: render PNG table via Pillow (Menlo/Helvetica, macOS fonts), send as photo (send_telegram image_path) + short caption. services/scan_image.py.
- WS1: N+1 fix via load_ltp_map(syms) batching; alembic revision IDs must be unique vs existing.
- WS2: patch target must be the importing module namespace, not the source module, for top-level imports.
ws3: SW version from max mtime; stale SW cache causes duplicate-let SyntaxError — version-bust first.
- WS4: US price key = "US:{sym}", crypto key = "CRYPTO:{coingecko_id}"; fx fallback 84.0 when fx job hasn't run.
- WS5: MF NAV job used h.fund_key (doesn't exist) — fixed to h.name; scheme_code = exact AMFI code match, no fuzzy needed.
- WS8: Breakout score v2 max ≈90 (not 100); depth_penalty ×0.6 reduces further; np.random in test fixtures needs fixed seed for determinism.
- WS12: NSE announcements API works without session warmup (home 403 OK); value in attchmntText only for some companies (others PDF-only).
- WS9: LightweightCharts rejects CSS var() colors — use literal hex; sec-modal-overlay not modal-overlay for fixed positioning.
- WS9 verify: 45 seeded indices, all history computed; inline compute on create fires in background thread successfully.
- WS9 UI invisible: asset-version meta hardcoded "2", not mtime-derived — bump it after any frontend change or cache-first serves stale JS.
- WS9 members 500: PriceSnapshot column is day_change_pct, not change_pct; uvicorn runs without --reload so restart to apply edits.
- WS9b: index renders as weighted OHLC candles; recompute_all() hooked after bhavcopy ingest so scans feed indices.
- WS9c news: Google News RSS ranks by relevance not date — add when:30d + sort pubDate desc.
- WS9c: indices panel rendered blank on Wavesight load; initCharts must fetch it, not only the toggle.
- WS9d toolbar: designed via Open Design MCP (project wavesight-toolbar); translated to wt-* namespaced classes, kept our ids/handlers. setChartsCount selector must match new .wt-seg not .lc-layout-btn.
- WS10: get_current_user_id must be called directly (request, db) — wrapping in Depends causes FastAPI session-type validation error.
- WS11: casparser 1.1.0 (latest); upsert_cas_holdings deletes only source='cas' rows to preserve kite/manual holdings.
- WS6: /login.html needs a registered route — unauthenticated GET / serves login.html but /login.html redirect lands 404 without it.
- WS7: test FERNET_KEY must be set before any import triggering crypto module; set os.environ before sys.path.insert.
- WS7 audit: all yf.download in route handlers wrapped in asyncio.to_thread; portfolio_snapshots row populated; alembic head clean; localStorage non-ephemeral uses remain in m4 (gp_charts_state, gp_indicators) — acceptable for single-user app.

## Architecture audit results (2026-06-13, WS7)
1. pytest (13 files serially) — ✅ all pass.
2. alembic upgrade head — ✅ clean (no pending migrations).
3. /api/dashboard/bootstrap response — ✅ served from snapshots (no upstream call in response path).
4. Browser nav — manual; no console errors confirmed in WS0/WS3/WS6 QA sessions.
5. Server restart freshness — ✅ snapshots persist in Postgres; first load still reads from DB.
6. Offline fallback — manual; SW caches shell; data from last-good snapshot.
7. portfolio_snapshots — ✅ user_id=2 row has total_wealth, equity_value, computed_at all populated.
8. localStorage non-ephemeral — ⚠️ gp_charts_state + gp_indicators + gp_watchlists still in LS (m4/m5); acceptable for single-user; not derived financial data.
9. yf.download in async handlers — ✅ all calls wrapped in asyncio.to_thread or in sync helper functions; no event-loop blocking.
10. price_alert_triggered test — manual; Notification inserted within 30s of alert condition (verified in WS1 manual run).
- Kite reconcile: count t1_quantity, normalize -BE series, evidence-based close, guard empty-holdings against mass false-close.
- FE-rework: SW stale-JS root cause = install addAll(SHELL) precaches via HTTP cache; fix = fetch each shell with cache:'reload'.
- Weekend Lab had ZERO wl-* CSS (text dump); designed via Open Design (proj crest-weekend-lab), ported wl-* classes, 2-pane rail+detail+drawer.
- ScanPick.grade = "HIGH CONVICTION"/"QUALIFIES" labels not letters; render as keyword pill not fixed square.
- MF: kite sync stores pnl=0 → recompute on read in crud.mf; FE showed short(ISIN) → use name; mfapi dates DD-MM-YYYY need ISO for range queries.
- LLM router _parse_sse returned only FIRST SSE chunk → every streamed reply truncated; fix = concat all delta/message chunks.
- gemini-2.5-flash thinking tokens count vs max_tokens; market_note needed 800 (200 starved output mid-sentence).
- Scanner = rolling weekly basket (1 run/Sunday-week); nightly track now merges fresh scan, dedupes by symbol, top_n survive, losers scan_result='CHURNED'.
- recheck_basket only ran on latest basket → old vault picks stuck null; added services/breach_sweep (OHLC _detect_close) on vault/{id} + /trades load.
- Portfolio sector=Unknown/mcap=all-Small: equity_holdings.sector/mcap_bucket null (Kite import); enrich from stock_master (strip -BE/-BZ) + derive bucket from mcap_cr.
- US FX stuck ₹84: fx_usdinr cache only filled by daily job; added services/fx.get_fx_rate live-fetch on cache miss.
- Vault funcs (openVaultDetail/_onVaultMonthChange) live in m1_portfolio.js not m3_*; scan-vault header now folder-driven (computed in openVaultDetail).
- breach_sweep set scan_result but NOT tracking_json.strength_status → FE grouped SL-hit picks as enterable; FE grouping must key on scan_result first.
- breach_sweep on /vault/{id}+/trades did yfinance per-open = stuck "Loading"; moved to nightly sweep_user_open_runs; backfill+nightly only.
- is_ipo_pick = IPO sub-scan bucket origin; added scan_picks.is_ipo = underlying recent-IPO (BELRISE is_ipo true but qualified via normal scan). Backfill from stock_master.is_ipo.
- Vault month selector defaulted to current month → hid older (May) folders; added "All scans" default option.
- deep_dive fallback only switched tier on NoFreeCapacity; generic errors returned None w/o system retry. Now falls through tiers on ANY error.
- Vault stuck-Loading real cause = m1_portfolio.js review.themes.map on object-shaped themes_json (weekend review); breach-sweep perf was secondary. Browser test caught it.
- Scanner now MONTHLY basket (_month_key, establish day=1/1st run, daily churn); sizing ₹1L 5%/10%(composite≥90); levels 12%/5.5%; protected picks (traded/held) never churn; weak+stale alerts edge-triggered across all runs; Kite reconcile syncs ScanOutcome + resurrects churned held picks.
- ScanReview is per-(run,kind): batch=auto, weekend=weekend. Kind-agnostic .first() clobbers weekend review — always filter kind.
- Verdict accuracy: closed-pick verdicts must reconcile w/ outcome (winner/failure kinds outrank validation in ai_map); best/worst computed from real return, not LLM guess on equal scores.
- Market note went stale (server down)+invented "NIFTY down" from empty breadth snapshot. Gate generation on real breadth+indices; stale badge on FE.
- LLM providers: gpt-oss-120b & cerebras zai-glm-4.7 reason heavily → empty/truncated JSON on tight budgets. Lead JSON tasks w/ llama-3.3/qwen-instruct/gemini; router now drops empty-200 + falls through.
- Free pools wired: Cerebras (gpt-oss-120b, zai-glm-4.7), NVIDIA NIM (121 models incl kimi-k2.6/qwen3.5-122b/llama-3.3 — free, no cost in usage). OpenRouter free now has nemotron-3-super-120b/qwen-80b (no kimi/deepseek/glm free on this key).
- Postgres can't DISTINCT a query selecting JSON columns ("no equality operator for type json") → select distinct IDs then load.
- notebooklm skill is shell-invokable: python ~/.claude/skills/notebooklm/scripts/run.py ask_question.py --notebook-url ... → backend can connector-bridge to it.
