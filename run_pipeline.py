#!/usr/bin/env python3
"""
Master Autonomous Forex Pipeline Runner
Chains all 11 Forex Agents sequentially:
01 scanner -> 02 calendar -> 03 macro -> 04 entry -> 05 exit ->
06 timemachine -> 07 budget -> 08 risk -> 09 broker -> 10 manager -> 11 alerts
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))


def _load_agent_module(rel_path: str, mod_name: str):
    full_path = ROOT_DIR / rel_path
    spec = importlib.util.spec_from_file_location(mod_name, full_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {full_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_full_pipeline(
    pair: str | None = None,
    timeframe: str = "15m",
    offline: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    scan_mod = _load_agent_module("forex-scanner/scan.py", "forex_scanner")
    cal_mod = _load_agent_module("forex-calendar/calendar_watch.py", "forex_calendar")
    macro_mod = _load_agent_module("forex-macro/macro.py", "forex_macro")
    entry_mod = _load_agent_module("forex-entry/entry.py", "forex_entry")
    exit_mod = _load_agent_module("forex-exit/exit.py", "forex_exit")
    tm_mod = _load_agent_module("forex-timemachine/timemachine.py", "forex_timemachine")
    budget_mod = _load_agent_module("forex-budget/sizer.py", "forex_budget")
    risk_mod = _load_agent_module("forex-risk/risk_guardian.py", "forex_risk")
    broker_mod = _load_agent_module("forex-broker/broker.py", "forex_broker")
    mgr_mod = _load_agent_module("forex-manager/manager.py", "forex_manager")
    alert_mod = _load_agent_module("forex-alerts/alerts.py", "forex_alerts")

    # Stage 01: Scanner (Always scan all 8 pairs so watchlist stays complete)
    s1 = scan_mod.run_scanner(pairs=None, timeframe=timeframe, offline=offline)
    chosen_cand = s1["top_pick"]
    if pair:
        clean_target = pair.upper().replace("/", "").replace("+", "")
        for cand in s1.get("candidates", []):
            if cand["pair"] == clean_target:
                chosen_cand = cand
                break
        s1["top_pick"] = chosen_cand
        from forex_core.market_data import save_stage_output
        save_stage_output("scanner", s1)

    active_pair = chosen_cand["pair"]
    active_dir = chosen_cand["direction"]

    # Stage 02: Calendar
    s2 = cal_mod.check_calendar(pair=active_pair, offline=offline)

    # Stage 03: Macro & Currency Strength
    s3 = macro_mod.analyze_macro(pair=active_pair, offline=offline)

    # Stage 04: Entry Trigger
    s4 = entry_mod.evaluate_entry(pair=active_pair, direction=active_dir, timeframe=timeframe, offline=offline)

    # Stage 05: Exit & SL/TP Plan
    s5 = exit_mod.plan_exit(pair=active_pair, direction=active_dir)

    # Stage 06: TimeMachine 10,000-Session Simulation
    s6 = tm_mod.run_timemachine(pair=active_pair, direction=active_dir, offline=offline)

    # Stage 07: Budget & Lot Sizing
    s7 = budget_mod.calculate_lot_size(pair=active_pair)

    # Stage 08: Deterministic Risk Gatekeeper
    s8 = risk_mod.evaluate_risk()

    # Stage 09: Broker Execution
    s9 = broker_mod.execute_order(auto_confirm=True)

    # Stage 10: Active Position Manager
    s10 = mgr_mod.manage_open_trades(offline=offline)

    # Stage 11: Alerts & Telemetry
    s11 = alert_mod.dispatch_alerts()

    summary = {
        "pair": active_pair,
        "direction": active_dir,
        "scanner": s1["top_pick"],
        "calendar": {"risk_status": s2["risk_status"], "blackout_active": s2["blackout_active"]},
        "macro": {"macro_bias": s3["macro_bias"], "macro_aligned": s3["macro_aligned"]},
        "entry": s4,
        "exit": s5,
        "timemachine": s6,
        "budget": s7,
        "risk": s8,
        "broker": s9,
        "manager": s10,
        "alerts": s11,
    }

    if verbose:
        print("=" * 88)
        print("   FOREX 11-AGENT AUTONOMOUS TRADING PIPELINE REPORT")
        print("=" * 88)
        print(f"[01 Scanner]     Top Pick: {active_pair} ({active_dir}) | Score: {s1['top_pick']['score']} | Setup: {s1['top_pick']['setup_type']}")
        print(f"[02 Calendar]    News Status: {s2['risk_status']} | Blackout Active: {s2['blackout_active']}")
        print(f"[03 Macro CSM]   Bias: {s3['macro_bias']} ({s3['base_currency']} {s3['base_strength']} vs {s3['quote_currency']} {s3['quote_strength']}) | Aligned: {s3['macro_aligned']}")
        print(f"[04 Entry]       {s4['order_type']} @ {s4['entry_price']} | Ready: {s4['entry_ready']}")
        print(f"[05 Exit Plan]   SL: {s5['stop_loss_price']} (-{s5['stop_loss_pips']}p) | TP1(1R): {s5['tp1_price_1r']} | TP2: {s5['tp2_price_primary']} ({s5['reward_to_risk']}R)")
        print(f"[06 TimeMachine] {s6['simulations_run']:,} runs | WinRate: {s6['simulated_win_rate'] * 100:.1f}% | EV: {s6['expected_value_r']:+.2f}R | Verdict: {s6['verdict']}")
        print(f"[07 Budget]      Size: {s7['recommended_lots']:.2f} Lots ({s7['units']:,} units) | Risk: ${s7['actual_risk_usd']:.2f} ({s7['actual_risk_pct']}%)")
        print(f"[08 Risk Gate]   Decision: [{s8['decision']}] ({7 - s8['failed_count']}/7 safety rules passed)")
        print(f"[09 Broker]      Status: {s9['status']}" + (f" | Ticket: {s9['order']['ticket_id']}" if s9.get("executed") else ""))
        print(f"[10 Manager]     Open Positions: {s10['remaining_open_count']} | Account Balance: ${s10['account_balance_usd']:,.2f}")
        print("-" * 88)
        print(s11["alert_message"])
        print("=" * 88)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete 11-Agent Forex Trading Pipeline")
    parser.add_argument("--pair", type=str, default="", help="Optional single pair override (e.g. EURUSD)")
    parser.add_argument("--timeframe", type=str, default="15m", help="Candle timeframe (5m, 15m, 1h, 4h)")
    parser.add_argument("--offline", action="store_true", help="Run in offline deterministic mode")
    parser.add_argument("--loop", action="store_true", help="Run continuously on an autonomous schedule")
    parser.add_argument("--interval", type=int, default=900, help="Loop interval in seconds (default: 900s = 15m)")
    parser.add_argument("--json", action="store_true", help="Print JSON summary only")
    args = parser.parse_args()

    if args.loop:
        print(f"Starting Autonomous Forex Loop (every {args.interval}s). Press Ctrl+C to stop.")
        while True:
            run_full_pipeline(
                pair=args.pair or None,
                timeframe=args.timeframe,
                offline=args.offline,
                verbose=not args.json,
            )
            time.sleep(args.interval)
    else:
        res = run_full_pipeline(
            pair=args.pair or None,
            timeframe=args.timeframe,
            offline=args.offline,
            verbose=not args.json,
        )
        if args.json:
            print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
