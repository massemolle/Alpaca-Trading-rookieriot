"""Rhetoric audit — shared by BOTH sleeves (adapted from Autobelay's citations.py
idea, MIT, re-implemented): beyond checking that cited fact-ids EXIST
(the credit bot's check), verify (a) the VALUES the model quotes next to a
citation match the fact it was handed, and (b) the ACTION aligns with the
model's own stated probability. Violations downgrade the pick to abstention
and are journaled — a judge that misquotes its evidence doesn't trade."""
from __future__ import annotations

import re


# A citation group is a run of slash-separated numbers followed by a run of
# fact tags — adjacent brackets ("$85.5/$414.5 [X_CREDIT_EST][X_MAX_LOSS]")
# or a comma list in one bracket ("$10/$490 [X_CREDIT_EST, X_MAX_LOSS]").
# Pairing nearest-number-to-each-tag mis-read these (c449 2026-10-05: the
# correct quote 85.5/414.5 was flagged because 414.5 sat nearest the first
# tag) — numbers and tags pair POSITIONALLY within a group.
_NUM = r"-?\$?\d+(?:,\d{3})*(?:\.\d+)?"
_TAG = r"[A-Z][A-Z0-9_]*"
_CITE_GROUP = re.compile(
    rf"({_NUM}(?:\s*/\s*{_NUM})*)\s*%?\s*"
    rf"((?:\[{_TAG}(?:\s*,\s*{_TAG})*\])+)"
)
_TAG_RE = re.compile(_TAG)


def audit_values(candidates: list[dict], reasoning: str, tolerance: float = 0.05) -> list[str]:
    """Find `number(s) [FACT_ID...]` citation groups; flag quotes deviating
    >tolerance (relative) from the supplied fact value."""
    facts = {}
    for c in candidates:
        for f in c.get("facts", []):
            facts[f["fact_id"]] = f.get("value")
    flags = []

    def close(quoted: float, actual: float) -> bool:
        return abs(quoted - actual) / max(abs(actual), 1e-9) <= tolerance

    for m in _CITE_GROUP.finditer(reasoning):
        nums = [float(n.replace("$", "").replace(",", ""))
                for n in re.split(r"\s*/\s*", m.group(1))]
        tags = _TAG_RE.findall(m.group(2))
        known = {}
        for fid in tags:
            if fid not in facts:
                flags.append(f"cites unknown fact [{fid}]")
                continue
            try:
                known[fid] = float(facts[fid])
            except (TypeError, ValueError):
                pass  # non-numeric fact — nothing to compare
        if len(nums) == len(tags):
            for quoted, fid in zip(nums, tags):
                if fid in known and not close(quoted, known[fid]):
                    flags.append(f"misquotes [{fid}]: says {quoted}, fact is {known[fid]}")
        elif len(nums) == 1 and known:
            # One number against several tags ("$479.5 [X_CREDIT, X_MAX_LOSS]"):
            # the writer means one of them — flag only if it matches none.
            if not any(close(nums[0], v) for v in known.values()):
                flags.append(
                    f"misquotes [{', '.join(tags)}]: says {nums[0]}, facts are "
                    + ", ".join(str(known[t]) for t in tags if t in known)
                )
        # Other count mismatches: pairing is ambiguous — skip the value check
        # rather than guess (unknown-tag flags above still apply).
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
