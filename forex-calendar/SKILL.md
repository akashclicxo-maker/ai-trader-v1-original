---
name: forex-calendar
description: Tracks high-impact Forex economic calendar releases (CPI, NFP, FOMC/ECB/BOE rate decisions) and enforces the News Blackout Window.
---

# 02 `/forex-calendar`

Monitors macroeconomic releases affecting the currencies in your target pair (`USD`, `EUR`, `GBP`, `JPY`, `AUD`, `CAD`, `CHF`, `NZD`). Automatically flags a **News Blackout** $\pm 30$ minutes around Red Folder events.

## Usage
```bash
python forex-calendar/calendar_watch.py --pair EURUSD
python forex-calendar/calendar_watch.py --pair XAUUSD --simulate-red-news
```

## Output
Writes `trader/state/calendar.json` with `blackout_active` (`true`/`false`) for `/forex-risk`.
