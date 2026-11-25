#!/usr/bin/env python3
"""
Agent 08: /forex-risk
Deterministic Institutional Risk Gatekeeper.
Enforces 8 strict rules including Anti-Stacking (Max 1 Trade Per Pair),
MTF Confluence Minimum Score, News Blackout, Spread Filter, and Drawdown Caps.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    STATE_DIR,
    load_config,
    load_stage_output,
    save_stage_output,
)
from forex_core.mt5_bridge import read_mt5_state


def _clean_symbol(sym: str) -> str:
    from forex_core.mt5_bridge import clean_pair_name
    return clean_pair_name(sym)


def _load_active_positions(offline: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    from forex_core.market_data import now_bdt
    today_str = now_bdt().strftime("%Y-%m-%d")
    ledger_path = STATE_DIR / "paper_ledger.json"
    if not ledger_path.exists():
        ledger = {"date": today_str, "daily_realized_loss_usd": 0.0, "trades_today": 0, "open_positions": []}
    else:
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                ledger = json.load(f)
        except Exception:
            ledger = {"date": today_str, "daily_realized_loss_usd": 0.0, "trades_today": 0, "open_positions": []}

    if ledger.get("date") != today_str:
        ledger["date"] = today_str
        ledger["daily_realized_loss_usd"] = 0.0
        ledger["daily_realized_profit_usd"] = 0.0
        ledger["trades_today"] = 0

    if not offline:
        mt5_live = read_mt5_state()
        if mt5_live is not None and mt5_live.get("open_positions") is not None:
            return ledger, mt5_live["open_positions"]
    return ledger, ledger.get("open_positions", [])


def evaluate_risk(
    simulate_spread_spike: float | None = None,
    simulate_daily_loss: float | None = None,
    ignore_pair_stacking: bool = False,
) -> Dict[str, Any]:
    cfg = load_config()
    scanner_state = load_stage_output("scanner") or {}
    calendar_state = load_stage_output("calendar") or {}
    entry_state = load_stage_output("entry") or {}
    exit_state = load_stage_output("exit") or {}
    tm_state = load_stage_output("timemachine") or {}
    budget_state = load_stage_output("budget") or {}
    top = scanner_state.get("top_pick", {})
    mt5_active = read_mt5_state() is not None
    is_offline = (top.get("data_source") == "simulated_market") and not mt5_active
    ledger, open_positions = _load_active_positions(offline=is_offline)
    pair = _clean_symbol(exit_state.get("pair") or top.get("pair") or "EURUSD")
    direction = (exit_state.get("direction") or top.get("direction") or "BUY").upper()
    setup_score = int(top.get("score", 80))
    min_score = int(cfg.get("min_setup_score", 78))

    spread_pips = float(
        simulate_spread_spike
        if simulate_spread_spike is not None
        else top.get("spread_pips", 1.2)
    )
    max_spread = float(cfg.get("max_spread_pips", 2.5))

    blackout_active = bool(calendar_state.get("blackout_active", False))
    actual_risk_usd = float(budget_state.get("actual_risk_usd", 50.0))
    max_loss_trade = float(cfg.get("max_loss_per_trade_usd", 100.0))

    mt5_state = read_mt5_state()
    if simulate_daily_loss is not None:
        daily_loss_so_far = float(simulate_daily_loss)
    elif mt5_state and "daily_realized_loss_usd" in mt5_state:
        daily_loss_so_far = float(mt5_state.get("daily_realized_loss_usd", 0.0))
    else:
        daily_loss_so_far = float(ledger.get("daily_realized_loss_usd", 0.0))

    # Read account-specific daily loss limit if in prop firm mode (e.g. 4% = $200 on $5k)
    max_daily_loss = float(cfg.get("max_daily_loss_usd", 400.0))
    for acc in cfg.get("accounts", []):
        if acc.get("enabled", False) and acc.get("prop_firm_mode", False):
            acc_bal = float(acc.get("balance_usd", 5000.0))
            acc_max_dd_pct = float(acc.get("max_daily_loss_pct", 4.0))
            max_daily_loss = min(max_daily_loss, acc_bal * (acc_max_dd_pct / 100.0))
            break

    open_count = len(open_positions)
    max_open = int(cfg.get("max_open_trades", 5))
    max_per_pair = int(cfg.get("max_trades_per_pair", 1))

    same_pair_open = sum(1 for p in open_positions if _clean_symbol(p.get("pair", "")) == pair)
    pair_stack_ok = ignore_pair_stacking or (same_pair_open < max_per_pair)

    rr = float(exit_state.get("reward_to_risk", 2.0))
    min_rr = float(cfg.get("min_reward_to_risk", 1.5))

    tm_passed = bool(tm_state.get("passed", True))
    entry_ready = bool(entry_state.get("entry_ready", True))

    checks: List[Dict[str, Any]] = [
        {
            "rule": "1. Anti-Stacking Guard (1 Trade/Pair)",
            "passed": pair_stack_ok,
            "detail": (
                f"{pair} has 0 active trades (Max {max_per_pair}/pair)"
                if pair_stack_ok
                else f"BLOCKED: {pair} already has {same_pair_open} open trade(s)"
            ),
        },
        {
            "rule": "2. MTF Confluence Quality Gate",
            "passed": setup_score >= min_score,
            "detail": f"Confluence Score {setup_score}/100 >= {min_score} min (Grade {top.get('grade', 'A')})",
        },
        {
            "rule": "3. Red-Folder News Blackout",
            "passed": not blackout_active,
            "detail": "Clear of high-impact news window" if not blackout_active else "BLOCKED: Within +-30m of High-Impact News",
        },
        {
            "rule": "4. Broker Spread Filter",
            "passed": spread_pips <= max_spread,
            "detail": f"Spread {spread_pips}p <= {max_spread}p max",
        },
        {
            "rule": "5. Per-Trade Risk Limit",
            "passed": actual_risk_usd <= max_loss_trade,
            "detail": f"Risk ${actual_risk_usd:.2f} <= ${max_loss_trade:.2f} max ({budget_state.get('progression_mode', '1R')})",
        },
        {
            "rule": "6. Daily Drawdown Circuit Breaker",
            "passed": (daily_loss_so_far + actual_risk_usd) <= max_daily_loss,
            "detail": f"Daily loss ${daily_loss_so_far:.2f} + ${actual_risk_usd:.2f} <= ${max_daily_loss:.2f} limit",
        },
        {
            "rule": "7. Portfolio Exposure Limit",
            "passed": open_count < max_open,
            "detail": f"Active portfolio positions: {open_count}/{max_open} max",
        },
        {
            "rule": "8. R:R & TimeMachine Expectancy",
            "passed": rr >= min_rr and tm_passed and entry_ready,
            "detail": f"R:R {rr} >= {min_rr}, TimeMachine={tm_state.get('verdict', 'POSITIVE_EDGE')}",
        },
    ]

    failed_rules = [c for c in checks if not c["passed"]]
    decision = "PASS" if len(failed_rules) == 0 else "BLOCK"

    output = {
        "pair": pair,
        "direction": direction,
        "decision": decision,
        "passed": decision == "PASS",
        "failed_count": len(failed_rules),
        "checks": checks,
        "blocking_reasons": [c["detail"] for c in failed_rules],
    }
    save_stage_output("risk", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="08 /forex-risk - Institutional Risk Gatekeeper (PASS / BLOCK)")
    parser.add_argument("--simulate-spread", type=float, default=-1.0, help="Simulate spread spike in pips")
    parser.add_argument("--simulate-daily-loss", type=float, default=-1.0, help="Simulate existing daily loss in USD")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    res = evaluate_risk(
        simulate_spread_spike=args.simulate_spread if args.simulate_spread > 0 else None,
        simulate_daily_loss=args.simulate_daily_loss if args.simulate_daily_loss >= 0 else None,
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [08 /forex-risk] Risk Gatekeeper Verdict: [{res['decision']}] ({res['pair']} {res['direction']}) ===")
    for c in res["checks"]:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"  [{mark}] {c['rule']:<38} | {c['detail']}")


if __name__ == "__main__":
    main()
