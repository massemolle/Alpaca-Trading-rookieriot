# Pre-mortem — "It's Sep 4 and we failed. What happened?"

Each imagined failure must map to a guard (code) or a test. Update as guards land.
Status: ☐ open ☑ guarded

| # | Imagined failure | Guard / test | Status |
|---|---|---|---|
| 1 | Agent traded on a phantom position it had already closed | Broker re-fetch every cycle; reconciler worker; TradeTrap chaos test | ☑ |
| 2 | Multi-leg orders never worked through our MCP client; found out Tuesday | Spike (REST) + day-1 MCP-client test; cut criterion D11 → simplify structures | ☐ |
| 3 | A timed-out submit was blindly retried → double position | Idempotent client order IDs; query-before-retry; order state machine | ☐ |
| 4 | Stale indicative quotes priced candidates; fills were nowhere near | Quote-age + feed-quality fields gate eligibility; staleness chaos test | ☑ |
| 5 | Short leg assigned early over a weekend/ex-dividend; portfolio inverted | Assignment/exercise polling; no short calls over ex-dividend; lifecycle checks | ☐ |
| 6 | Position expired ITM on deadline day mid-session | Forced-liquidation deadline before Sep 4 15:00 UTC; no same-day expiries | ☐ |
| 7 | Prompt injection in a news article steered the selector | Structural content isolation; claims extraction; injection chaos tests; news never touches risk config | ☐ |
| 8 | LLM "improved" the strategy nightly and overfit to 3 trades | Reflector limited to process errors; fixed risk budgets | ☑ |
| 9 | Token spend blew up; pipeline silently stopped mid-week | Cost measured at spike; tiered cadence; budget alarm in monitor | ☐ |
| 10 | Greeks said safe; overnight gap blew through the local approximation | Scenario grid (D9) worst-loss recorded per candidate; sizing off worst-case | ☐ |
| 11 | Dashboard showed demo data, not real decisions, at judging | Cut criterion D11: dashboard reads persisted decisions by Tue 1 or loses features | ☑ |
| 12 | Fresh-account rule misread; submission invalid | Capture exact rule quotes from Discord; account plan in PLAN.md D5 | ☐ |
| 13 | One malformed API response crashed the scheduler for hours unattended | Chaos tests; workers restart-safe; kill switch on corrupted state; alerting | ☑ |
| 14 | Collar legs (stock + option, non-atomic) left half-open on a failure | Leg-imbalance detection in reconciler; prefer atomic mleg structures | ☐ |