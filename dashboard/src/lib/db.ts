// Server-only — direct Postgres against the same Supabase project Agent
// Bazaar uses, isolated in its own `alpaca_hackathon` schema (see
// db.py for why this goes through Postgres directly
// rather than PostgREST: that schema isn't in the project's "exposed
// schemas" list, and this avoids needing that dashboard setting changed).
//
// This file must never be imported from a Client Component — the DB
// credentials live in server-only env vars, read only inside the
// `/api/state` Route Handler.
import { Pool } from 'pg';

let pool: Pool | null = null;

function getPool(): Pool {
  if (!pool) {
    pool = new Pool({
      host: process.env.SUPABASE_DB_HOST,
      port: Number(process.env.SUPABASE_DB_PORT || 5432),
      database: process.env.SUPABASE_DB_NAME || 'postgres',
      user: process.env.SUPABASE_DB_USER,
      password: process.env.SUPABASE_DB_PASSWORD,
      ssl: { rejectUnauthorized: false },
      max: 3,
    });
  }
  return pool;
}

const SCHEMA = process.env.SUPABASE_SCHEMA || 'alpaca_hackathon';

export interface AccountSnapshot {
  equity: number;
  last_equity: number | null;
  cash: number | null;
  open_spreads_count: number;
  daily_pl: number | null;
  daily_pl_pct: number | null;
  spy_price: number | null;
  snapshot_at: string;
}

export interface Spread {
  id: number;
  underlying: string;
  direction: string;
  expiration: string;
  short_strike: number;
  long_strike: number;
  contracts: number;
  credit_received: number;
  max_loss: number;
  status: string;
  realized_pnl: number | null;
  opened_at: string;
  closed_at: string | null;
}

export interface Cycle {
  id: number;
  ran_at: string;
  decision: string | null;
  reasoning: string | null;
  error: string | null;
}

