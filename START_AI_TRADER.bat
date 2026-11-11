@echo off
title Forex 24/7 Standalone Quantitative Engine (BDT Time)
cd /d "%~dp0"
echo ============================================================================
echo   FOREX 24/7 STANDALONE QUANTITATIVE TRADING ENGINE (BDT TIME)
echo   Dashboard URL: http://localhost:8080
echo   Status: Active & Connected to MetaTrader 5
echo ============================================================================
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8080 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
start "" "http://localhost:8080"
python dashboard.py
pause
