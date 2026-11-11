---
name: forex-scanner
description: Scans major Forex pairs and Gold (XAUUSD) for London/NY Session Breakouts, Trend Pullbacks, and Liquidity Sweeps.
---

# 01 `/forex-scanner`

Scans your watchlist (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCAD`, `USDCHF`, `NZDUSD`, `XAUUSD`) across multi-timeframe candles to identify high-probability setups.

## Usage
```bash
python forex-scanner/scan.py --timeframe 15m
python forex-scanner/scan.py --pairs EURUSD,GBPUSD,XAUUSD --json
```

## Output
Writes ranked setups to `trader/state/scanner.json` and passes the top candidate to `/forex-calendar` and `/forex-macro`.
