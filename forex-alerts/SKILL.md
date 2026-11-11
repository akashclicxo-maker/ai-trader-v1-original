---
name: forex-alerts
description: Formats trade execution, SL/TP, and risk block notifications, logs them to trader/state/alerts_log.txt, and broadcasts to Telegram.
---

# 11 `/forex-alerts`

Generates structured audit notifications for every pipeline run and sends real-time mobile alerts via Telegram if `telegram.enabled` is set to `true` in `config.json`.

## Usage
```bash
python forex-alerts/alerts.py
```

## Output
Saves `trader/state/alerts.json` and appends to `trader/state/alerts_log.txt`.
