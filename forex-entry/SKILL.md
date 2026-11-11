---
name: forex-entry
description: Evaluates bar-by-bar price action, candlestick body conviction, and EMA value zones to pin down the exact entry trigger and order type.
---

# 04 `/forex-entry`

Inspects the M15/H1 candle structure for the candidate setup from `/forex-scanner` to determine whether to execute a `MARKET` order immediately or place a `LIMIT` pullback order.

## Usage
```bash
python forex-entry/entry.py --pair EURUSD --direction BUY
```

## Output
Writes `trader/state/entry.json` with `entry_price`, `order_type`, and `entry_ready`.
