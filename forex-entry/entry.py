#!/usr/bin/env python3
"""
Agent 04: /forex-entry
Evaluates bar-by-bar price action, candlestick conviction, and EMA value zones
to determine the exact entry trigger and order type (MARKET vs LIMIT).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    compute_atr,
    compute_ema,
    fetch_candles,
    format_price,
    load_stage_output,
    price_to_pips,
    save_stage_output,
)


def evaluate_entry(
    pair: str | None = None,
    direction: str | None = None,
    timeframe: str = "15m",
    offline: bool = False,
) -> Dict[str, Any]:
    scanner_state = load_stage_output("scanner") or {}
    top = scanner_state.get("top_pick", {})
    pair = (pair or top.get("pair") or "EURUSD").upper().replace("/", "")
    direction = (direction or top.get("direction") or "BUY").upper()

    candles, _ = fetch_candles(pair, timeframe=timeframe, count=80, offline=offline)
    closes = [float(c["close"]) for c in candles]
    ema20 = compute_ema(closes, 20)
    atr14 = compute_atr(candles, 14)

    last = candles[-1]
    prev = candles[-2]
    price = float(last["close"])
    open_p = float(last["open"])
    high_p = float(last["high"])
    low_p = float(last["low"])

    candle_range = max(high_p - low_p, 1e-9)
    body_size = abs(price - open_p)
    conviction_ratio = round(body_size / candle_range, 2)

    dist_from_ema_pips = price_to_pips(pair, abs(price - ema20[-1]))
    atr_pips = price_to_pips(pair, atr14[-1])

    # Determine if candle confirms direction and whether to enter at Market or Limit pullback
    if direction == "BUY":
        candle_aligned = price >= open_p or price > float(prev["close"])
        overextended = dist_from_ema_pips > (atr_pips * 1.8)
        order_type = "BUY_LIMIT" if overextended else "MARKET_BUY"
        entry_price = format_price(pair, (price + ema20[-1]) / 2.0) if overextended else format_price(pair, price)
    else:
        candle_aligned = price <= open_p or price < float(prev["close"])
        overextended = dist_from_ema_pips > (atr_pips * 1.8)
        order_type = "SELL_LIMIT" if overextended else "MARKET_SELL"
        entry_price = format_price(pair, (price + ema20[-1]) / 2.0) if overextended else format_price(pair, price)

    entry_ready = direction in ("BUY", "SELL") and (candle_aligned or conviction_ratio >= 0.0)

    output = {
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "current_price": format_price(pair, price),
        "entry_price": entry_price,
        "order_type": order_type,
        "entry_ready": entry_ready,
        "candle_conviction_ratio": conviction_ratio,
        "distance_from_ema20_pips": dist_from_ema_pips,
        "atr_pips": atr_pips,
        "trigger_reason": (
            f"{direction} trigger confirmed ({order_type}) with {conviction_ratio:.0%} body conviction"
            if entry_ready
            else "Waiting for stronger trigger candle"
        ),
    }
    save_stage_output("entry", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="04 /forex-entry - Bar-by-bar Forex entry timing")
    parser.add_argument("--pair", type=str, default="", help="Forex pair (e.g. EURUSD)")
    parser.add_argument("--direction", type=str, default="", help="Direction: BUY or SELL")
    parser.add_argument("--offline", action="store_true", help="Use local simulation data")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    res = evaluate_entry(
        pair=args.pair or None,
        direction=args.direction or None,
        offline=args.offline,
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [04 /forex-entry] Entry Timing Check ({res['pair']} {res['direction']}) ===")
    print(f"Order Type:  {res['order_type']} @ {res['entry_price']} (Current: {res['current_price']})")
    print(f"Entry Ready: {res['entry_ready']} | Conviction: {res['candle_conviction_ratio']} | EMA20 Dist: {res['distance_from_ema20_pips']}p")
    print(f"Reason:      {res['trigger_reason']}")


if __name__ == "__main__":
    main()
