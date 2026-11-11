#!/usr/bin/env python3
"""
Agent 11: /forex-alerts
Formats trade execution & risk alerts, logs them to trader/state/alerts_log.txt,
and broadcasts to Telegram if enabled in config.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_core.market_data import (
    STATE_DIR,
    load_config,
    load_stage_output,
    save_stage_output,
)

ALERT_LOG_PATH = STATE_DIR / "alerts_log.txt"


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def dispatch_alerts() -> Dict[str, Any]:
    cfg = load_config()
    scanner = load_stage_output("scanner") or {}
    calendar = load_stage_output("calendar") or {}
    macro = load_stage_output("macro") or {}
    exit_s = load_stage_output("exit") or {}
    tm = load_stage_output("timemachine") or {}
    budget = load_stage_output("budget") or {}
    risk = load_stage_output("risk") or {}
    broker = load_stage_output("broker") or {}
    manager = load_stage_output("manager") or {}

    top = scanner.get("top_pick", {})
    pair = exit_s.get("pair") or top.get("pair") or "EURUSD"
    direction = exit_s.get("direction") or top.get("direction") or "BUY"
    risk_decision = risk.get("decision", "BLOCK")
    now_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if risk_decision == "PASS" and broker.get("executed"):
        order = broker.get("order", {})
        msg = (
            f"[FOREX AI SIGNAL EXECUTED] {now_str}\n"
            f"Pair: {pair} | Action: {order.get('order_type', direction)}\n"
            f"Size: {order.get('lots', 0.1):.2f} Lots (Risk: ${order.get('risk_usd', 0):.2f})\n"
            f"Entry: {order.get('entry_price')} | SL: {order.get('stop_loss')} (-{exit_s.get('stop_loss_pips')}p)\n"
            f"TP1 (1R BE): {order.get('tp1_1r')} | TP2: {order.get('tp2_primary')} ({exit_s.get('reward_to_risk')}R)\n"
            f"TimeMachine WinRate: {tm.get('simulated_win_rate', 0) * 100:.1f}% (EV: {tm.get('expected_value_r', 0):+.2f}R)\n"
            f"Macro Bias: {macro.get('macro_bias')} | News Status: {calendar.get('risk_status')}\n"
            f"Ticket: {order.get('ticket_id')} ({order.get('broker_mode', 'paper').upper()})"
        )
    else:
        reasons = ", ".join(risk.get("blocking_reasons", ["No trade triggered"]))
        msg = (
            f"[FOREX AI RISK BLOCK] {now_str}\n"
            f"Pair: {pair} ({direction}) | Risk Verdict: {risk_decision}\n"
            f"Blocked Reason: {reasons}"
        )

    if manager.get("actions_taken"):
        msg += "\nTrade Manager: " + "; ".join(manager["actions_taken"])

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n" + ("-" * 60) + "\n")

    tg_cfg = cfg.get("telegram", {})
    tg_sent = False
    if tg_cfg.get("enabled"):
        tg_sent = send_telegram_message(
            str(tg_cfg.get("bot_token", "")),
            str(tg_cfg.get("chat_id", "")),
            msg,
        )

    output = {
        "timestamp": now_str,
        "pair": pair,
        "risk_decision": risk_decision,
        "telegram_sent": tg_sent,
        "log_file": str(ALERT_LOG_PATH),
        "alert_message": msg,
    }
    save_stage_output("alerts", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="11 /forex-alerts - Trade Alert Dispatcher & Logger")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    res = dispatch_alerts()
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print("\n=== [11 /forex-alerts] Alert Broadcast ===")
    print(res["alert_message"])


if __name__ == "__main__":
    main()
