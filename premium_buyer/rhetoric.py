"""Rhetoric audit — NEW ADDITION #1 (adapted from Autobelay's citations.py
idea, MIT, re-implemented): beyond checking that cited fact-ids EXIST
(the credit bot's check), verify (a) the VALUES the model quotes next to a
citation match the fact it was handed, and (b) the ACTION aligns with the
model's own stated probability. Violations downgrade the pick to abstention
and are journaled — a judge that misquotes its evidence doesn't trade."""
from __future__ import annotations

import re


def audit_values(candidates: list[dict], reasoning: str, tolerance: float = 0.05) -> list[str]:
    """Find `number [FACT_ID]` patterns; flag quotes deviating >tolerance
    (relative) from the supplied fact value."""
    facts = {}
    for c in candidates:
        for f in c.get("facts", []):
            facts[f["fact_id"]] = f.get("value")
    flags = []
    for m in re.finditer(r"(-?\$?\d+(?:\.\d+)?)\s*%?\s*\[([A-Z0-9_]+)\]", reasoning):
        quoted = float(m.group(1).replace("$", ""))
        fid = m.group(2)
        actual = facts.get(fid)
        if actual is None:
            flags.append(f"cites unknown fact [{fid}]")
            continue
        try:
            actual_f = float(actual)
        except (TypeError, ValueError):
            continue
        denom = max(abs(actual_f), 1e-9)
        if abs(quoted - actual_f) / denom > tolerance:
            flags.append(f"misquotes [{fid}]: says {quoted}, fact is {actual_f}")
    return flags


def audit_alignment(selected: list[dict], min_p: float) -> list[str]:
    """A pick whose own stated probability is below the bar contradicts
    itself — the model is trading against its stated belief."""
    flags = []
    for s in selected:
        p = s.get("p_move")
        if p is None:
            flags.append(f"{s.get('ticker')}: no stated probability")
        elif p < min_p:
            flags.append(f"{s.get('ticker')}: selected with stated p={p} < {min_p} — action contradicts belief")
    return flags
