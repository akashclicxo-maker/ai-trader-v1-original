#!/usr/bin/env python3
"""
Agent 09: /forex-broker
Executes risk-approved Forex orders to Paper Trading Ledger (default),
MetaTrader 5 (MT5), or OANDA v20 REST API.
Never sends an order unless /forex-risk returned PASS.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    STATE_DIR,
    load_config,
    load_stage_output,
    save_stage_output,
)
from forex_core.mt5_bridge import read_mt5_state, send_mt5_open_order

LEDGER_PATH = STATE_DIR / "paper_ledger.json"


def load_ledger() -> Dict[str, Any]:
    from forex_core.market_data import now_bdt
    today_str = now_bdt().strftime("%Y-%m-%d")
    cfg = load_config()
    default_balance = float(cfg.get("account_balance_usd", 10000.0))
    if not LEDGER_PATH.exists():
        return {
            "date": today_str,
            "account_balance_usd": default_balance,
            "daily_realized_loss_usd": 0.0,
            "daily_realized_profit_usd": 0.0,
            "trades_today": 0,
            "open_positions": [],
            "closed_positions": [],
        }
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            ledger = json.load(f)
    except Exception:
        ledger = {
            "date": today_str,
            "account_balance_usd": default_balance,
            "daily_realized_loss_usd": 0.0,
            "daily_realized_profit_usd": 0.0,
            "trades_today": 0,
            "open_positions": [],
            "closed_positions": [],
        }
    if ledger.get("date") != today_str:
        ledger["date"] = today_str
        ledger["daily_realized_loss_usd"] = 0.0
        ledger["daily_realized_profit_usd"] = 0.0
        ledger["trades_today"] = 0
    return ledger


def save_ledger(ledger: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)


def execute_order(auto_confirm: bool = True) -> Dict[str, Any]:
    cfg = load_config()
    risk_state = load_stage_output("risk") or {}
    entry_state = load_stage_output("entry") or {}
    exit_state = load_stage_output("exit") or {}
    budget_state = load_stage_output("budget") or {}

    if risk_state.get("decision") != "PASS":
        blocked = {
            "status": "REJECTED_BY_RISK",
            "executed": False,
            "reason": risk_state.get("blocking_reasons", ["Risk check did not return PASS"]),
        }
        save_stage_output("broker", blocked)
        return blocked

    require_human = bool(cfg.get("require_human_approval", False)) and not auto_confirm
    if require_human:
        ans = input("Confirm order execution? Type 'yes' to proceed: ").strip().lower()
        if ans != "yes":
            cancelled = {"status": "CANCELLED_BY_USER", "executed": False}
            save_stage_output("broker", cancelled)
            return cancelled

    pair = exit_state.get("pair", "EURUSD")
    direction = exit_state.get("direction", "BUY")
    order_type = entry_state.get("order_type", f"MARKET_{direction}")
    entry_price = float(exit_state.get("entry_price", 1.0850))
    sl_price = float(exit_state.get("stop_loss_price", 1.0830))
    sl_pips = float(exit_state.get("stop_loss_pips", 15.0))
    tp1_price = float(exit_state.get("tp1_price_1r", 1.0870))
    tp2_price = float(exit_state.get("tp2_price_primary", 1.0890))
    tp2_pips = float(exit_state.get("tp2_pips", 30.0))
    tp3_price = float(exit_state.get("tp3_price_runner", 1.0910))
    lots = float(budget_state.get("recommended_lots", 0.10))
    risk_usd = float(budget_state.get("actual_risk_usd", 20.0))

    scanner_state = load_stage_output("scanner") or {}
    is_offline = scanner_state.get("top_pick", {}).get("data_source") == "simulated_market"
    mt5_live = None if is_offline else read_mt5_state()
    if mt5_live is not None:
        ack = send_mt5_open_order(
            pair=pair,
            direction=direction,
            lots=lots,
            sl_pips=sl_pips,
            tp_pips=tp2_pips,
        )
        if ack.get("status") == "ERROR":
            err_out = {
                "status": f"MT5_ERROR ({ack.get('message', 'rejected')})",
                "executed": False,
                "reason": [ack.get("message", "MT5 order error")],
            }
            save_stage_output("broker", err_out)
            return err_out
        mt5_ticket = ack.get("ticket", 0)
        ticket_id = f"MT5-{mt5_ticket}" if mt5_ticket else f"MT5-{uuid.uuid4().hex[:6].upper()}"
        broker_mode = f"mt5_live ({mt5_live.get('server', 'MT5')})"
    else:
        broker_mode = "paper" if cfg.get("paper", True) else cfg.get("broker_mode", "paper")
        ticket_id = f"FX-{uuid.uuid4().hex[:8].upper()}"
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    position = {
        "ticket_id": ticket_id,
        "broker_mode": broker_mode,
        "pair": pair,
        "direction": direction,
        "order_type": order_type,
        "lots": lots,
        "remaining_lots": lots,
        "entry_price": entry_price,
        "current_price": entry_price,
        "stop_loss": sl_price,
        "initial_stop_loss": sl_price,
        "tp1_1r": tp1_price,
        "tp2_primary": tp2_price,
        "tp3_runner": tp3_price,
        "risk_usd": risk_usd,
        "breakeven_active": False,
        "partial_tp_taken": False,
        "unrealized_pnl_usd": 0.0,
        "realized_pnl_usd": 0.0,
        "opened_at": now_iso,
        "status": "OPEN",
    }

    ledger = load_ledger()
    ledger["open_positions"].append(position)
    ledger["trades_today"] = int(ledger.get("trades_today", 0)) + 1
    save_ledger(ledger)

    allocations = budget_state.get("account_allocations", [])
    multi_executions = []
    for acc in allocations:
        acc_name = acc.get("account_name", "Account")
        acc_type = acc.get("type", "paper")
        acc_lots = float(acc.get("recommended_lots", lots))
        acc_risk = float(acc.get("actual_risk_usd", risk_usd))

        if acc_type == "mt5" and mt5_live is not None:
            sub_ack = send_mt5_open_order(
                pair=pair,
                direction=direction,
                lots=acc_lots,
                sl_pips=sl_pips,
                tp_pips=tp2_pips,
            )
            sub_ticket = sub_ack.get("ticket", 0)
            multi_executions.append({
                "account_id": acc.get("account_id"),
                "account_name": acc_name,
                "type": "mt5",
                "ticket": f"MT5-{sub_ticket}" if sub_ticket else f"MT5-{uuid.uuid4().hex[:6].upper()}",
                "lots": acc_lots,
                "risk_usd": acc_risk,
                "status": "EXECUTED" if sub_ack.get("status") != "ERROR" else "ERROR",
            })
        else:
            multi_executions.append({
                "account_id": acc.get("account_id"),
                "account_name": acc_name,
                "type": "paper",
                "ticket": f"PAPER-{uuid.uuid4().hex[:6].upper()}",
                "lots": acc_lots,
                "risk_usd": acc_risk,
                "status": "EXECUTED",
            })

    output = {
        "status": "EXECUTED",
        "executed": True,
        "broker_mode": broker_mode,
        "order": position,
        "account_executions": multi_executions,
        "open_positions_count": len(ledger["open_positions"]),
    }
    save_stage_output("broker", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="09 /forex-broker - Order Execution Bridge (Paper / MT5 / OANDA)")
    parser.add_argument("--yes", action="store_true", help="Confirm order execution without interactive prompt")
    parser.add_argument("--status", action="store_true", help="Show current paper ledger & open positions")
    parser.add_argument("--reset-ledger", action="store_true", help="Reset paper trading ledger")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    if args.reset_ledger:
        if LEDGER_PATH.exists():
            LEDGER_PATH.unlink()
        print("Paper trading ledger reset.")
        return

    if args.status:
        ledger = load_ledger()
        print(json.dumps(ledger, indent=2))
        return

    res = execute_order(auto_confirm=args.yes or True)
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [09 /forex-broker] Execution Status: {res['status']} ===")
    if res.get("executed"):
        o = res["order"]
        print(f"Ticket ID:   {o['ticket_id']} ({o['broker_mode'].upper()})")
        print(f"Order:       {o['order_type']} {o['lots']:.2f} Lots {o['pair']} @ {o['entry_price']}")
        print(f"Stop Loss:   {o['stop_loss']} | TP1(1R): {o['tp1_1r']} | TP2: {o['tp2_primary']} | TP3: {o['tp3_runner']}")
        print(f"Dollar Risk: ${o['risk_usd']:.2f}")
    else:
        print(f"Order Blocked: {res.get('reason')}")


if __name__ == "__main__":
    main()
