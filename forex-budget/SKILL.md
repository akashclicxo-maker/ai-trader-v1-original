---
name: forex-budget
description: Calculates exact Forex lot sizes (Standard, Mini, Micro lots) based on account budget, max loss per trade cap, stop-loss pips, and pip value.
---

# 07 `/forex-budget`

Determines the exact position size in lots (`0.01` micro-lot precision) so your dollar risk never exceeds `max_loss_per_trade_usd` or `risk_per_trade_pct` in `config.json`.

## Usage
```bash
python forex-budget/sizer.py --pair EURUSD --balance 10000 --risk 1.0 --sl-pips 20
```

## Output
Saves `trader/state/budget.json` with `recommended_lots`, `units`, and `actual_risk_usd`.
