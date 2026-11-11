#!/usr/bin/env python3
"""
Agent 03: /forex-macro
Computes the 8-Currency Strength Meter (CSM), Central Bank Interest Rate Differentials,
and Macro Directional Bias for the active Forex pair.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    fetch_candles,
    fetch_tradingview_scan,
    load_stage_output,
    save_stage_output,
)

# Reference Central Bank Policy Rates & Stance
CENTRAL_BANKS: Dict[str, Dict[str, Any]] = {
    "USD": {"bank": "Federal Reserve (Fed)", "rate": 4.75, "stance": "Hawkish-Neutral", "bias_score": 1.2},
    "EUR": {"bank": "European Central Bank (ECB)", "rate": 3.25, "stance": "Dovish-Neutral", "bias_score": -0.4},
    "GBP": {"bank": "Bank of England (BOE)", "rate": 4.75, "stance": "Neutral", "bias_score": 0.6},
    "JPY": {"bank": "Bank of Japan (BOJ)", "rate": 0.25, "stance": "Gradual Normalization", "bias_score": -1.5},
    "AUD": {"bank": "Reserve Bank of Australia (RBA)", "rate": 4.35, "stance": "Hawkish Hold", "bias_score": 0.5},
    "CAD": {"bank": "Bank of Canada (BOC)", "rate": 3.75, "stance": "Dovish", "bias_score": -0.7},
    "CHF": {"bank": "Swiss National Bank (SNB)", "rate": 1.00, "stance": "Dovish", "bias_score": -0.8},
    "NZD": {"bank": "Reserve Bank of New Zealand (RBNZ)", "rate": 4.75, "stance": "Dovish Pivot", "bias_score": -0.3},
    "XAU": {"bank": "Gold Safe-Haven / Real Yields", "rate": 0.00, "stance": "Central Bank Accumulation", "bias_score": 1.8},
}


def compute_currency_strength(offline: bool = False) -> Dict[str, float]:
    """Calculates relative strength (0-100 scale) for major currencies from recent price momentum."""
    pairs = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
    raw_scores: Dict[str, float] = {k: 50.0 for k in CENTRAL_BANKS}

    tv_map = {} if offline else fetch_tradingview_scan(pairs, timeframe="15m")
    if tv_map:
        for p, tv in tv_map.items():
            scaled = max(-25.0, min(25.0, float(tv.get("tv_recommend", 0.0)) * 32.0 + (float(tv.get("rsi_14", 50.0)) - 50.0) * 0.4))
            base, quote = p[:3], p[3:]
            raw_scores[base] = raw_scores.get(base, 50.0) + scaled
            raw_scores[quote] = raw_scores.get(quote, 50.0) - (scaled * 0.35)
    else:
        for p in pairs:
            candles, _ = fetch_candles(p, timeframe="15m", count=40, offline=offline)
            if len(candles) < 20:
                continue
            start_c = float(candles[-20]["close"])
            end_c = float(candles[-1]["close"])
            pct_change = ((end_c - start_c) / max(start_c, 1e-9)) * 100.0
            scaled = max(-25.0, min(25.0, pct_change * 45.0))

            base, quote = p[:3], p[3:]
            raw_scores[base] = raw_scores.get(base, 50.0) + scaled
            raw_scores[quote] = raw_scores.get(quote, 50.0) - (scaled * 0.35)

    # Blend with macro central bank stance score and clamp [10, 95]
    strength: Dict[str, float] = {}
    for cur, val in raw_scores.items():
        cb_bonus = CENTRAL_BANKS.get(cur, {}).get("bias_score", 0.0) * 3.0
        strength[cur] = round(max(10.0, min(95.0, val + cb_bonus)), 1)
    return dict(sorted(strength.items(), key=lambda item: item[1], reverse=True))


def analyze_macro(pair: str | None = None, offline: bool = False) -> Dict[str, Any]:
    scanner_state = load_stage_output("scanner") or {}
    top_pick = scanner_state.get("top_pick", {})
    pair = (pair or top_pick.get("pair") or "EURUSD").upper().replace("/", "")
    tech_dir = top_pick.get("direction", "BUY")

    base, quote = pair[:3], pair[3:]
    csm = compute_currency_strength(offline=offline)

    base_strength = csm.get(base, 50.0)
    quote_strength = csm.get(quote, 50.0)
    strength_diff = round(base_strength - quote_strength, 1)

    base_cb = CENTRAL_BANKS.get(base, {"bank": base, "rate": 0.0, "stance": "Neutral"})
    quote_cb = CENTRAL_BANKS.get(quote, {"bank": quote, "rate": 0.0, "stance": "Neutral"})
    rate_diff = round(float(base_cb["rate"]) - float(quote_cb["rate"]), 2)

    macro_bias = "BUY" if strength_diff >= 1.5 else ("SELL" if strength_diff <= -1.5 else "NEUTRAL")
    aligned = (macro_bias == tech_dir) or (macro_bias == "NEUTRAL")

    output = {
        "pair": pair,
        "base_currency": base,
        "quote_currency": quote,
        "base_strength": base_strength,
        "quote_strength": quote_strength,
        "strength_differential": strength_diff,
        "rate_differential_pct": rate_diff,
        "base_central_bank": base_cb,
        "quote_central_bank": quote_cb,
        "macro_bias": macro_bias,
        "technical_direction": tech_dir,
        "macro_aligned": aligned,
        "currency_strength_meter": csm,
    }
    save_stage_output("macro", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="03 /forex-macro - Currency Strength Meter & Central Bank Bias")
    parser.add_argument("--pair", type=str, default="", help="Forex pair (e.g. EURUSD)")
    parser.add_argument("--offline", action="store_true", help="Use local simulation data")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    res = analyze_macro(pair=args.pair or None, offline=args.offline)
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [03 /forex-macro] Macro & Currency Strength Analysis ({res['pair']}) ===")
    print("Currency Strength Meter (0-100):")
    csm_line = " | ".join(f"{k}: {v}" for k, v in res["currency_strength_meter"].items())
    print(f"  {csm_line}")
    print(
        f"\nPair Differential ({res['base_currency']} vs {res['quote_currency']}): "
        f"{res['strength_differential']:+.1f} pts | Rate Diff: {res['rate_differential_pct']:+.2f}%"
    )
    print(
        f"Macro Bias: {res['macro_bias']} | Technical Dir: {res['technical_direction']} | "
        f"Aligned: {'YES' if res['macro_aligned'] else 'CONFLICT'}"
    )


if __name__ == "__main__":
    main()
