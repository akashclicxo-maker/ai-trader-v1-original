---
name: forex-exit
description: Plans ATR-based Stop Loss (in pips) and multi-tier Take Profit targets (1R, 2R, 3R) before any trade is placed.
---

# 05 `/forex-exit`

Calculates the Stop Loss distance in pips using $1.5 \times \text{ATR}_{14}$ and defines three Take Profit levels:
- **TP1 ($1.0R$):** Move Stop Loss to Break-Even and close partial position.
- **TP2 ($2.0R$):** Primary target.
- **TP3 ($3.0R$):** Trend runner target.

## Usage
```bash
python forex-exit/exit.py --pair EURUSD --direction BUY --rr 2.0
```

## Output
Saves `trader/state/exit.json`.
