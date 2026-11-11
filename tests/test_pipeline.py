#!/usr/bin/env python3
"""
Unit & Integration Tests for the 11-Agent Forex Trading System.
Run with: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from forex_core.market_data import STATE_DIR
from run_pipeline import _load_agent_module, run_full_pipeline


class TestForexTradingAgents(unittest.TestCase):
    def setUp(self) -> None:
        ledger_path = STATE_DIR / "paper_ledger.json"
        if ledger_path.exists():
            ledger_path.unlink()

    def test_01_scanner_finds_ranked_candidates(self) -> None:
        scan_mod = _load_agent_module("forex-scanner/scan.py", "forex_scanner")
        res = scan_mod.run_scanner(pairs=["EURUSD", "GBPUSD", "XAUUSD"], timeframe="15m", offline=True)
        self.assertEqual(res["scanned_count"], 3)
        self.assertIn("top_pick", res)
        self.assertIn(res["top_pick"]["pair"], ["EURUSD", "GBPUSD", "XAUUSD"])
        self.assertGreaterEqual(res["top_pick"]["score"], 35)

    def test_02_calendar_red_folder_blackout(self) -> None:
        cal_mod = _load_agent_module("forex-calendar/calendar_watch.py", "forex_calendar")
        clear_res = cal_mod.check_calendar(pair="EURUSD", offline=True, simulate_red_news_now=False)
        self.assertFalse(clear_res["blackout_active"])

        red_res = cal_mod.check_calendar(pair="EURUSD", offline=True, simulate_red_news_now=True)
        self.assertTrue(red_res["blackout_active"])
        self.assertEqual(red_res["risk_status"], "HIGH_BLACKOUT")

    def test_03_macro_currency_strength_meter(self) -> None:
        macro_mod = _load_agent_module("forex-macro/macro.py", "forex_macro")
        res = macro_mod.analyze_macro(pair="EURUSD", offline=True)
        self.assertIn("currency_strength_meter", res)
        self.assertIn("USD", res["currency_strength_meter"])
        self.assertIn("EUR", res["currency_strength_meter"])

    def test_04_and_05_entry_and_exit_planning(self) -> None:
        entry_mod = _load_agent_module("forex-entry/entry.py", "forex_entry")
        exit_mod = _load_agent_module("forex-exit/exit.py", "forex_exit")

        e_res = entry_mod.evaluate_entry(pair="EURUSD", direction="BUY", offline=True)
        self.assertEqual(e_res["pair"], "EURUSD")

        x_res = exit_mod.plan_exit(pair="EURUSD", direction="BUY", entry_price=1.0850, atr_pips=14.0, rr_target=2.0)
        self.assertLess(x_res["stop_loss_price"], x_res["entry_price"])
        self.assertGreater(x_res["tp2_price_primary"], x_res["tp1_price_1r"])
        self.assertEqual(x_res["reward_to_risk"], 2.0)

    def test_06_timemachine_10000_simulations(self) -> None:
        tm_mod = _load_agent_module("forex-timemachine/timemachine.py", "forex_timemachine")
        res = tm_mod.run_timemachine(
            pair="EURUSD", direction="BUY", sl_pips=18.0, tp_pips=36.0, simulations=10000, offline=True
        )
        self.assertEqual(res["simulations_run"], 10000)
        self.assertGreater(res["simulated_win_rate"], 0.0)

    def test_07_budget_lot_sizing_respects_risk_cap(self) -> None:
        budget_mod = _load_agent_module("forex-budget/sizer.py", "forex_budget")
        res = budget_mod.calculate_lot_size(pair="EURUSD", balance_usd=10000.0, risk_pct=1.0, max_loss_usd=100.0, sl_pips=20.0)
        self.assertEqual(res["recommended_lots"], 0.50)
        self.assertLessEqual(res["actual_risk_usd"], 100.0)

    def test_08_risk_blocks_wide_spread(self) -> None:
        run_full_pipeline(pair="EURUSD", offline=True, verbose=False)
        risk_mod = _load_agent_module("forex-risk/risk_guardian.py", "forex_risk")
        blocked = risk_mod.evaluate_risk(simulate_spread_spike=5.0)
        self.assertEqual(blocked["decision"], "BLOCK")
        self.assertFalse(blocked["passed"])

    def test_09_and_10_full_pipeline_and_breakeven_management(self) -> None:
        summary = run_full_pipeline(pair="EURUSD", offline=True, verbose=False)
        self.assertEqual(summary["risk"]["decision"], "PASS")
        self.assertTrue(summary["broker"]["executed"])

        mgr_mod = _load_agent_module("forex-manager/manager.py", "forex_manager")
        # Simulate price reaching +1.2R -> should shift Stop Loss to Break-Even and close partial profit
        m_res = mgr_mod.manage_open_trades(simulate_price_move_r=1.2, offline=True)
        self.assertEqual(m_res["remaining_open_count"], 1)
        open_pos = m_res["open_positions"][0]
        self.assertTrue(open_pos["breakeven_active"])
        self.assertEqual(open_pos["stop_loss"], open_pos["entry_price"])


if __name__ == "__main__":
    unittest.main()
