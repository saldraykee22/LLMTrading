@echo off
title LLM Trading System - Launcher

:: LLM Trading System - Easy Launcher Script
:: ===========================================

echo.
echo +====================================================================+
echo ^|           LLM TRADING SYSTEM - LAUNCHER                            ^|
echo ^|                     v2.0.0                                         ^|
echo +====================================================================+
echo.

:: Check Python installation
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.10+.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [INFO] Python found: 
python --version
echo.

:: Virtual environment check
if not exist "venv\Scripts\activate.bat" (
    echo [WARN] Virtual environment not found!
    echo Creating...
    python -m venv venv
    echo [INFO] Virtual environment created.
    echo.
)

:: Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat
echo.

:: Check dependencies
echo [INFO] Checking dependencies...
if exist "requirements.txt" (
    pip install -q -r requirements.txt
    echo [OK] Dependencies installed.
)
echo.

:: Main menu
:MENU
cls
echo.
echo +====================================================================+
echo ^|                        MAIN MENU                                   ^|
echo +====================================================================+
echo.
echo  1) Health Check
echo  2) Paper Trading - BTC/USDT (1H candles)
echo  3) Paper Trading - BTC/USDT (15M candles)
echo  4) Paper Trading - Custom
echo  5) Live Trading (CAUTION!)
echo  6) Run Backtest
echo  7) Portfolio Status
echo  8) Test Suite
echo  9) Show Logs
echo.
echo  0) Exit
echo.
echo ====================================================================
echo.

set /p choice="Your choice (0-9): "

if "%choice%"=="1" goto HEALTH_CHECK
if "%choice%"=="2" goto PAPER_TRADING_1H
if "%choice%"=="3" goto PAPER_TRADING_15M
if "%choice%"=="4" goto PAPER_TRADING_CUSTOM
if "%choice%"=="5" goto LIVE_TRADING
if "%choice%"=="6" goto BACKTEST
if "%choice%"=="7" goto PORTFOLIO
if "%choice%"=="8" goto TESTS
if "%choice%"=="9" goto LOGS
if "%choice%"=="0" goto EXIT

echo [ERROR] Invalid choice!
timeout /t 2 >nul
goto MENU

:HEALTH_CHECK
cls
echo.
echo ====================================================================
echo          RUNNING HEALTH CHECK...
echo ====================================================================
echo.
python scripts\health_check.py
echo.
pause
goto MENU

:PAPER_TRADING_1H
cls
echo.
echo ====================================================================
echo     PAPER TRADING - BTC/USDT (1 Hour Candles)
echo ====================================================================
echo.
echo [INFO] Starting bot... (Press Ctrl+C to stop)
echo.
python scripts\run_live.py --symbol BTC/USDT --interval 1h --watchdog
goto MENU

:PAPER_TRADING_15M
cls
echo.
echo ====================================================================
echo    PAPER TRADING - BTC/USDT (15 Minute Candles)
echo ====================================================================
echo.
echo [INFO] Starting bot... (Press Ctrl+C to stop)
echo.
python scripts\run_live.py --symbol BTC/USDT --interval 15m --watchdog
goto MENU

:PAPER_TRADING_CUSTOM
cls
echo.
echo ====================================================================
echo      CUSTOM PAPER TRADING
echo ====================================================================
echo.
set /p custom_symbol="Symbol (e.g., BTC/USDT, ETH/USDT): "
set /p custom_interval="Interval (5m, 15m, 30m, 1h, 4h): "
set /p custom_watchdog="Watchdog active? (y/n): "

echo.
echo [INFO] Starting bot...
echo Symbol: %custom_symbol%
echo Interval: %custom_interval%

if /i "%custom_watchdog%"=="y" (
    python scripts\run_live.py --symbol %custom_symbol% --interval %custom_interval% --watchdog
) else (
    python scripts\run_live.py --symbol %custom_symbol% --interval %custom_interval%
)
goto MENU

:LIVE_TRADING
cls
echo.
echo ====================================================================
echo           WARNING - LIVE TRADING MODE
echo ====================================================================
echo.
echo This mode trades REAL money!
echo.
echo Before continuing, please verify:
echo.
echo [ ] 1. TRADING_MODE=live in .env file
echo [ ] 2. CONFIRM_LIVE_TRADE=true in .env file
echo [ ] 3. Binance API keys are correct and active
echo [ ] 4. API permissions: Spot Trading ENABLED
echo [ ] 5. Withdraw permission: DISABLED (security!)
echo [ ] 6. Starting with small amount
echo.
set /p confirm="I verified all items and accept risks (y/n): "

if /i not "%confirm%"=="y" (
    echo.
    echo [CANCEL] Live trading cancelled.
    timeout /t 2 >nul
    goto MENU
)

echo.
set /p live_symbol="Live trading symbol (e.g., BTC/USDT): "
set /p live_interval="Interval (15m, 30m, 1h, 4h): "

echo.
echo [WARNING] LIVE TRADING STARTING!
echo Symbol: %live_symbol%
echo Interval: %live_interval%
echo.
timeout /t 3 >nul

python scripts\run_live.py --symbol %live_symbol% --interval %live_interval% --execute --watchdog
goto MENU

:BACKTEST
cls
echo.
echo ====================================================================
echo              RUNNING BACKTEST...
echo ====================================================================
echo.
set /p bt_symbol="Symbol (e.g., BTC/USDT): "
set /p bt_days="Historical days (e.g., 90): "

echo.
python scripts\run_backtest.py --symbol %bt_symbol% --days %bt_days%
echo.
pause
goto MENU

:PORTFOLIO
cls
echo.
echo ====================================================================
echo              PORTFOLIO STATUS
echo ====================================================================
echo.
if exist "data\portfolio_state.json" (
    type data\portfolio_state.json
) else (
    echo [INFO] No open positions yet.
)
echo.
pause
goto MENU

:TESTS
cls
echo.
echo ====================================================================
echo              RUNNING TEST SUITE...
echo ====================================================================
echo.
python -m pytest tests/test_integration.py -v --tb=short
echo.
pause
goto MENU

:LOGS
cls
echo.
echo ====================================================================
echo              RECENT LOGS
echo ====================================================================
echo.
if exist "logs\trading.log" (
    powershell -Command "Get-Content logs\trading.log -Tail 50"
) else (
    echo [INFO] No log file created yet.
)
echo.
pause
goto MENU

:EXIT
cls
echo.
echo ====================================================================
echo              LLM TRADING SYSTEM
echo                   SHUTTING DOWN...
echo ====================================================================
echo.
echo [INFO] System shut down safely.
echo Goodbye!
echo.
timeout /t 2 >nul
exit /b 0
