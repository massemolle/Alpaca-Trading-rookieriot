"""The original's ONE optional model call (agent/decision.ts:283-344),
re-implemented faithfully — including its most important property:

    THE RATCHET. Only HOLD/PASS replies are honored. A model reply of BUY
    can never create or elevate a trade; the deterministic council decides
    what may be bought, and the model may only veto it. Any parse error,
    timeout or exception keeps the deterministic action.

Their prompt schema is reproduced; the provider is ours (headless Claude
rather than Featherless/Qwen), since that is the model this project runs.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an institutional trading council synthesis model. Analyze the "
    "provided market evidence and quantitative scores.\n"
    "Respond ONLY with a valid JSON object matching this schema:\n"
    '{ "decision": "BUY"|"HOLD"|"PASS", "confidence": number (0-100), '
    '"thesis": string, "invalidation": string, "risks": string[], '
    '"reasoningSummary": string }'
)


def enabled() -> bool:
    return os.environ.get("COUNCIL_LLM_REVIEW", "true").lower() == "true"


def review(decision: dict, snapshot) -> dict:
    """Returns {action, confidence, thesis, reasoning, downgraded}.
    Called ONLY when the deterministic council already said BUY."""
    out = {"action": "BUY", "confidence": decision["confidence"],
           "thesis": "", "reasoning": "", "downgraded": False}
    if not enabled():
        return out
    payload = {
        "symbol": snapshot.symbol, "price": snapshot.price,
        "change24h": snapshot.change24h, "rsi14": snapshot.rsi14,
        "rvol": snapshot.rvol, "regime": decision["regime"],
        "multiFactorScore": decision["multi_factor"],
        "estimatedRR": decision["rr"],
        "quantSummary": f"opportunity {decision['opportunity']}, risk {decision['risk']}",
        "redTeamFindings": decision["vulnerabilities"],
    }
    prompt = SYSTEM_PROMPT + "\n\n" + json.dumps(payload, default=str)
    cmd = ["claude", "-p", prompt, "--output-format", "text"]
    model = os.environ.get("REASONER_CLAUDE_MODEL")
    if model:
        cmd += ["--model", model]
    try:
        with tempfile.TemporaryDirectory() as scratch:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=scratch)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip()[:160])
        text = res.stdout.strip()
        if text.startswith("```"):
            text = text.strip("`\n")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        reply = str(parsed.get("decision", "")).upper()
        conf = float(parsed.get("confidence", decision["confidence"]))
        # THE RATCHET: BUY replies are ignored; only vetoes are honored.
        if reply in ("HOLD", "PASS"):
            out["action"] = reply
            out["downgraded"] = True
        out["confidence"] = round((decision["confidence"] + conf) / 2)
        out["thesis"] = str(parsed.get("thesis", ""))[:500]
        out["reasoning"] = str(parsed.get("reasoningSummary", ""))[:500]
    except Exception as exc:
        logger.warning("council LLM review unavailable (%s) — keeping deterministic action", exc)
    return out
