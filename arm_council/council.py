"""The 7-stage adversarial council — deterministic, as in the original.

Stage order: DISCOVERY -> (QUANT | INTELLIGENCE | RISK) -> RED_TEAM ->
DECISION -> RISK_GATE. Per-agent failures fail CLOSED (quant HOLD/0,
intel HOLD/50, risk REJECT/90). The claim graph is an audit artifact —
refutations are linked and statuses derived, but only the red team's
thesisStatus=='DISPROVED' (>=2 vulnerabilities) changes the outcome,
exactly as in the original.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from arm_council import config as ccfg, scoring


@dataclass
class Claim:
    id: str
    agent: str
    stage: str
    type: str            # BULLISH | BEARISH | RISK | REFUTATION | NEUTRAL
    statement: str
    confidence: float
    status: str = "UNSUPPORTED"   # SUPPORTED | CONTESTED | REFUTED | UNSUPPORTED
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradictory_evidence_ids: list[str] = field(default_factory=list)
    refuted_by_claim_id: str | None = None
    refutation_of: str | None = None


def derive_status(c: Claim) -> str:
    if c.refuted_by_claim_id:
        return "REFUTED"
    if c.contradictory_evidence_ids:
        return "CONTESTED"
    if not c.supporting_evidence_ids and c.type != "REFUTATION":
        return "UNSUPPORTED"
    return "SUPPORTED"


def link_refutations(claims: list[Claim]) -> list[Claim]:
    by_id = {c.id: c for c in claims}
    for c in claims:
        if c.type == "REFUTATION" and c.refutation_of in by_id:
            target = by_id[c.refutation_of]
            target.refuted_by_claim_id = c.id
            target.status = "REFUTED"
    for c in claims:
        if c.type != "REFUTATION" and c.status != "REFUTED":
            c.status = derive_status(c)
    return claims


def red_team(s: scoring.Snapshot, top10_holders_pct: float = 0.0,
             contradictions: int = 0) -> tuple[list[str], str]:
    """Their 4 fixed attacks. >=2 vulnerabilities => DISPROVED (the veto)."""
    vulns = []
    if top10_holders_pct > 60:
        vulns.append("concentration: top-10 holders exceed 60%")
    if s.liquidity_usd < 250_000:
        vulns.append(f"liquidity: ${s.liquidity_usd:,.0f} below $250k floor")
    if s.rsi14 > 75 and s.realized_vol > 50:
        vulns.append(f"exhaustion: RSI {s.rsi14:.0f} with realized vol {s.realized_vol:.0f}")
    if contradictions >= 1:
        vulns.append("intelligence produced contradictory evidence")
    status = "DISPROVED" if len(vulns) >= 2 else "WEAKENED" if len(vulns) == 1 else "INTACT"
    return vulns, status


def decide(s: scoring.Snapshot, evidence_count: int = 3,
           top10_holders_pct: float = 0.0, contradictions: int = 0) -> dict:
    """Full council run for one symbol. Deterministic end to end."""
    mfs, meta = scoring.multi_factor_score(s)
    opp = scoring.opportunity_score(s)
    risk = scoring.composite_risk(s)
    vulns, thesis_status = red_team(s, top10_holders_pct, contradictions)

    claims = [
        Claim(f"CLAIM-{s.symbol}-DSC-1", "discovery", "DISCOVERY", "BULLISH",
              f"{s.symbol} opportunity score {opp:.0f}", min(95.0, opp + 5),
              supporting_evidence_ids=["EV-MARKET", "EV-FLOW"]),
        Claim(f"CLAIM-{s.symbol}-QNT-1", "quant", "QUANT", "BULLISH",
              f"multi-factor {mfs:.0f}, est R:R {meta['rr']}", mfs,
              supporting_evidence_ids=["EV-MARKET"]),
        Claim(f"CLAIM-{s.symbol}-RSK-1", "risk", "RISK", "RISK",
              f"composite risk {risk:.0f}", 100 - risk,
              supporting_evidence_ids=["EV-RISK"]),
    ]
    for i, v in enumerate(vulns):
        claims.append(Claim(
            f"CLAIM-{s.symbol}-RT-{i+1}", "red_team", "RED_TEAM", "REFUTATION", v, 88.0,
            # Faithful quirk: ONLY the first vulnerability targets a claim.
            refutation_of=f"CLAIM-{s.symbol}-QNT-1" if i == 0 else None))
    claims = link_refutations(claims)

    # DECISION (agents/index.ts:343-355) — strict precedence, no voting.
    if thesis_status == "DISPROVED" or risk > 70:
        conclusion, confidence = "REJECT", max(88.0, 85.0)
    elif opp >= 65 and risk <= 45 and mfs >= ccfg.CANDIDATE_FLOOR:
        conclusion, confidence = "BUY", 86.0
    else:
        conclusion, confidence = "HOLD", 65.0

    # RISK_GATE (risk-gate/index.ts:41-98)
    violations = []
    if thesis_status == "DISPROVED":
        violations.append("red-team fatal flaw")
    if s.liquidity_usd < ccfg.GATE_MIN_LIQUIDITY:
        violations.append(f"liquidity ${s.liquidity_usd:,.0f} < ${ccfg.GATE_MIN_LIQUIDITY:,.0f}")
    if risk > ccfg.GATE_MAX_RISK_SCORE:
        violations.append(f"risk {risk} > {ccfg.GATE_MAX_RISK_SCORE}")
    if opp < ccfg.GATE_MIN_OPPORTUNITY:
        violations.append(f"opportunity {opp} < {ccfg.GATE_MIN_OPPORTUNITY}")
    if evidence_count < ccfg.GATE_MIN_EVIDENCE:
        violations.append(f"evidence {evidence_count} < {ccfg.GATE_MIN_EVIDENCE}")

    return {
        "symbol": s.symbol, "conclusion": conclusion, "confidence": confidence,
        "multi_factor": mfs, "opportunity": opp, "risk": risk,
        "regime": meta["regime"], "rr": meta["rr"],
        "thesis_status": thesis_status, "vulnerabilities": vulns,
        "gate_passed": not violations, "violations": violations,
        "claims": [asdict(c) for c in claims],
        "tradeable": conclusion == "BUY" and not violations,
    }


def size_position(equity: float, cash: float, gross_exposure: float, price: float,
                  confidence: float, opportunity: float, realized_vol: float) -> tuple[float, int, list[str]]:
    """sizing.ts:37-112 — volatility penalty x conviction factor, floored."""
    violations = []
    max_gross = equity * ccfg.MAX_PORTFOLIO_EXPOSURE_PCT / 100
    remaining = max(0.0, max_gross - gross_exposure)
    if remaining <= 0:
        violations.append("portfolio exposure cap reached")
    cap = min(ccfg.MAX_POSITION_SIZE_USD, equity * ccfg.MAX_CONCENTRATION_PCT / 100,
              cash, remaining)
    vol_penalty = scoring.clamp(30 / max(10.0, realized_vol), 0.5, 1.0)
    conviction = scoring.clamp(confidence / 100 * 0.6 + opportunity / 100 * 0.4, 0.5, 1.0)
    size_usd = min(cap * vol_penalty * conviction, cap)
    qty = int(size_usd // price) if price > 0 else 0
    if qty <= 0:
        violations.append("size below one share")
    return round(size_usd, 2), qty, violations


def exit_decision(pnl_pct: float, momentum: float, rsi: float,
                  liquidity_usd: float, risk_score: float) -> str | None:
    """monitoring/thesis.ts — any CRITICAL finding exits the full position."""
    if pnl_pct <= ccfg.EXIT_DRAWDOWN_PCT:
        return "price_drawdown"
    if momentum < ccfg.EXIT_MOMENTUM_MIN:
        return "momentum_reversal"
    if pnl_pct >= ccfg.EXIT_PROFIT_PCT and (
            momentum < ccfg.EXIT_MOMENTUM_EXHAUSTION or rsi > ccfg.EXIT_RSI_EXHAUSTION):
        return "profit_target_hit"
    if liquidity_usd < ccfg.EXIT_LIQUIDITY_MIN:
        return "liquidity_deterioration"
    if risk_score > ccfg.EXIT_RISK_MAX:
        return "risk_gate_violation"
    return None
