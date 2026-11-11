---
name: forex-timemachine
description: Replays historical candle occurrences and runs 10,000 Monte Carlo simulated sessions to verify positive expectancy before taking a trade.
---

# 06 `/forex-timemachine`

Simulates 10,000 sessions of the planned setup (`stop_loss_pips` vs `tp2_pips`) and replays historical occurrences on recent candles to verify that the trade has a positive mathematical edge ($EV > +0.15R$).

## Usage
```bash
python forex-timemachine/timemachine.py --pair EURUSD --sims 10000
```

## Output
Saves `trader/state/timemachine.json` with `simulated_win_rate`, `expected_value_r`, and `verdict`.
