---
name: forex-broker
description: Executes risk-approved Forex orders to the Paper Trading Ledger (default), MetaTrader 5 (MT5), or OANDA.
---

# 09 `/forex-broker`

Routes approved orders to the broker. Refuses to execute unless `/forex-risk` returned `PASS`. By default, `paper: true` is active so all trades are recorded safely in `trader/state/paper_ledger.json`.

## Usage
```bash
python forex-broker/broker.py --yes
python forex-broker/broker.py --status
python forex-broker/broker.py --reset-ledger
```

## Output
Saves `trader/state/broker.json` and updates `trader/state/paper_ledger.json`.
