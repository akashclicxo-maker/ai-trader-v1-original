#!/usr/bin/env python3
"""
Module 05: /forex-exit
Calculates Regime-Adaptive ATR Stop Loss (in pips) and multi-tier Take Profit targets
(TP1 @ 1.0R, TP2 @ Regime R:R, TP3 @ 3.0R) before any trade is taken.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    format_price,
    load_stage_output,
    pips_to_price,
    save_stage_output,
)


def plan_exit(
    pair: str | None = None,
    direction: str | None = None,
    entry_price: float | None = None,
    atr_pips: float | None = None,
    rr_target: float | None = None,
) -> Dict[str, Any]:
    entry_state = load_stage_output("entry") or {}
    scanner_state = load_stage_output("scanner") or {}
    top = scanner_state.get("top_pick", {})

    pair = (pair or entry_state.get("pair") or top.get("pair") or "EURUSD").upper().replace("/", "")
    direction = (direction or entry_state.get("direction") or top.get("direction") or "BUY").upper()
    entry_p = float(entry_price or entry_state.get("entry_price") or top.get("price") or 1.0850)
    raw_atr_pips = float(atr_pips or entry_state.get("atr_pips") or top.get("atr_pips") or 12.0)

    # Use explicit rr_target if provided, else use regime-recommended R:R from scanner (default 2.0)
    effective_rr = float(rr_target if rr_target is not None else top.get("recommended_rr", 2.0))
    regime = str(top.get("market_regime", "STRONG_TREND"))

    # Dynamic SL sizing: 1.5x ATR clamped to sensible institutional bounds per asset class
    if any(k in pair for k in ("NAS100", "USTEC", "US100", "NDX", "US30", "DJ30", "GER40", "DAX", "SPX500")):
        sl_pips = round(max(35.0, min(200.0, raw_atr_pips * 1.5)), 1)
    elif pair == "XAUUSD" or "GOLD" in pair:
        sl_pips = round(max(25.0, min(120.0, raw_atr_pips * 1.5)), 1)
    else:
        sl_pips = round(max(12.0, min(45.0, raw_atr_pips * 1.5)), 1)

    tp1_pips = round(sl_pips * 1.0, 1)
    tp2_pips = round(sl_pips * effective_rr, 1)
    tp3_pips = round(sl_pips * 3.0, 1)

    sl_dist = pips_to_price(pair, sl_pips)
    tp1_dist = pips_to_price(pair, tp1_pips)
    tp2_dist = pips_to_price(pair, tp2_pips)
    tp3_dist = pips_to_price(pair, tp3_pips)

    if direction == "BUY":
        sl_price = format_price(pair, entry_p - sl_dist)
        tp1_price = format_price(pair, entry_p + tp1_dist)
        tp2_price = format_price(pair, entry_p + tp2_dist)
        tp3_price = format_price(pair, entry_p + tp3_dist)
    else:
        sl_price = format_price(pair, entry_p + sl_dist)
        tp1_price = format_price(pair, entry_p - tp1_dist)
        tp2_price = format_price(pair, entry_p - tp2_dist)
        tp3_price = format_price(pair, entry_p - tp3_dist)

    output = {
        "pair": pair,
        "direction": direction,
        "market_regime": regime,
        "entry_price": format_price(pair, entry_p),
        "stop_loss_price": sl_price,
        "stop_loss_pips": sl_pips,
        "tp1_price_1r": tp1_price,
        "tp1_pips": tp1_pips,
        "tp2_price_primary": tp2_price,
        "tp2_pips": tp2_pips,
        "tp3_price_runner": tp3_price,
        "tp3_pips": tp3_pips,
        "reward_to_risk": round(tp2_pips / max(sl_pips, 0.1), 2),
    }
    save_stage_output("exit", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="05 /forex-exit - Stop Loss & Take Profit Planner")
    parser.add_argument("--pair", type=str, default="", help="Forex pair (e.g. EURUSD)")
    parser.add_argument("--direction", type=str, default="", help="BUY or SELL")
    parser.add_argument("--entry", type=float, default=0.0, help="Entry price override")
    parser.add_argument("--rr", type=float, default=0.0, help="Primary Reward:Risk ratio override")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    res = plan_exit(
        pair=args.pair or None,
        direction=args.direction or None,
        entry_price=args.entry if args.entry > 0 else None,
        rr_target=args.rr if args.rr > 0 else None,
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [05 /forex-exit] Exit & Stop-Loss Plan ({res['pair']} {res['direction']} | {res.get('market_regime','')}) ===")
    print(f"Entry Price:      {res['entry_price']}")
    print(f"Stop Loss (SL):   {res['stop_loss_price']} (-{res['stop_loss_pips']} pips)")
    print(f"TP1 (1.0R BE):    {res['tp1_price_1r']} (+{res['tp1_pips']} pips)")
    print(f"TP2 (Primary):    {res['tp2_price_primary']} (+{res['tp2_pips']} pips) [R:R = {res['reward_to_risk']}]")
    print(f"TP3 (Runner 3R):  {res['tp3_price_runner']} (+{res['tp3_pips']} pips)")


if __name__ == "__main__":
    main()
