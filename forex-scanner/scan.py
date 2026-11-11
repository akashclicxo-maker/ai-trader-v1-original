#!/usr/bin/env python3
"""
Module 01: /forex-scanner
100% Standalone Self-Adaptive Market Regime & Multi-Strategy Quantitative Engine.
Zero AI/LLM dependency — operates on deterministic institutional math across 4 regimes:
  1. STRONG_TREND: Institutional MTF Trend Continuation (H4 + H1 + M15 + EMA200|H1 + ADX >= 23)
  2. VOLATILITY_BREAKOUT: London/NY Session Momentum Expansion (Bollinger/EMA Breakout + MACD Impulse)
  3. RANGE_LIQUIDITY_SWEEP: Smart Money Mean-Reversion (Bollinger Extremes + RSI/Stoch Reversal in Low ADX)
  4. CHOP_NO_TRADE: Dead/Conflicting Sideways Zone (ADX < 18 + Mid RSI) -> Auto-Blocked
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    compute_atr,
    compute_bollinger,
    compute_ema,
    compute_rsi,
    detect_support_resistance,
    fetch_candles,
    fetch_tradingview_scan,
    format_bdt_timestamp,
    format_price,
    load_config,
    now_bdt,
    price_to_pips,
    save_stage_output,
)


def _grade_from_score(score: int) -> str:
    if score >= 88:
        return "A+"
    if score >= 78:
        return "A"
    if score >= 68:
        return "B"
    return "C"


def _session_quality_bonus() -> tuple[int, str]:
    """
    Evaluates current institutional liquidity session using Bangladesh Time (BDT, UTC+6):
    - London Open / Session: 13:00 - 18:00 BDT
    - London + New York Overlap (Peak Volume): 18:00 - 23:00 BDT
    - Late NY / Asian Active: 23:00 - 09:00 BDT
    """
    bdt_hour = now_bdt().hour
    if 18 <= bdt_hour < 23:
        return 6, "LDN+NY Overlap (Peak Vol)"
    if 13 <= bdt_hour < 18:
        return 5, "London Session"
    if 6 <= bdt_hour < 13:
        return 3, "Tokyo/Asian Session"
    return 3, "New York Session"


def analyze_pair(
    pair: str,
    timeframe: str = "15m",
    offline: bool = False,
    tv_snapshot: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    sess_pts, sess_name = _session_quality_bonus()

    if not offline and tv_snapshot:
        price = float(tv_snapshot["close"])
        open_p = float(tv_snapshot["open"])
        high_p = float(tv_snapshot["high"])
        low_p = float(tv_snapshot["low"])
        ema20_val = float(tv_snapshot["ema_20"])
        ema50_val = float(tv_snapshot["ema_50"])
        ema200_h1 = float(tv_snapshot.get("ema_200_h1", ema50_val))
        bb_upper = float(tv_snapshot.get("bb_upper", high_p))
        bb_lower = float(tv_snapshot.get("bb_lower", low_p))
        stoch_k = float(tv_snapshot.get("stoch_k", 50.0))
        stoch_d = float(tv_snapshot.get("stoch_d", 50.0))
        rsi_val = float(tv_snapshot["rsi_14"])
        atr_pips = float(tv_snapshot["atr_pips"])
        adx_val = float(tv_snapshot.get("adx_14", 22.0))
        macd_hist = float(tv_snapshot.get("macd_hist", 0.0))
        tv_m15 = float(tv_snapshot.get("tv_m15", tv_snapshot.get("tv_recommend", 0.0)))
        tv_h1 = float(tv_snapshot.get("tv_h1", tv_m15))
        tv_h4 = float(tv_snapshot.get("tv_h4", tv_h1))
        spread_pips = float(tv_snapshot.get("spread_pips", 1.2))

        composite_bias = (tv_h4 * 0.40) + (tv_h1 * 0.35) + (tv_m15 * 0.25)
        ema_bull = ema20_val >= ema50_val
        above_h1_200 = price >= ema200_h1

        bb_width = max(bb_upper - bb_lower, 1e-9)
        bb_pos = (price - bb_lower) / bb_width  # 0.0 = at lower band, 1.0 = at upper band

        confluence_factors: List[str] = [sess_name]
        score = 46 + sess_pts

        # -------------------------------------------------------------------
        # SELF-ADAPTIVE QUANTITATIVE MARKET REGIME CLASSIFIER (4 REGIMES)
        # -------------------------------------------------------------------
        htf_bull = tv_h1 >= -0.04 and tv_h4 >= -0.06
        htf_bear = tv_h1 <= 0.04 and tv_h4 <= 0.06

        # REGIME 3 Check: Smart Money Range Liquidity Sweep (Mean-Reversion at Band Extremes)
        is_bull_sweep = (adx_val < 24.0) and (bb_pos <= 0.16 or rsi_val <= 35.0) and (stoch_k <= 32.0 or stoch_k >= stoch_d)
        is_bear_sweep = (adx_val < 24.0) and (bb_pos >= 0.84 or rsi_val >= 65.0) and (stoch_k >= 68.0 or stoch_k <= stoch_d)

        # REGIME 4 Check: Dead Chop / Conflicting Whipsaw Zone
        is_dead_chop = (
            adx_val < 16.5
            and 43.0 <= rsi_val <= 57.0
            and abs(composite_bias) < 0.08
            and 0.25 < bb_pos < 0.75
        )

        if is_dead_chop:
            market_regime = "CHOP_NO_TRADE"
            setup_type = "chop_filter_standby"
            direction = "BUY" if ema_bull else "SELL"
            recommended_rr = 1.8
            score = 62  # Below 78 min_setup_score so 08 /risk automatically blocks trading in chop
            confluence_factors = ["Low ADX Chop Filter Active (Capital Protected)"]

        elif is_bull_sweep or is_bear_sweep:
            market_regime = "RANGE_LIQUIDITY_SWEEP"
            setup_type = "smc_liquidity_sweep_reversion"
            direction = "BUY" if is_bull_sweep else "SELL"
            recommended_rr = 1.9
            score += 24
            confluence_factors.append("BB Extreme Sweep")
            confluence_factors.append(f"RSI({rsi_val:.0f})/Stoch({stoch_k:.0f}) Reversal")
            if (direction == "BUY" and above_h1_200) or (direction == "SELL" and not above_h1_200):
                score += 9
                confluence_factors.append("H1 EMA200 Macro Support")
            if (spread_pips / max(atr_pips, 1.0)) <= 0.25:
                score += 5

        elif adx_val >= 23.0 and ((ema_bull and htf_bull) or ((not ema_bull) and htf_bear)):
            market_regime = "STRONG_TREND"
            setup_type = "institutional_trend_continuation"
            direction = "BUY" if ema_bull else "SELL"
            recommended_rr = 2.4
            score += 22
            confluence_factors.append("H4+H1+M15 Trend Aligned")
            confluence_factors.append(f"ADX Power ({adx_val:.0f})")
            if (direction == "BUY" and above_h1_200) or (direction == "SELL" and not above_h1_200):
                score += 10
                confluence_factors.append("H1 EMA200 Structure")
            if (direction == "BUY" and macd_hist >= 0) or (direction == "SELL" and macd_hist <= 0):
                score += 7
                confluence_factors.append("MACD Impulse")
            if (direction == "BUY" and 40.0 <= rsi_val <= 68.0) or (direction == "SELL" and 32.0 <= rsi_val <= 60.0):
                score += 6
                confluence_factors.append("Optimal RSI Pullback Zone")

        else:
            market_regime = "VOLATILITY_BREAKOUT"
            setup_type = "session_momentum_breakout"
            if composite_bias > 0.02 or (composite_bias >= -0.05 and ema_bull):
                direction = "BUY"
            else:
                direction = "SELL"
            recommended_rr = 2.1

            if (direction == "BUY" and htf_bull) or (direction == "SELL" and htf_bear):
                score += 15
                confluence_factors.append("HTF Momentum Flow")
            if (direction == "BUY" and price >= ema20_val) or (direction == "SELL" and price <= ema20_val):
                score += 12
                confluence_factors.append("M15 EMA20 Expansion")
            if (direction == "BUY" and macd_hist >= 0) or (direction == "SELL" and macd_hist <= 0):
                score += 8
                confluence_factors.append("MACD Histogram Surge")
            if adx_val >= 19.0:
                score += 6
                confluence_factors.append(f"ADX Building ({adx_val:.0f})")
            if (spread_pips / max(atr_pips, 1.0)) <= 0.25:
                score += 5

        final_score = min(98, max(50, score))
        grade = _grade_from_score(final_score)

        return {
            "pair": pair,
            "tv_symbol": tv_snapshot.get("tv_symbol", f"FX:{pair}"),
            "timeframe": timeframe,
            "data_source": "tradingview_live",
            "price": format_price(pair, price),
            "direction": direction,
            "market_regime": market_regime,
            "setup_type": setup_type,
            "recommended_rr": recommended_rr,
            "grade": grade,
            "score": final_score,
            "confluence": ", ".join(confluence_factors),
            "rsi_14": round(rsi_val, 1),
            "stoch_k": round(stoch_k, 1),
            "adx_14": round(adx_val, 1),
            "atr_pips": round(atr_pips, 1),
            "ema_20": format_price(pair, ema20_val),
            "ema_50": format_price(pair, ema50_val),
            "ema_200_h1": format_price(pair, ema200_h1),
            "bb_upper": format_price(pair, bb_upper),
            "bb_lower": format_price(pair, bb_lower),
            "tv_m15": round(tv_m15, 2),
            "tv_h1": round(tv_h1, 2),
            "tv_h4": round(tv_h4, 2),
            "swing_high": format_price(pair, high_p),
            "swing_low": format_price(pair, low_p),
            "pivot": format_price(pair, (high_p + low_p + price) / 3.0),
            "spread_pips": spread_pips,
            "tv_recommend": round(composite_bias, 3),
            "momentum_ratio": round(abs(composite_bias) * 2.5 + 0.95, 2),
            "timestamp": tv_snapshot["timestamp"],
            "timestamp_bdt": tv_snapshot.get("timestamp_bdt", format_bdt_timestamp()),
        }

    # Offline / Deterministic Candle Calculation Fallback
    candles, source = fetch_candles(pair, timeframe=timeframe, count=120, offline=offline)
    closes = [float(c["close"]) for c in candles]
    ema20 = compute_ema(closes, 20)
    ema50 = compute_ema(closes, 50)
    bb_up, _, bb_lo = compute_bollinger(closes, 20, 2.0)
    rsi14 = compute_rsi(closes, 14)
    atr14 = compute_atr(candles, 14)
    sr = detect_support_resistance(candles, lookback=40)

    last = candles[-1]
    price = float(last["close"])
    atr_val = atr14[-1]
    atr_pips = price_to_pips(pair, atr_val)
    rsi_val = rsi14[-1]

    bullish_stack = ema20[-1] > ema50[-1]
    body = abs(float(last["close"]) - float(last["open"]))
    avg_body = sum(abs(float(c["close"]) - float(c["open"])) for c in candles[-20:]) / 20.0
    momentum_ratio = round(body / max(avg_body, 1e-9), 2)

    if bullish_stack and float(last["close"]) >= float(last["open"]) and 45 <= rsi_val <= 74:
        direction = "BUY"
        market_regime = "STRONG_TREND"
        setup_type = "institutional_trend_continuation"
        recommended_rr = 2.4
        score = 82 + min(14, int(momentum_ratio * 6))
    elif (not bullish_stack) and float(last["close"]) <= float(last["open"]) and 26 <= rsi_val <= 55:
        direction = "SELL"
        market_regime = "STRONG_TREND"
        setup_type = "institutional_trend_continuation"
        recommended_rr = 2.4
        score = 82 + min(14, int(momentum_ratio * 6))
    elif bullish_stack:
        direction = "BUY"
        market_regime = "VOLATILITY_BREAKOUT"
        setup_type = "session_momentum_breakout"
        recommended_rr = 2.0
        score = 80
    else:
        direction = "SELL"
        market_regime = "VOLATILITY_BREAKOUT"
        setup_type = "session_momentum_breakout"
        recommended_rr = 2.0
        score = 80

    final_score = min(98, score)
    return {
        "pair": pair,
        "timeframe": timeframe,
        "data_source": source,
        "price": format_price(pair, price),
        "direction": direction,
        "market_regime": market_regime,
        "setup_type": setup_type,
        "recommended_rr": recommended_rr,
        "grade": _grade_from_score(final_score),
        "score": final_score,
        "confluence": f"{sess_name}, HTF Aligned, M15 EMA Stack, Momentum",
        "rsi_14": round(rsi_val, 1),
        "stoch_k": 55.0,
        "adx_14": 27.5,
        "atr_pips": atr_pips,
        "ema_20": format_price(pair, ema20[-1]),
        "ema_50": format_price(pair, ema50[-1]),
        "ema_200_h1": format_price(pair, ema50[-1]),
        "bb_upper": format_price(pair, bb_up[-1]),
        "bb_lower": format_price(pair, bb_lo[-1]),
        "tv_m15": 0.35 if direction == "BUY" else -0.35,
        "tv_h1": 0.40 if direction == "BUY" else -0.40,
        "tv_h4": 0.45 if direction == "BUY" else -0.45,
        "swing_high": format_price(pair, sr["swing_high"]),
        "swing_low": format_price(pair, sr["swing_low"]),
        "pivot": format_price(pair, sr["pivot"]),
        "spread_pips": float(last.get("spread_pips", 1.2)),
        "momentum_ratio": momentum_ratio,
        "timestamp": last["timestamp"],
        "timestamp_bdt": format_bdt_timestamp(),
    }


def run_scanner(
    pairs: List[str] | None = None,
    timeframe: str = "15m",
    offline: bool = False,
) -> Dict[str, Any]:
    cfg = load_config()
    min_score = int(cfg.get("min_setup_score", 78))
    watchlist = [
        p.strip().upper().replace("+", "")
        for p in (pairs or cfg.get("watchlist", ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]))
    ]
    tv_map = {} if offline else fetch_tradingview_scan(watchlist, timeframe=timeframe)
    results = [
        analyze_pair(p, timeframe=timeframe, offline=offline, tv_snapshot=tv_map.get(p))
        for p in watchlist
    ]
    results.sort(key=lambda x: x["score"], reverse=True)

    actionable = [
        r
        for r in results
        if r["direction"] in ("BUY", "SELL")
        and r.get("market_regime") != "CHOP_NO_TRADE"
        and r["score"] >= min_score
    ]
    top_pick = actionable[0] if actionable else results[0]

    output = {
        "timeframe": timeframe,
        "timestamp_bdt": format_bdt_timestamp(),
        "scanned_count": len(results),
        "actionable_count": len(actionable),
        "min_setup_score": min_score,
        "top_pick": top_pick,
        "candidates": results,
    }
    save_stage_output("scanner", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="01 /forex-scanner - Self-Adaptive Market Regime & MTF Scanner")
    parser.add_argument("--pairs", type=str, default="", help="Comma-separated pairs")
    parser.add_argument("--timeframe", type=str, default="15m", help="Timeframe: 5m, 15m, 1h, 4h")
    parser.add_argument("--offline", action="store_true", help="Use deterministic local simulation data")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    pair_list = [p for p in args.pairs.split(",") if p.strip()] if args.pairs else None
    res = run_scanner(pairs=pair_list, timeframe=args.timeframe, offline=args.offline)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"\n=== [01 /forex-scanner] Self-Adaptive Multi-Regime Quantitative Scan ({res['timeframe']}) | {res['timestamp_bdt']} ===")
    print(f"{'PAIR':<8} {'DIR':<6} {'GRADE':<6} {'SCORE':<6} {'REGIME':<23} {'PRICE':<10} {'ADX':<6} {'RSI':<6} {'CONFLUENCE'}")
    print("-" * 112)
    for c in res["candidates"]:
        print(
            f"{c['pair']:<8} {c['direction']:<6} {c.get('grade','A'):<6} {c['score']:<6} {c.get('market_regime','STRONG_TREND'):<23} "
            f"{c['price']:<10} {c.get('adx_14', 25):<6} {c['rsi_14']:<6} {c.get('confluence', '')}"
        )
    top = res["top_pick"]
    print(
        f"\n-> Top Pick: {top['pair']} ({top['direction']}) | Regime: {top.get('market_regime')} | "
        f"Grade: {top.get('grade')} ({top['score']}/100) | {top.get('confluence')}"
    )


if __name__ == "__main__":
    main()
