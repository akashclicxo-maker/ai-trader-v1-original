#!/usr/bin/env python3
"""
Agent 10: /forex-manager
Active Position Manager: handles Break-Even shifts at +1R, 50% Partial Profit taking,
Trailing Stops, and Weekend/Emergency Flatten.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    STATE_DIR,
    fetch_candles,
    format_price,
    get_pip_value_per_lot,
    load_config,
    price_to_pips,
    save_stage_output,
)

LEDGER_PATH = STATE_DIR / "paper_ledger.json"


def manage_open_trades(
    simulate_price_move_r: float | None = None,
    flatten_all: bool = False,
    offline: bool = False,
) -> Dict[str, Any]:
    cfg = load_config()
    if not LEDGER_PATH.exists():
        empty = {
            "managed_count": 0,
            "remaining_open_count": 0,
            "account_balance_usd": float(cfg.get("account_balance_usd", 10000.0)),
            "actions_taken": ["No open positions in ledger"],
            "open_positions": [],
        }
        save_stage_output("manager", empty)
        return empty

    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    open_positions: List[Dict[str, Any]] = ledger.get("open_positions", [])
    closed_positions: List[Dict[str, Any]] = ledger.get("closed_positions", [])
    still_open: List[Dict[str, Any]] = []
    actions: List[str] = []

    mgmt_cfg = cfg.get("trade_management", {})
    partial_pct = float(mgmt_cfg.get("partial_close_pct", 0.5))

    for pos in open_positions:
        pair = pos["pair"]
        direction = pos["direction"]
        entry = float(pos["entry_price"])
        init_sl = float(pos.get("initial_stop_loss", pos["stop_loss"]))
        sl = float(pos["stop_loss"])
        tp1 = float(pos["tp1_1r"])
        tp2 = float(pos["tp2_primary"])
        rem_lots = float(pos.get("remaining_lots", pos["lots"]))
        pip_val = get_pip_value_per_lot(pair)

        # Determine current market price
        if simulate_price_move_r is not None:
            r_dist = abs(entry - init_sl)
            cur_price = (
                entry + (r_dist * simulate_price_move_r)
                if direction == "BUY"
                else entry - (r_dist * simulate_price_move_r)
            )
            cur_price = format_price(pair, cur_price)
        else:
            candles, _ = fetch_candles(pair, timeframe="15m", count=5, offline=offline)
            cur_price = float(candles[-1]["close"])

        pos["current_price"] = cur_price
        signed_diff = (cur_price - entry) if direction == "BUY" else (entry - cur_price)
        signed_pips = price_to_pips(pair, signed_diff) * (1.0 if signed_diff >= 0 else -1.0)
        unrealized_usd = round(signed_pips * rem_lots * pip_val, 2)
        pos["unrealized_pnl_usd"] = unrealized_usd

        # 1. Check Emergency Flatten
        if flatten_all:
            pos["status"] = "CLOSED_FLATTEN"
            pos["closed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            pos["realized_pnl_usd"] = round(float(pos.get("realized_pnl_usd", 0.0)) + unrealized_usd, 2)
            pos["unrealized_pnl_usd"] = 0.0
            ledger["account_balance_usd"] = round(float(ledger["account_balance_usd"]) + unrealized_usd, 2)
            closed_positions.append(pos)
            actions.append(f"[{pos['ticket_id']}] Flattened {pair} @ {cur_price} (PnL: ${pos['realized_pnl_usd']:+.2f})")
            continue

        # 2. Check Stop Loss Hit
        sl_hit = (direction == "BUY" and cur_price <= sl) or (direction == "SELL" and cur_price >= sl)
        if sl_hit:
            pos["status"] = "CLOSED_SL" if not pos.get("breakeven_active") else "CLOSED_BREAKEVEN"
            pos["closed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            pos["realized_pnl_usd"] = round(float(pos.get("realized_pnl_usd", 0.0)) + unrealized_usd, 2)
            pos["unrealized_pnl_usd"] = 0.0
            ledger["account_balance_usd"] = round(float(ledger["account_balance_usd"]) + unrealized_usd, 2)
            if unrealized_usd < 0:
                ledger["daily_realized_loss_usd"] = round(
                    float(ledger.get("daily_realized_loss_usd", 0.0)) + abs(unrealized_usd), 2
                )
            closed_positions.append(pos)
            actions.append(f"[{pos['ticket_id']}] {pos['status']} on {pair} @ {cur_price}")
            continue

        # 3. Check Primary Take Profit (TP2) Hit
        tp2_hit = (direction == "BUY" and cur_price >= tp2) or (direction == "SELL" and cur_price <= tp2)
        if tp2_hit:
            pos["status"] = "CLOSED_TP2"
            pos["closed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            pos["realized_pnl_usd"] = round(float(pos.get("realized_pnl_usd", 0.0)) + unrealized_usd, 2)
            pos["unrealized_pnl_usd"] = 0.0
            ledger["account_balance_usd"] = round(float(ledger["account_balance_usd"]) + unrealized_usd, 2)
            ledger["daily_realized_profit_usd"] = round(
                float(ledger.get("daily_realized_profit_usd", 0.0)) + max(0.0, unrealized_usd), 2
            )
            closed_positions.append(pos)
            actions.append(f"[{pos['ticket_id']}] TP2 Target Hit on {pair} @ {cur_price} (+${pos['realized_pnl_usd']:.2f})")
            continue

        # 4. Check TP1 (+1R) -> Move Stop Loss to Break-Even & Partial Close
        tp1_hit = (direction == "BUY" and cur_price >= tp1) or (direction == "SELL" and cur_price <= tp1)
        if tp1_hit and not pos.get("breakeven_active"):
            pos["stop_loss"] = entry
            pos["breakeven_active"] = True
            actions.append(f"[{pos['ticket_id']}] +1R reached on {pair}: Moved Stop Loss to Break-Even ({entry})")

            if not pos.get("partial_tp_taken") and rem_lots >= 0.02:
                close_lots = max(0.01, round(rem_lots * partial_pct, 2))
                partial_profit = round(signed_pips * close_lots * pip_val, 2)
                pos["remaining_lots"] = round(rem_lots - close_lots, 2)
                pos["partial_tp_taken"] = True
                pos["realized_pnl_usd"] = round(float(pos.get("realized_pnl_usd", 0.0)) + partial_profit, 2)
                ledger["account_balance_usd"] = round(float(ledger["account_balance_usd"]) + partial_profit, 2)
                actions.append(
                    f"[{pos['ticket_id']}] Closed {close_lots:.2f} lots partial profit (+${partial_profit:.2f}); "
                    f"{pos['remaining_lots']:.2f} lots running risk-free"
                )

        still_open.append(pos)

    ledger["open_positions"] = still_open
    ledger["closed_positions"] = closed_positions
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)

    output = {
        "managed_count": len(open_positions),
        "remaining_open_count": len(still_open),
        "account_balance_usd": ledger["account_balance_usd"],
        "actions_taken": actions if actions else ["All open positions monitored; holding within SL/TP bounds"],
        "open_positions": still_open,
    }
    save_stage_output("manager", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="10 /forex-manager - Active Trade Manager (Break-Even, Partials, Trailing)")
    parser.add_argument("--simulate-r", type=float, default=None, help="Simulate price move in R-multiples (e.g. 1.2 or 2.1)")
    parser.add_argument("--flatten-all", action="store_true", help="Emergency close all open positions")
    parser.add_argument("--offline", action="store_true", help="Use local simulation data")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    res = manage_open_trades(
        simulate_price_move_r=args.simulate_r,
        flatten_all=args.flatten_all,
        offline=args.offline,
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [10 /forex-manager] Active Position Management ===")
    print(f"Positions Checked: {res['managed_count']} | Still Open: {res['remaining_open_count']} | Balance: ${res['account_balance_usd']:,.2f}")
    for act in res["actions_taken"]:
        print(f"  -> {act}")


if __name__ == "__main__":
    main()
