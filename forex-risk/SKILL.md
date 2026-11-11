---
name: forex-risk
description: Hard deterministic safety gatekeeper that verifies 7 risk rules (news blackout, spread limit, max daily loss, R:R) and outputs PASS or BLOCK.
---

# 08 `/forex-risk`

Audits every proposed trade against 7 hard safety rules before `/forex-broker` is allowed to execute:
1. Red-Folder News Blackout check ($\pm 30$ mins)
2. Broker Spread Filter ($\le 2.5$ pips)
3. Per-Trade Risk Limit ($\le \$100$)
4. Daily Drawdown Circuit Breaker ($\le \$300$)
5. Max Open Positions & Daily Trade Quota
6. Minimum Reward-to-Risk Ratio ($\ge 1.5R$)
7. TimeMachine Positive Expectancy Check

## Usage
```bash
python forex-risk/risk_guardian.py
python forex-risk/risk_guardian.py --simulate-spread 4.5
```

## Output
Saves `trader/state/risk.json` with `decision: "PASS"` or `"BLOCK"`.
