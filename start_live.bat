@echo off
title LLM Trading System - CANLI MOD (LIVE)

echo =========================================================
echo ⚠️  [UYARI] LLM TRADING SYSTEM - TAM CANLI MOD ⚠️
echo =========================================================
echo Bu mod GERCEK BAKIYE ve GERCEK ISLEMLER icerir.
echo OTO-TARAMA (Auto-Scan) ve TUM HESAPLAR aktiftir.
echo.
echo Kapatmak icin CTRL+C tuslarina basabilirsiniz.
echo =========================================================
echo.

:: Virtual environment aktivasyonu
if exist "venv\Scripts\activate.bat" (
    echo [BILGI] Virtual environment aktif ediliyor...
    call venv\Scripts\activate.bat
) else (
    echo [UYARI] Virtual environment (venv) bulunamadi. Global Python kullanilacak.
)

echo.
echo [BILGI] Bot calistiriliyor... 
echo Lutfen islemler devam ederken bu ekrani kapatmayin.
echo.

python scripts\run_live.py --auto-scan --execute --interval 30m

echo.
echo [BILGI] Bot durduruldu.
pause
