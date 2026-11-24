#!/usr/bin/env python3
"""
Agent 07: /forex-budget
Dynamic Forex Lot Size & Equity Progression Engine.
Scales risk by Setup Conviction Grade (A+ / A / B), compounds with equity growth,
and activates a Drawdown Shield when account equity dips.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    get_active_accounts,
    get_pip_value_per_lot,
    load_config,
    load_stage_output,
    save_stage_output,
)
from forex_core.mt5_bridge import read_mt5_state


def calculate_lot_size(
    pair: str | None = None,
    balance_usd: float | None = None,
    risk_pct: float | None = None,
    max_loss_usd: float | None = None,
    sl_pips: float | None = None,
) -> Dict[str, Any]:
    cfg = load_config()
    exit_state = load_stage_output("exit") or {}
    scanner_state = load_stage_output("scanner") or {}
    top = scanner_state.get("top_pick", {})

    pair = (pair or exit_state.get("pair") or top.get("pair") or "EURUSD").upper().replace("/", "").replace("+", "")
    mt5_live = read_mt5_state()
    base_cfg_bal = float(cfg.get("account_balance_usd", 10000.0))

    if balance_usd is not None:
        balance = float(balance_usd)
        dynamic_mode = False
    elif mt5_live and mt5_live.get("equity"):
        balance = float(mt5_live["equity"])
        dynamic_mode = True
    else:
        balance = base_cfg_bal
        dynamic_mode = True

    base_risk_p = float(risk_pct if risk_pct is not None else cfg.get("risk_per_trade_pct", 1.0))
    grade = str(top.get("grade", "A"))
    score = int(top.get("score", 82))

    # Dynamic Conviction & Progression Scaling (only when risk_pct is not manually overridden)
    progression_state = "STANDARD_1R"
    if risk_pct is None and dynamic_mode:
        if grade == "A+" or score >= 86:
            tier_mult = 1.0
            progression_state = "A+_FULL_CONVICTION"
        elif grade == "A" or score >= 78:
            tier_mult = 0.70
            progression_state = "A_TIER_SCALED (0.7x)"
        else:
            tier_mult = 0.45
            progression_state = "DEFENSIVE_TIER (0.45x)"

        # Drawdown shield vs profit compounding
        dd_pct = ((base_cfg_bal - balance) / max(base_cfg_bal, 1.0)) * 100.0
        if dd_pct >= 2.5:
            tier_mult *= 0.65
            progression_state += " + DRAWDOWN_SHIELD"
        elif balance > base_cfg_bal * 1.02:
            progression_state += " + EQUITY_COMPOUNDING"

        effective_risk_pct = round(base_risk_p * tier_mult, 2)
    else:
        effective_risk_pct = base_risk_p

    cap_usd = float(max_loss_usd if max_loss_usd is not None else cfg.get("max_loss_per_trade_usd", 100.0))
    stop_pips = float(sl_pips if sl_pips is not None else (exit_state.get("stop_loss_pips") or 20.0))
    rr = float(exit_state.get("reward_to_risk", 2.0))

    pct_risk_usd = balance * (effective_risk_pct / 100.0)
    allowed_risk_usd = min(pct_risk_usd, cap_usd)

    pip_val_std_lot = get_pip_value_per_lot(pair)
    raw_lots = allowed_risk_usd / max(stop_pips * pip_val_std_lot, 1e-6)

    # Floor to nearest 0.01 micro-lot so we never exceed risk cap
    lots = max(0.01, math.floor(raw_lots * 100.0) / 100.0)
    actual_risk_usd = round(lots * stop_pips * pip_val_std_lot, 2)
    potential_profit_tp2_usd = round(actual_risk_usd * rr, 2)

    output = {
        "pair": pair,
        "setup_grade": grade,
        "progression_mode": progression_state,
        "account_balance_usd": round(balance, 2),
        "risk_per_trade_pct": effective_risk_pct,
        "max_loss_cap_usd": cap_usd,
        "allowed_risk_usd": round(allowed_risk_usd, 2),
        "stop_loss_pips": stop_pips,
        "pip_value_per_std_lot_usd": pip_val_std_lot,
        "recommended_lots": lots,
        "units": int(round(lots * 100000)),
        "actual_risk_usd": actual_risk_usd,
        "actual_risk_pct": round((actual_risk_usd / max(balance, 1.0)) * 100.0, 2),
        "potential_profit_tp2_usd": potential_profit_tp2_usd,
    }

    # Compute dedicated lot size allocations for all active accounts
    active_accs = get_active_accounts()
    allocations = []
    for acc in active_accs:
        acc_bal = float(acc.get("balance_usd", 10000.0))
        acc_risk_pct = float(acc.get("risk_per_trade_pct", 0.5))
        # If in Prop Firm mode, ensure risk does not exceed safe prop firm threshold
        if acc.get("prop_firm_mode", False):
            acc_risk_pct = min(acc_risk_pct, 1.0)
        acc_allowed_risk = acc_bal * (acc_risk_pct / 100.0)
        risk_per_std_lot = stop_pips * pip_val_std_lot
        if risk_per_std_lot > 0:
            raw_acc_lots = acc_allowed_risk / risk_per_std_lot
            acc_lots = max(0.01, min(100.0, round(raw_acc_lots, 2)))
        else:
            acc_lots = 0.01
        acc_actual_risk = round(acc_lots * stop_pips * pip_val_std_lot, 2)
        allocations.append({
            "account_id": acc.get("id"),
            "account_name": acc.get("name"),
            "type": acc.get("type", "paper"),
            "login": acc.get("login", 0),
            "server": acc.get("server", ""),
            "balance_usd": acc_bal,
            "risk_per_trade_pct": acc_risk_pct,
            "recommended_lots": acc_lots,
            "actual_risk_usd": acc_actual_risk,
            "prop_firm_mode": acc.get("prop_firm_mode", False),
        })
    output["account_allocations"] = allocations

    save_stage_output("budget", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="07 /forex-budget - Dynamic Forex Lot Size & Progression Calculator")
    parser.add_argument("--pair", type=str, default="", help="Forex pair (e.g. EURUSD)")
    parser.add_argument("--balance", type=float, default=-1.0, help="Account balance USD")
    parser.add_argument("--risk", type=float, default=-1.0, help="Risk percentage per trade (e.g. 1.0)")
    parser.add_argument("--sl-pips", type=float, default=-1.0, help="Stop Loss distance in pips")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    res = calculate_lot_size(
        pair=args.pair or None,
        balance_usd=args.balance if args.balance > 0 else None,
        risk_pct=args.risk if args.risk > 0 else None,
        sl_pips=args.sl_pips if args.sl_pips > 0 else None,
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [07 /forex-budget] Position Sizing & Progression ({res['pair']} • Grade {res['setup_grade']}) ===")
    print(f"Progression Mode:  {res['progression_mode']}")
    print(f"Account Equity:    ${res['account_balance_usd']:,.2f} | Allowed Risk: ${res['allowed_risk_usd']:,.2f} ({res['risk_per_trade_pct']}%)")
    print(f"Stop Loss:         {res['stop_loss_pips']} pips (${res['pip_value_per_std_lot_usd']}/pip per 1.00 lot)")
    print(f"Recommended Size:  {res['recommended_lots']:.2f} Lots ({res['units']:,} units)")
    print(f"Actual Dollar Risk:${res['actual_risk_usd']:,.2f} ({res['actual_risk_pct']}%) | Target Profit (TP2): +${res['potential_profit_tp2_usd']:,.2f}")


if __name__ == "__main__":
    main()
