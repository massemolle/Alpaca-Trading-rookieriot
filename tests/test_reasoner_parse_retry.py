"""The reasoner's parse/retry contract (nightly 2026-11-26).

A flaky generation used to forfeit the whole 30-minute decision window:
cycle 1090 (2026-11-25) abstained on a malformed-JSON reply, and three
cycles on 2026-11-13 abstained on nonzero `claude -p` exits. The fix is
one bounded retry of the GENERATION step plus a conservative parser that
tolerates prose around ONE valid JSON object but never repairs malformed
JSON. Abstention stays the terminal fallback — the chaos tests
(tests/chaos/test_chaos.py) still assert garbage in → abstention out.
"""
import json

import pytest

import llm_reasoner
from llm_reasoner import _parse_reasoner_text

VALID = '{"selected": [{"ticker": "SPY", "p_win": 0.7}], "reasoning": "because facts"}'

CANDS = [{"ticker": "SPY", "direction": "bull_put", "strength": 0.5,
          "credit_estimate": 100.0, "max_loss": 400.0, "expiration": "2026-12-11"}]


# --- parser: tolerant of wrapping, never of malformation --------------------

def test_parse_clean_json():
    parsed = _parse_reasoner_text(VALID)
    assert parsed["selected"][0]["ticker"] == "SPY"


def test_parse_code_fenced_json():
    parsed = _parse_reasoner_text(f"```json\n{VALID}\n```")
    assert parsed["reasoning"] == "because facts"


def test_parse_leading_prose_salvaged():
    parsed = _parse_reasoner_text(f"Here is my decision:\n{VALID}")
    assert parsed["selected"][0]["p_win"] == 0.7


def test_parse_trailing_prose_salvaged():
    parsed = _parse_reasoner_text(f"{VALID}\nLet me know if you need more.")
    assert parsed["reasoning"] == "because facts"


def test_parse_malformed_json_is_never_repaired():
    # The cycle-1090 class: broken inside the object (missing comma).
    broken = '{"selected": [{"ticker": "SPY" "p_win": 0.7}], "reasoning": "x"}'
    with pytest.raises(json.JSONDecodeError):
        _parse_reasoner_text(broken)


def test_parse_no_object_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_reasoner_text("I think you should definitely buy SPY!!")


def test_parse_wrong_schema_raises():
    with pytest.raises(AssertionError):
        _parse_reasoner_text('{"selected": "SPY", "reasoning": 42}')


def test_parse_non_object_json_raises():
    with pytest.raises(ValueError):
        _parse_reasoner_text('["SPY", "QQQ"]')


# --- retry: one fresh generation, then the existing abstention --------------

def _patch_claude_sequence(monkeypatch, stdouts):
    """Each call to subprocess.run pops the next stdout from the list."""
    import subprocess

    calls = {"n": 0}

    class R:
        def __init__(self, out):
            self.stdout = out
            self.stderr = ""
            self.returncode = 0

    def fake_run(*a, **k):
        out = stdouts[calls["n"]]
        calls["n"] += 1
        return R(out)

    monkeypatch.setattr(llm_reasoner, "REASONER_MODE", "claude_code")
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_retry_recovers_from_one_malformed_reply(monkeypatch):
    calls = _patch_claude_sequence(monkeypatch, ["{{{not json", VALID])
    out = llm_reasoner.decide(CANDS, remaining_budget=1)
    assert calls["n"] == 2
    assert [t["ticker"] for t in out["selected"]] == ["SPY"]


def test_two_failures_still_abstain(monkeypatch):
    calls = _patch_claude_sequence(monkeypatch, ["{{{not json", "also not json"])
    out = llm_reasoner.decide(CANDS, remaining_budget=1)
    assert calls["n"] == 2
    assert out["selected"] == []
    assert "failed" in out["reasoning"]


def test_single_success_does_not_retry(monkeypatch):
    calls = _patch_claude_sequence(monkeypatch, [VALID, "MUST NOT BE REACHED"])
    out = llm_reasoner.decide(CANDS, remaining_budget=1)
    assert calls["n"] == 1
    assert out["reasoning"] == "because facts"
