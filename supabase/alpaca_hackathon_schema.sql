-- alpaca_hackathon schema — RECONSTRUCTED 2026-08-28 from db.py's queries and
-- the live /api/state payload (the original file referenced by db.py's
-- docstring was never pushed). Alex: diff this against your local version.
--
-- decision_journal is ALSO auto-created by db.py (_ensure_decision_journal_table);
-- included here for completeness with the identical definition.
-- The call_* / strategy columns on spreads are nullable forward-compat columns
-- observed in the live deployment's iron-condor rows (not yet written by the
-- pushed db.py).

CREATE SCHEMA IF NOT EXISTS alpaca_hackathon;

CREATE TABLE IF NOT EXISTS alpaca_hackathon.cycles (
    id          SERIAL PRIMARY KEY,
    candidates  JSONB,
    decision    TEXT,
    reasoning   TEXT,
    error       TEXT,
    ran_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alpaca_hackathon.spreads (
    id                SERIAL PRIMARY KEY,
    underlying        TEXT NOT NULL,
    direction         TEXT NOT NULL,
    expiration        DATE,
    short_strike      NUMERIC,
    long_strike       NUMERIC,
    short_symbol      TEXT,
    long_symbol       TEXT,
    contracts         INTEGER,
    credit_received   NUMERIC,
    max_loss          NUMERIC,
    alpaca_order_ids  JSONB,
    cycle_id          INTEGER REFERENCES alpaca_hackathon.cycles(id),
    status            TEXT NOT NULL DEFAULT 'open',
    realized_pnl      NUMERIC,
    opened_at         TIMESTAMPTZ DEFAULT now(),
    closed_at         TIMESTAMPTZ,
    -- forward-compat (iron condor support seen in the live deployment)
    strategy          TEXT,
    call_short_strike NUMERIC,
    call_long_strike  NUMERIC,
    call_short_symbol TEXT,
    call_long_symbol  TEXT
);

CREATE TABLE IF NOT EXISTS alpaca_hackathon.account_snapshots (
    id                  SERIAL PRIMARY KEY,
    equity              NUMERIC NOT NULL,
    last_equity         NUMERIC,
    cash                NUMERIC,
    open_spreads_count  INTEGER,
    daily_pl            NUMERIC,
    daily_pl_pct        NUMERIC,
    snapshot_at         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alpaca_hackathon.decision_journal (
    id                   SERIAL PRIMARY KEY,
    cycle_id             INTEGER REFERENCES alpaca_hackathon.cycles(id),
    candidates           JSONB,
    llm_selected         JSONB,
    llm_reasoning        TEXT,
    shadow_selected      JSONB,
    gate_rejections      JSONB,
    pre_trade_rejections JSONB,
    created_at           TIMESTAMPTZ DEFAULT now()
);
