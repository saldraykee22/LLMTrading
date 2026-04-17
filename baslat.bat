@echo off
title LLM Trading System - Başlatıcı

:: LLM Trading System - Kolay Başlatma Scripti
:: =============================================

echo.
echo +====================================================================+
echo ^|           LLM TRADING SYSTEM - BAŞLATICI                           ^|
echo ^|                     v2.0.0                                         ^|
echo +====================================================================+
echo.

:: Python kurulumunu kontrol et
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadı! Lütfen Python 3.10+ yükleyin.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [BİLGİ] Python bulundu: 
python --version
echo.

:: Virtual environment kontrolü
if not exist "venv\Scripts\activate.bat" (
    echo [UYARI] Virtual environment bulunamadı!
    echo Oluşturuluyor...
    python -m venv venv
    echo [BİLGİ] Virtual environment oluşturuldu.
    echo.
)

:: Virtual environment aktif et
echo [BİLGİ] Virtual environment aktif ediliyor...
call venv\Scripts\activate.bat
echo.

:: Bağımlılıkları kontrol et
echo [BİLGİ] Bağımlılıklar kontrol ediliyor...
if exist "requirements.txt" (
    pip install -q -r requirements.txt
    echo [TAMAM] Bağımlılıklar yüklü.
)
echo.

:: Ana menü
:MENU
cls
echo.
echo +====================================================================+
echo ^|                        ANA MENÜ                                    ^|
echo +====================================================================+
echo.
echo  1) Sağlık Kontrolü
echo  2) Sanal Trading - BTC/USDT (1 saatlik mumlar)
echo  3) Sanal Trading - BTC/USDT (15 dakikalık mumlar)
echo  4) Sanal Trading - Özelleştirilmiş
echo  5) Canlı Trading (DİKKAT!)
echo  6) Geriye Dönük Test
echo  7) Portföy Durumu
echo  8) Test Paketi
echo  9) Kayıtları Göster
echo.
echo  0) Çıkış
echo.
echo ====================================================================
echo.

set /p choice="Seçiminiz (0-9): "

if "%choice%"=="1" goto SAGLIK
if "%choice%"=="2" goto SANAL_1H
if "%choice%"=="3" goto SANAL_15M
if "%choice%"=="4" goto SANAL_OZEL
if "%choice%"=="5" goto CANLI
if "%choice%"=="6" goto BACKTEST
if "%choice%"=="7" goto PORTFOY
if "%choice%"=="8" goto TESTLER
if "%choice%"=="9" goto KAYITLAR
if "%choice%"=="0" goto CIKIS

echo [HATA] Geçersiz seçim!
timeout /t 2 >nul
goto MENU

:SAGLIK
cls
echo.
echo ====================================================================
echo          SAĞLIK KONTROLÜ ÇALIŞTIRILIYOR...
echo ====================================================================
echo.
python scripts\health_check.py
echo.
pause
goto MENU

:SANAL_1H
cls
echo.
echo ====================================================================
echo     SANAL TRADING - BTC/USDT (1 Saatlik Mumlar)
echo ====================================================================
echo.
echo [BİLGİ] Bot başlatılıyor... (Ctrl+C ile durdurabilirsiniz)
echo.
python scripts\run_live.py --symbol BTC/USDT --interval 1h --watchdog
goto MENU

:SANAL_15M
cls
echo.
echo ====================================================================
echo    SANAL TRADING - BTC/USDT (15 Dakikalık Mumlar)
echo ====================================================================
echo.
echo [BİLGİ] Bot başlatılıyor... (Ctrl+C ile durdurabilirsiniz)
echo.
python scripts\run_live.py --symbol BTC/USDT --interval 15m --watchdog
goto MENU

:SANAL_OZEL
cls
echo.
echo ====================================================================
echo      ÖZELLEŞTİRİLMİŞ SANAL TRADING
echo ====================================================================
echo.
set /p custom_symbol="Sembol (örn: BTC/USDT, ETH/USDT): "
set /p custom_interval="Aralık (5m, 15m, 30m, 1h, 4h): "
set /p custom_watchdog="Bekçi aktif mi? (e/h): "

