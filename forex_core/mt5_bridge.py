"""
Python Bridge to the compiled MQL5 Expert Advisor (ForexAIBridge.ex5)
via MetaQuotes Common\\Files directory.
Includes Anti-Stacking Guard, Duplicate Position Cleaner, Pre-News Profit Shield,
Break-Even + Cushion Lock at +1.0R, and Dynamic Trailing Stop at +1.5R.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from forex_core.market_data import format_price, get_pip_size, load_stage_output

COMMON_FILES_DIR = (
    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    / "MetaQuotes"
    / "Terminal"
    / "Common"
    / "Files"
)
STATE_FILE = COMMON_FILES_DIR / "forex_ai_mt5_state.json"
CMD_FILE = COMMON_FILES_DIR / "forex_ai_cmd.txt"
ACK_FILE = COMMON_FILES_DIR / "forex_ai_ack.txt"


def clean_pair_name(sym: str) -> str:
    s = str(sym).upper().replace("/", "").replace("+", "")
    for sfx in (".PC", ".P", ".R", ".A", ".PRO", ".ECN"):
        if s.endswith(sfx):
            s = s[: -len(sfx)]
    return s[:6]


def read_mt5_state(max_age_seconds: float = 15.0) -> Optional[Dict[str, Any]]:
    """
    Reads live MT5 account & position state written by ForexAIBridge.ex5.
    Returns None if the EA is not currently attached/running in MT5.
    """
    if not STATE_FILE.exists():
        return None
    try:
        mtime = STATE_FILE.stat().st_mtime
        if (time.time() - mtime) > max_age_seconds:
            return None
        raw = STATE_FILE.read_text(encoding="utf-8", errors="ignore").strip()
        if not raw:
            return None
        data = json.loads(raw)
        if data.get("connected"):
            return data
    except Exception:
        return None
    return None


def send_mt5_command(line: str, wait_ack_sec: float = 2.0) -> Dict[str, Any]:
    """
    Sends a pipe-delimited command line to ForexAIBridge.ex5 in Common\\Files
    and optionally waits up to wait_ack_sec for the execution acknowledgement.
    """
    COMMON_FILES_DIR.mkdir(parents=True, exist_ok=True)
    parts = line.split("|")
    cmd_id = parts[1] if len(parts) > 1 else uuid.uuid4().hex[:8]

    if ACK_FILE.exists():
        try:
            ACK_FILE.unlink()
        except Exception:
            pass

    with open(CMD_FILE, "a", encoding="utf-8") as f:
        f.write(line.strip() + "\n")

    deadline = time.time() + wait_ack_sec
    while time.time() < deadline:
        if ACK_FILE.exists():
            try:
                ack_raw = ACK_FILE.read_text(encoding="utf-8", errors="ignore").strip()
                if ack_raw:
                    ack = json.loads(ack_raw)
                    if ack.get("cmd_id") == cmd_id:
                        return ack
            except Exception:
                pass
        time.sleep(0.08)

    return {"cmd_id": cmd_id, "status": "QUEUED_TO_MT5", "ticket": 0, "message": "Command dispatched to MT5"}


def send_mt5_open_order(
    pair: str,
    direction: str,
    lots: float,
    sl_pips: float,
    tp_pips: float,
    max_per_pair: int = 1,
) -> Dict[str, Any]:
    clean_pair = clean_pair_name(pair)
    mt5_state = read_mt5_state()
    suffix = "+"
    if mt5_state:
        open_positions = mt5_state.get("open_positions", [])
        same_pair_count = sum(1 for p in open_positions if clean_pair_name(p.get("pair", "")) == clean_pair)
        if same_pair_count >= max_per_pair:
            return {
                "cmd_id": "ANTI-STACK",
                "status": "ERROR",
                "ticket": 0,
                "message": f"Anti-Stacking Guard: {clean_pair} already has {same_pair_count} active trade(s)",
            }
        for pos in open_positions:
            sym = str(pos.get("pair", ""))
            if len(sym) > 6:
                suffix = sym[6:]
                break
    broker_pair = f"{clean_pair}{suffix}"

    cmd_id = f"CMD-{uuid.uuid4().hex[:6].upper()}"
    line = f"OPEN|{cmd_id}|{broker_pair}|{direction.upper()}|{lots:.2f}|{sl_pips:.1f}|{tp_pips:.1f}"
    ack = send_mt5_command(line, wait_ack_sec=1.5)

    if ack.get("status") == "ERROR" and "Anti-Stacking" not in str(ack.get("message", "")):
        time.sleep(0.5)
        cmd_id2 = f"CMD-{uuid.uuid4().hex[:6].upper()}"
        line2 = f"OPEN|{cmd_id2}|{broker_pair}|{direction.upper()}|{lots:.2f}|{sl_pips:.1f}|{tp_pips:.1f}"
        ack = send_mt5_command(line2, wait_ack_sec=1.5)
    return ack


def send_mt5_close_ticket(raw_ticket: int) -> Dict[str, Any]:
    cmd_id = f"CMD-{uuid.uuid4().hex[:6].upper()}"
    return send_mt5_command(f"CLOSE|{cmd_id}|{int(raw_ticket)}", wait_ack_sec=0.8)


def send_mt5_flatten_all() -> Dict[str, Any]:
    cmd_id = f"CMD-{uuid.uuid4().hex[:6].upper()}"
    return send_mt5_command(f"FLATTEN|{cmd_id}", wait_ack_sec=1.5)


def send_mt5_breakeven(raw_ticket: int) -> Dict[str, Any]:
    cmd_id = f"CMD-{uuid.uuid4().hex[:6].upper()}"
    return send_mt5_command(f"BREAKEVEN|{cmd_id}|{int(raw_ticket)}", wait_ack_sec=0.8)


def send_mt5_modify_sl_tp(raw_ticket: int, new_sl: float, new_tp: float = 0.0) -> Dict[str, Any]:
    cmd_id = f"CMD-{uuid.uuid4().hex[:6].upper()}"
    return send_mt5_command(f"MODIFY|{cmd_id}|{int(raw_ticket)}|{new_sl:.5f}|{new_tp:.5f}", wait_ack_sec=0.8)


def deduplicate_mt5_positions(max_per_pair: int = 1) -> List[str]:
    """
    Finds any currency pair with more than `max_per_pair` open positions in MT5,
    keeps the highest-PnL position for that pair, and closes the duplicates.
    """
    mt5_state = read_mt5_state()
    if not mt5_state:
        return []

    by_pair: Dict[str, List[Dict[str, Any]]] = {}
    for pos in mt5_state.get("open_positions", []):
        cp = clean_pair_name(pos.get("pair", ""))
        by_pair.setdefault(cp, []).append(pos)

    closed_logs: List[str] = []
    lines_to_send: List[str] = []
    for cp, plist in by_pair.items():
        if len(plist) > max_per_pair:
            plist.sort(key=lambda x: float(x.get("unrealized_pnl_usd", 0.0)), reverse=True)
            to_close = plist[max_per_pair:]
            for dup in to_close:
                raw_t = int(dup.get("raw_ticket", 0))
                if raw_t > 0:
                    cid = f"DEDUP-{uuid.uuid4().hex[:5].upper()}"
                    lines_to_send.append(f"CLOSE|{cid}|{raw_t}")
                    closed_logs.append(f"Closed duplicate {dup.get('pair')} #{raw_t} (keeping best 1 trade/pair)")

    if lines_to_send:
        COMMON_FILES_DIR.mkdir(parents=True, exist_ok=True)
        with open(CMD_FILE, "a", encoding="utf-8") as f:
            for l in lines_to_send:
                f.write(l + "\n")
    return closed_logs


def manage_live_mt5_positions() -> List[str]:
    """
    Autonomous Live MT5 Trade Manager:
    1. Pre-News Profit Shield: If ForexFactory flags high-impact news within 20m for an open
       pair that is in profit, immediately locks Stop Loss at Break-Even.
    2. +1.0R Break-Even Lock: When price reaches +1.0R, moves Stop Loss to Entry + cushion.
    3. +1.5R Dynamic Trailing Stop: When price reaches +1.5R+, trails Stop Loss dynamically
       behind current price (0.75R trail distance) to lock in growing profit.
    """
    mt5_state = read_mt5_state()
    if not mt5_state:
        return []

    cal_state = load_stage_output("calendar") or {}
    imminent_news_currencies = set(cal_state.get("imminent_high_impact_currencies", []))

    actions: List[str] = []
    for pos in mt5_state.get("open_positions", []):
        raw_t = int(pos.get("raw_ticket", 0))
        pair_raw = str(pos.get("pair", "EURUSD"))
        clean_p = clean_pair_name(pair_raw)
        entry = float(pos.get("entry_price", 0.0))
        cur = float(pos.get("current_price", 0.0))
        sl = float(pos.get("stop_loss", 0.0))
        tp = float(pos.get("tp2_primary", 0.0))
        pnl = float(pos.get("unrealized_pnl_usd", 0.0))
        direction = str(pos.get("direction", "BUY")).upper()
        if raw_t <= 0 or entry <= 0 or tp <= 0:
            continue

        pip = get_pip_size(clean_p)
        tp_dist = abs(tp - entry)
        if tp_dist <= 0:
            continue

        one_r_dist = tp_dist * 0.50
        gain_dist = (cur - entry) if direction == "BUY" else (entry - cur)

        # 1. Pre-News Shield: High-impact news within 20m and position is in profit
        pair_curs = {"USD"} if "XAU" in clean_p else {clean_p[:3], clean_p[3:6]}
        if (pair_curs & imminent_news_currencies) and pnl > 1.0 and not pos.get("breakeven_active"):
            send_mt5_breakeven(raw_t)
            actions.append(
                f"MT5 #{raw_t} ({pair_raw}): Pre-News Shield Active (Red-Folder News <20m) -> Locked SL at Break-Even ({entry})"
            )
            continue

        # 2. Dynamic Trailing Stop at >= +1.5R
        if gain_dist >= (one_r_dist * 1.5):
            trail_dist = one_r_dist * 0.75
            if direction == "BUY":
                desired_sl = format_price(clean_p, cur - trail_dist)
                if desired_sl > sl + (2.0 * pip):
                    send_mt5_modify_sl_tp(raw_t, desired_sl, tp)
                    actions.append(
                        f"MT5 #{raw_t} ({pair_raw}): +1.5R+ Dynamic Trail -> Ratcheted SL up to {desired_sl}"
                    )
            else:
                desired_sl = format_price(clean_p, cur + trail_dist)
                if sl <= 0 or desired_sl < sl - (2.0 * pip):
                    send_mt5_modify_sl_tp(raw_t, desired_sl, tp)
                    actions.append(
                        f"MT5 #{raw_t} ({pair_raw}): +1.5R+ Dynamic Trail -> Ratcheted SL down to {desired_sl}"
                    )
            continue

        # 3. Break-Even Lock at >= +1.0R
        if gain_dist >= one_r_dist and not pos.get("breakeven_active"):
            send_mt5_breakeven(raw_t)
            actions.append(
                f"MT5 #{raw_t} ({pair_raw}): +1.0R reached -> Locked Stop Loss at Break-Even ({entry})"
            )

    return actions
