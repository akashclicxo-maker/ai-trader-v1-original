# Forex 11-Agent Autonomous Trading System (`forex-trader-skill`)

An institutional-style, 11-agent autonomous Forex trading architecture adapted from the `day-trader-skill` blueprint—purpose-built for **Forex pairs (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCAD`, `USDCHF`, `NZDUSD`) and Gold (`XAUUSD`)**.

Uses **Python 3.8+ standard library** out-of-the-box with zero external package requirements, defaults to **Paper Trading**, and enforces a **7-rule Deterministic Risk Gatekeeper**.

---

## Architecture & Trade Flow

```text
01 /forex-scanner  ->  02 /forex-calendar  ->  03 /forex-macro      ->  04 /forex-entry
       |                                                                      |
       v                                                                      v
08 /forex-risk     <-  07 /forex-budget    <-  06 /forex-timemachine <-  05 /forex-exit
       |
       v
09 /forex-broker   ->  10 /forex-manager   ->  11 /forex-alerts
```

| # | Agent Skill | Script | Responsibility |
| :- | :--- | :--- | :--- |
| **01** | `/forex-scanner` | `forex-scanner/scan.py` | Scans 8 major pairs + Gold for London/NY breakouts, pullbacks, and liquidity sweeps. |
| **02** | `/forex-calendar` | `forex-calendar/calendar_watch.py` | Scrapes ForexFactory high-impact news (CPI, NFP, FOMC/ECB) and triggers $\pm 30\text{m}$ blackouts. |
| **03** | `/forex-macro` | `forex-macro/macro.py` | Computes the 8-Currency Strength Meter (CSM) & Central Bank interest rate differentials. |
| **04** | `/forex-entry` | `forex-entry/entry.py` | Evaluates bar-by-bar candle conviction & EMA20 distance (`MARKET` vs `LIMIT`). |
| **05** | `/forex-exit` | `forex-exit/exit.py` | Calculates ATR-based Stop Loss (in pips) and multi-tier Take Profits (`1R`, `2R`, `3R`). |
| **06** | `/forex-timemachine` | `forex-timemachine/timemachine.py` | Runs 10,000 Monte Carlo sessions & historical candle replays before taking a trade. |
| **07** | `/forex-budget` | `forex-budget/sizer.py` | Calculates exact Forex lot sizes (`0.01` micro-lot precision) capped at `max_loss_per_trade_usd`. |
| **08** | `/forex-risk` | `forex-risk/risk_guardian.py` | Verifies 7 hard safety rules (`PASS` or `BLOCK`): News blackout, spread filter, daily drawdown. |
| **09** | `/forex-broker` | `forex-broker/broker.py` | Executes `PASS` orders to the Paper Trading Ledger (or MT5 / OANDA). |
| **10** | `/forex-manager` | `forex-manager/manager.py` | Moves SL to Break-Even at $+1R$, takes 50% partial profits, and handles emergency flatten. |
| **11** | `/forex-alerts` | `forex-alerts/alerts.py` | Logs audit reports to `trader/state/alerts_log.txt` and broadcasts to Telegram. |

---

## Quickstart Commands

### 1. Run Offline Unit Test Suite
```powershell
python -m unittest discover -s tests -v
```

### 2. Run the Full 11-Agent Pipeline
```powershell
# Run with live data (falls back to simulation if offline)
python run_pipeline.py

# Run in deterministic offline mode
python run_pipeline.py --offline

# Run continuously every 15 minutes (900 seconds)
python run_pipeline.py --loop --interval 900
```

### 3. Run Individual Agents Directly
```powershell
python forex-scanner/scan.py --timeframe 15m
python forex-calendar/calendar_watch.py --pair EURUSD
python forex-macro/macro.py --pair EURUSD
python forex-entry/entry.py --pair EURUSD --direction SELL
python forex-exit/exit.py --pair EURUSD --direction SELL --rr 2.0
python forex-timemachine/timemachine.py --pair EURUSD --sims 10000
python forex-budget/sizer.py --pair EURUSD --balance 10000 --risk 1.0 --sl-pips 20
python forex-risk/risk_guardian.py
python forex-broker/broker.py --status
python forex-manager/manager.py --simulate-r 1.2
python forex-alerts/alerts.py
```