export async function getDashboardState() {
  const client = await getPool().connect();
  try {
    const [snapshot, spreads, cycles] = await Promise.all([
      client.query<AccountSnapshot>(
        `select equity, last_equity, cash, open_spreads_count, daily_pl, daily_pl_pct, spy_price, snapshot_at
         from ${SCHEMA}.account_snapshots order by snapshot_at desc limit 1`
      ),
      client.query<Spread>(
        `select id, underlying, direction, expiration, short_strike, long_strike,
                contracts, credit_received, est_credit, fill_credit, max_loss, status, realized_pnl, opened_at, closed_at
         from ${SCHEMA}.spreads order by opened_at desc limit 50`
      ),
      client.query<Cycle>(
        `select id, ran_at, decision, reasoning, error
         from ${SCHEMA}.cycles order by ran_at desc limit 20`
      ),
      // Equity curve for the chart — every snapshot, not just the latest.
    ]);
    const curve = await client.query<Pick<AccountSnapshot, 'equity' | 'snapshot_at' | 'spy_price'>>(
      `select equity, spy_price, snapshot_at from ${SCHEMA}.account_snapshots order by snapshot_at asc`
    );

    // Live ablation: realized + unrealized shown separately for every policy.
    // LLM unrealized is estimated from open spreads using credit as a stand-in
    // mark proxy when no mark is stored (honestly labeled on the panel).
    const shadow = await client.query(
      `select policy,
              coalesce(sum(realized_pnl) filter (where status <> 'open'), 0) as realized,
              coalesce(sum((credit_received - unrealized_mark) * contracts)
                       filter (where status = 'open' and unrealized_mark is not null), 0) as unrealized,
              count(*) filter (where status = 'open') as open_count,
              count(*) filter (where status <> 'open') as closed_count
       from ${SCHEMA}.shadow_positions
       where policy in ('shadow', 'random')
       group by policy`
    );
    const llmBook = await client.query(
      `select coalesce(sum(realized_pnl) filter (where status like 'closed%'), 0) as realized,
              coalesce(sum(0) filter (where status in ('open', 'pending')), 0) as unrealized,
              count(*) filter (where status in ('open', 'pending')) as open_count,
              count(*) filter (where status like 'closed%') as closed_count
       from ${SCHEMA}.spreads`
    );

    // Experiment integrity metrics from cycles + decision journal.
    const cycleStats = await client.query(
      `select
         count(*) as n_cycles,
         count(*) filter (where decision in ('skipped', 'abstained', 'gate_blocked')) as n_abstain,
         count(*) filter (where decision = 'reconcile_block') as n_reconcile_block,
         count(*) filter (where decision = 'opened') as n_opened,
         count(*) filter (where error is not null) as n_error
       from ${SCHEMA}.cycles`
    );
    const journalStats = await client.query(
      `select
         count(*) as n_journals,
         count(*) filter (
           where jsonb_array_length(coalesce(gate_rejections, '[]'::jsonb)) > 0
         ) as n_with_gate_blocks,
         count(*) filter (
           where jsonb_array_length(coalesce(pre_trade_rejections, '[]'::jsonb)) > 0
         ) as n_with_pretrade_blocks,
         count(*) filter (
           where jsonb_array_length(coalesce(llm_selected, '[]'::jsonb)) = 0
             and jsonb_array_length(coalesce(candidates, '[]'::jsonb)) > 0
         ) as n_llm_abstain_with_menu
       from ${SCHEMA}.decision_journal`
    );
    const fillQuality = await client.query(
      `select
         count(*) filter (where fill_credit is not null) as n_with_fill,
         count(*) filter (
           where fill_credit is not null and credit_received is not null
             and credit_received <> 0
         ) as n_slippage_sample,
         avg(
           case when fill_credit is not null and credit_received is not null
                     and credit_received <> 0
                then (credit_received - fill_credit) / abs(credit_received)
                else null end
         ) as avg_credit_slippage_frac
       from ${SCHEMA}.spreads`
    );

    const cs = cycleStats.rows[0] ?? {};
    const js = journalStats.rows[0] ?? {};
    const fq = fillQuality.rows[0] ?? {};
    const nCycles = Number(cs.n_cycles ?? 0);
    const nJournals = Number(js.n_journals ?? 0);

    return {
      latestSnapshot: snapshot.rows[0] ?? null,
      spreads: spreads.rows,
      cycles: cycles.rows,
      equityCurve: curve.rows,
      ablation: {
        llm: llmBook.rows[0] ?? null,
        policies: shadow.rows,
        meta: {
          n_closed_llm: Number(llmBook.rows[0]?.closed_count ?? 0),
          n_cycles: nCycles,
          abstention_rate:
            nCycles > 0 ? Number(cs.n_abstain ?? 0) / nCycles : null,
          gate_block_rate:
            nJournals > 0 ? Number(js.n_with_gate_blocks ?? 0) / nJournals : null,
          pretrade_block_rate:
            nJournals > 0 ? Number(js.n_with_pretrade_blocks ?? 0) / nJournals : null,
          llm_abstain_with_menu: Number(js.n_llm_abstain_with_menu ?? 0),
          reconcile_blocks: Number(cs.n_reconcile_block ?? 0),
          avg_credit_slippage_pct:
            fq.avg_credit_slippage_frac != null
              ? Number(fq.avg_credit_slippage_frac) * 100
              : null,
          n_slippage_sample: Number(fq.n_slippage_sample ?? 0),
          valid_cycle_coverage_note:
            'Valid cycles = market-hours runs without reconcile_block/error; see decision journal for gate detail.',
          abstention_note:
            'Abstention includes skipped cycles and LLM empty picks on a non-empty menu.',
        },
      },
    };
  } finally {
    client.release();
  }
}

export async function getLabState() {
  const client = await getPool().connect();
  try {
    const [summary, trades] = await Promise.all([
      client.query(
        `select run_id, config, n_trades, total_pnl, win_rate, avg_pnl, max_drawdown, run_at
         from ${SCHEMA}.lab_summary order by id`
      ),
      client.query(
        `select run_id, config, symbol, direction, entry_date, exit_date, credit, pnl, exit_reason
         from ${SCHEMA}.lab_trades order by entry_date desc, id desc limit 500`
      ),
    ]);
    return { summary: summary.rows, trades: trades.rows };
  } finally {
    client.release();
  }
}

export async function getAuditState() {
  const client = await getPool().connect();
  try {
    const [journal, nightly] = await Promise.all([
      client.query(
        `select j.id, j.cycle_id, j.candidates, j.llm_selected, j.llm_reasoning,
                j.shadow_selected, j.gate_rejections, j.pre_trade_rejections, j.created_at,
                c.decision, c.error
         from ${SCHEMA}.decision_journal j
         left join ${SCHEMA}.cycles c on c.id = j.cycle_id
         order by j.id desc limit 60`
      ),
      client.query(
        `select session_date, verdict, summary, gate_tail, created_at
         from ${SCHEMA}.nightly_sessions order by id desc limit 14`
      ),
    ]);
    return { journal: journal.rows, nightly: nightly.rows };
  } finally {
    client.release();
  }
}