echo.
echo [BİLGİ] Bot başlatılıyor...
echo Sembol: %custom_symbol%
echo Aralık: %custom_interval%

if /i "%custom_watchdog%"=="e" (
    python scripts\run_live.py --symbol %custom_symbol% --interval %custom_interval% --watchdog
) else (
    python scripts\run_live.py --symbol %custom_symbol% --interval %custom_interval%
)
goto MENU

:CANLI
cls
echo.
echo ====================================================================
echo           ⚠️  CANLI TRADING UYARISI ⚠️  
echo ====================================================================
echo.
echo Bu mod GERÇEK para ile işlem yapar!
echo.
echo Devam etmeden önce lütfen aşağıdakileri doğrulayın:
echo.
echo [ ] 1. .env dosyasında TRADING_MODE=live ayarlı
echo [ ] 2. .env dosyasında CONFIRM_LIVE_TRADE=true ayarlı
echo [ ] 3. Binance API anahtarları doğru ve aktif
echo [ ] 4. API anahtarı izinleri: Spot Trading AKTİF
echo [ ] 5. Withdraw (para çekme) izni: KAPALI (güvenlik!)
echo [ ] 6. Küçük bir miktar ile test edeceksiniz
echo.
set /p confirm="Tüm maddeleri doğruladım ve riskleri kabul ediyorum (e/h): "

if /i not "%confirm%"=="e" (
    echo.
    echo [İPTAL] Canlı trading iptal edildi.
    timeout /t 2 >nul
    goto MENU
)

echo.
set /p live_symbol="Canlı işlem sembolü (örn: BTC/USDT): "
set /p live_interval="Aralık (15m, 30m, 1h, 4h): "

echo.
echo [UYARI] CANLI İŞLEM BAŞLATILIYOR!
echo Sembol: %live_symbol%
echo Aralık: %live_interval%
echo.
timeout /t 3 >nul

python scripts\run_live.py --symbol %live_symbol% --interval %live_interval% --execute --watchdog
goto MENU

:BACKTEST
cls
echo.
echo ====================================================================
echo              GERİYE DÖNÜK TEST ÇALIŞTIRILIYOR...
echo ====================================================================
echo.
set /p bt_symbol="Sembol (örn: BTC/USDT): "
set /p bt_days="Geçmiş gün sayısı (örn: 90): "

echo.
python scripts\run_backtest.py --symbol %bt_symbol% --days %bt_days%
echo.
pause
goto MENU

:PORTFOY
cls
echo.
echo ====================================================================
echo              PORTFÖY DURUMU
echo ====================================================================
echo.
if exist "data\portfolio_state.json" (
    type data\portfolio_state.json
) else (
    echo [BİLGİ] Henüz açık pozisyon yok.
)
echo.
pause
goto MENU

:TESTLER
cls
echo.
echo ====================================================================
echo              TEST PAKETİ ÇALIŞTIRILIYOR...
echo ====================================================================
echo.
python -m pytest tests/test_integration.py -v --tb=short
echo.
pause
goto MENU

:KAYITLAR
cls
echo.
echo ====================================================================
echo              SON KAYIT SATIRLARI
echo ====================================================================
echo.
if exist "logs\trading.log" (
    powershell -Command "Get-Content logs\trading.log -Tail 50"
) else (
    echo [BİLGİ] Henüz kayıt dosyası oluşturulmadı.
)
echo.
pause
goto MENU

:CIKIS
cls
echo.
echo ====================================================================
echo              LLM TRADING SYSTEM
echo                   KAPANIYOR...
echo ====================================================================
echo.
echo [BİLGİ] Sistem güvenli şekilde kapatıldı.
echo İyi işlemler! 👋
echo.
timeout /t 2 >nul
exit /b 0
