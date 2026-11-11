---
name: forex-manager
description: Actively manages open Forex trades with automatic Break-Even shifts at +1R, 50% partial profit taking, and emergency flatten controls.
---

# 10 `/forex-manager`

Monitors every open trade in `trader/state/paper_ledger.json`:
- **At $+1.0R$ (`tp1_1r`):** Moves Stop Loss to entry price (Break-Even) and locks in 50% partial profits.
- **At $+2.0R$ (`tp2_primary`):** Closes remaining position at target profit.
- **Emergency Flatten (`--flatten-all`):** Closes all open positions before Friday market close or major macro shocks.

## Usage
```bash
python forex-manager/manager.py
python forex-manager/manager.py --simulate-r 1.2
python forex-manager/manager.py --flatten-all
```

## Output
Saves `trader/state/manager.json` and updates `trader/state/paper_ledger.json`.
