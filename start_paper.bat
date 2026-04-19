@echo off
chcp 65001 >nul
title LLM Trading - Paper Mode

echo ============================================
echo   LLM TRADING SYSTEM - PAPER MODE
echo ============================================
echo.

REM Python kontrolü
python --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi!
    pause
    exit /b 1
)

echo [OK] Python bulundu
echo.

REM .env kontrolü
if not exist ".env" (
    echo [HATA] .env dosyasi bulunamadi!
    pause
    exit /b 1
)

echo [OK] .env bulundu
echo.

REM Paper trading başlat
echo [BAŞLIYOR] Paper trading başlatılıyor...
echo [BİLGİ] Komut için "/" tuşuna basın
echo [BİLGİ] Model: qwen3.5-flash
echo.

python scripts/run_live.py --symbol AUTO --paper --watchdog --auto-scan --model qwen/qwen3.5-flash-02-23

echo.
echo [BİTTİ] İşlem tamamlandı.
pause
