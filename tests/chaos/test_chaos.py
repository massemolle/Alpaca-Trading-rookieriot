"""Chaos tests — PREMORTEM items as executable checks (PLAN D17 PR6).

Each test injects a specific failure and asserts the system degrades the
safe way: refuse/abstain/raise-loudly, never trade on garbage. All offline.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

import executor_mcp
import llm_reasoner
from spread_builder import _mid_from_snapshot
from tests.conftest import FakeClient, FakeMCP, make_plan, snapshot


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# --- executor: broker responses that lie -----------------------------------

def test_error_shaped_success_raises():
    """PREMORTEM: Alpaca can reject inside a 200-shaped payload — treating it
    as success once created a phantom DB position. Must raise."""
    with pytest.raises(RuntimeError, match="rejected"):
        executor_mcp._extract_order_ids({"data": {"error": {"message": "outside market hours", "http_status": 422}}})


def test_malformed_order_result_raises():
    with pytest.raises(RuntimeError, match="Could not extract"):
        executor_mcp._extract_order_ids({"data": {"unexpected": "shape"}})


def test_dry_run_never_places_orders(monkeypatch):
    monkeypatch.setattr(executor_mcp, "config", dataclasses.replace(executor_mcp.config, dry_run=True))

    class MustNotBeCalledMCP:
        async def call(self, tool, arguments):
            raise AssertionError(f"DRY_RUN must not reach MCP, got {tool}")

    result = run(executor_mcp.open_spread(MustNotBeCalledMCP(), make_plan(), contracts=2))
    assert result.status == "dry_run"
    assert result.order_ids[0].startswith("dryrun-")
    result = run(executor_mcp.close_spread(MustNotBeCalledMCP(), "S", "L", 2))
    assert result.status == "dry_run"
    assert result.order_ids[0].startswith("dryrun-")


# --- reasoner: garbage in, abstention out ----------------------------------

def _patch_claude(monkeypatch, stdout="", returncode=0, exc=None):
    import subprocess

    class R:
        def __init__(self):
            self.stdout = stdout
            self.stderr = "boom"
            self.returncode = returncode

    def fake_run(*a, **k):
        if exc:
            raise exc
        return R()

    monkeypatch.setattr(llm_reasoner, "REASONER_MODE", "claude_code")
    monkeypatch.setattr(subprocess, "run", fake_run)


CANDS = [{"ticker": "SPY", "direction": "bull_put", "strength": 0.5,
          "credit_estimate": 100.0, "max_loss": 400.0, "expiration": "2026-09-11"}]


def test_reasoner_garbage_output_abstains(monkeypatch):
    _patch_claude(monkeypatch, stdout="I think you should definitely buy SPY!!")
    out = llm_reasoner.decide(CANDS, remaining_budget=1)
    assert out["selected"] == []
    assert "failed" in out["reasoning"]


def test_reasoner_nonzero_exit_abstains(monkeypatch):
    _patch_claude(monkeypatch, returncode=1)
    out = llm_reasoner.decide(CANDS, remaining_budget=1)
    assert out["selected"] == []


def test_reasoner_timeout_abstains(monkeypatch):
    import subprocess
    _patch_claude(monkeypatch, exc=subprocess.TimeoutExpired(cmd="claude", timeout=180))
    out = llm_reasoner.decide(CANDS, remaining_budget=1)
    assert out["selected"] == []


def test_reasoner_wrong_schema_abstains(monkeypatch):
    _patch_claude(monkeypatch, stdout='{"selected": "SPY", "reasoning": 42}')
    out = llm_reasoner.decide(CANDS, remaining_budget=1)
    assert out["selected"] == []


# --- market data: quotes that aren't there ---------------------------------

def test_mid_from_snapshot_handles_missing_pieces():
    assert _mid_from_snapshot({}) is None
    assert _mid_from_snapshot({"latestQuote": {}}) is None
    assert _mid_from_snapshot({"latestQuote": {"bp": 1.0, "ap": None}}) is None
    assert _mid_from_snapshot(snapshot(1.0, 2.0)) == 1.5
