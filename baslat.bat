@echo off
chcp 65001 >nul 2>&1
title LLM Trading System - Baslat

:: LLM Trading System - Kolay Baslatma Scripti
:: =============================================

echo.
echo ╔════════════════════════════════════════════════════════╗
echo ║           LLM TRADING SYSTEM - BASLATMA                ║
echo ║                     v2.0.0                             ║
echo ╚════════════════════════════════════════════════════════╝
echo.

:: Python kurulumunu kontrol et
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadi! Lutfen Python 3.10+ yukleyin.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [BILGI] Python bulundu: 
python --version
echo.

:: Virtual environment kontrolu
if not exist "venv\Scripts\activate.bat" (
    echo [UYARI] Virtual environment bulunamadi!
    echo Olusturuluyor...
    python -m venv venv
    echo [BILGI] Virtual environment olusturuldu.
    echo.
)

:: Virtual environment aktif et
echo [BILGI] Virtual environment aktif ediliyor...
call venv\Scripts\activate.bat
echo.

:: Bagimliliklari kontrol et
echo [BILGI] Bagimliliklar kontrol ediliyor...
if exist "requirements.txt" (
    pip install -q -r requirements.txt
    echo [TAMAM] Bagimliliklar yuklu.
)
echo.

:: Ana menu
:MENU
cls
echo.
echo ╔════════════════════════════════════════════════════════╗
echo ║                    ANA MENU                            ║
echo ╚════════════════════════════════════════════════════════╝
echo.
echo  1) Saglik Kontrolu (Health Check)
echo  2) Paper Trading - BTC/USDT (1 saatlik mumlar)
echo  3) Paper Trading - BTC/USDT (15 dakikalik mumlar)
echo  4) Paper Trading - Ozellestirilmis
echo  5) Canli Trading (DİKKAT!)
echo  6) Backtest Calistir
echo  7) Portfoy Durumu
echo  8) Test Suite
echo  9) Loglari Goster
echo.
echo  0) Cikis
echo.
echo ════════════════════════════════════════════════════════
echo.

set /p choice="Seciminiz (0-9): "

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

echo [HATA] Gecersiz secim!
timeout /t 2 >nul
goto MENU

:HEALTH_CHECK
cls
echo.
echo ════════════════════════════════════════════════════════
echo          SAGLIK KONTROLU CALISTIRILIYOR...
echo ════════════════════════════════════════════════════════
echo.
python scripts\health_check.py
echo.
pause
goto MENU

:PAPER_TRADING_1H
cls
echo.
echo ════════════════════════════════════════════════════════
echo     PAPER TRADING - BTC/USDT (1 Saatlik Mumlar)
echo ════════════════════════════════════════════════════════
echo.
echo [BILGI] Bot baslatiliyor... (Ctrl+C ile durdurabilirsiniz)
echo.
python scripts\run_live.py --symbol BTC/USDT --interval 1h --watchdog
goto MENU

:PAPER_TRADING_15M
cls
echo.
echo ════════════════════════════════════════════════════════
echo    PAPER TRADING - BTC/USDT (15 Dakikalik Mumlar)
echo ════════════════════════════════════════════════════════
echo.
echo [BILGI] Bot baslatiliyor... (Ctrl+C ile durdurabilirsiniz)
echo.
python scripts\run_live.py --symbol BTC/USDT --interval 15m --watchdog
goto MENU

:PAPER_TRADING_CUSTOM
cls
echo.
echo ════════════════════════════════════════════════════════
echo      OZELLESTIRILMIS PAPER TRADING
echo ════════════════════════════════════════════════════════
echo.
set /p custom_symbol="Sembol (orn: BTC/USDT, ETH/USDT): "
set /p custom_interval="Interval (5m, 15m, 30m, 1h, 4h): "
set /p custom_watchdog="Watchdog aktif mi? (e/h): "

echo.
echo [BILGI] Bot baslatiliyor...
echo Sembol: %custom_symbol%
echo Interval: %custom_interval%

if /i "%custom_watchdog%"=="e" (
    python scripts\run_live.py --symbol %custom_symbol% --interval %custom_interval% --watchdog
) else (
    python scripts\run_live.py --symbol %custom_symbol% --interval %custom_interval%
)
goto MENU

:LIVE_TRADING
cls
echo.
echo ════════════════════════════════════════════════════════
echo           ⚠️  CANLI TRADING UYARISI ⚠️  
echo ════════════════════════════════════════════════════════
echo.
echo Bu mod GERCEK para ile islem yapar!
echo.
echo Devam etmeden once lutfen asagidakileri dogrulayin:
echo.
echo [ ] 1. .env dosyasinda TRADING_MODE=live ayarli
echo [ ] 2. .env dosyasinda CONFIRM_LIVE_TRADE=true ayarli
echo [ ] 3. Binance API anahtarlari dogru ve aktif
echo [ ] 4. API anahtari izinleri: Spot Trading AKTIF
echo [ ] 5. Withdraw (para cekme) izni: KAPALI (guvenlik!)
echo [ ] 6. Kucuk bir miktar ile test edeceksiniz
echo.
set /p confirm="Tum maddeleri dogruladim ve riskleri kabul ediyorum (e/h): "

if /i not "%confirm%"=="e" (
    echo.
    echo [IPTAL] Canli trading iptal edildi.
    timeout /t 2 >nul
    goto MENU
)

echo.
set /p live_symbol="Canli islem sembolu (orn: BTC/USDT): "
set /p live_interval="Interval (15m, 30m, 1h, 4h): "

echo.
echo [UYARI] CANLI ISLEM BASLATILIYOR!
echo Sembol: %live_symbol%
echo Interval: %live_interval%
echo.
timeout /t 3 >nul

python scripts\run_live.py --symbol %live_symbol% --interval %live_interval% --execute --watchdog
goto MENU

:BACKTEST
cls
echo.
echo ════════════════════════════════════════════════════════
echo              BACKTEST CALISTIRILIYOR...
echo ════════════════════════════════════════════════════════
echo.
set /p bt_symbol="Sembol (orn: BTC/USDT): "
set /p bt_days="Gecmis gun sayisi (orn: 90): "

echo.
python scripts\run_backtest.py --symbol %bt_symbol% --days %bt_days%
echo.
pause
goto MENU

:PORTFOLIO
cls
echo.
echo ════════════════════════════════════════════════════════
echo              PORTFOY DURUMU
echo ════════════════════════════════════════════════════════
echo.
if exist "data\portfolio_state.json" (
    type data\portfolio_state.json
) else (
    echo [BILGI] Henuz acik pozisyon yok.
)
echo.
pause
goto MENU

:TESTS
cls
echo.
echo ════════════════════════════════════════════════════════
echo              TEST SUITE CALISTIRILIYOR...
echo ════════════════════════════════════════════════════════
echo.
python -m pytest tests/test_integration.py -v --tb=short
echo.
pause
goto MENU

:LOGS
cls
echo.
echo ════════════════════════════════════════════════════════
echo              SON LOGSATIRLARI
echo ════════════════════════════════════════════════════════
echo.
if exist "logs\trading.log" (
    powershell -Command "Get-Content logs\trading.log -Tail 50"
) else (
    echo [BILGI] Henuz log dosyasi olusturilmadi.
)
echo.
pause
goto MENU

:EXIT
cls
echo.
echo ════════════════════════════════════════════════════════
echo              LLM TRADING SYSTEM
echo                   KAPANIYOR...
echo ════════════════════════════════════════════════════════
echo.
echo [BILGI] Sistem guvenli sekilde kapatildi.
echo İyi islemler! 👋
echo.
timeout /t 2 >nul
exit /b 0
