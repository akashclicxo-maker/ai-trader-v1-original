---
name: forex-macro
description: Computes the 8-Currency Strength Meter (CSM), Central Bank Rate Differentials, and Macro Bias alignment.
---

# 03 `/forex-macro`

Evaluates macro currency strength (`USD`, `EUR`, `GBP`, `JPY`, `AUD`, `CAD`, `CHF`, `NZD`, `XAU`) and Central Bank monetary policy stances (Fed, ECB, BOE, BOJ, RBA, BOC, SNB, RBNZ) to confirm or filter the scanner's setup.

## Usage
```bash
python forex-macro/macro.py --pair EURUSD
```

## Output
Saves `trader/state/macro.json` with `currency_strength_meter` and `macro_aligned`.
