@echo off
setlocal enabledelayedexpansion

:: LLM Trading System - Otomatik Kurulum Scripti (Windows)
:: ========================================================

chcp 65001 > nul
echo.
echo  ======================================================
echo     Aegis Terminal - Otomatik Kurulum Baslatiliyor
echo  ======================================================
echo.

:: 1. Python Kontrolü
echo [+] Python kontrol ediliyor...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] HATA: Python bulunamadi! Lutfen Python 3.10 veya uzeri bir surumun yuklu ve PATH'e ekli oldugundan emin olun.
    pause
    exit /b 1
)

:: 2. Klasör Yapısı
echo [+] Klasör yapisi kontrol ediliyor...
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "data\cache" mkdir data\cache
if not exist "data\backtest_results" mkdir data\backtest_results

:: 3. .env Dosyası
if not exist ".env" (
    echo [+] .env dosyasi bulunamadi, .env.example'dan kopyalaniyor...
    copy .env.example .env
    echo [!] Lutfen .env dosyasini acip API anahtarlarinizi girin!
) else (
    echo [+] .env dosyasi zaten mevcut.
)

:: 4. Virtual Environment (venv) Oluşturma
if not exist "venv" (
    echo [+] Sanal ortam (venv) olusturuluyor...
    python -m venv venv
) else (
    echo [+] Sanal ortam zaten mevcut.
)

:: 5. Bağımlılıkların Yüklenmesi
echo [+] Bagimliliklar yukleniyor (bu islem biraz zaman alabilir)...
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

:: 6. Sağlık Kontrolü
echo.
echo [+] Kurulum tamamlandi! Sistem saglik kontrolü yapiliyor...
echo.
python cli.py saglik

echo.
echo  ======================================================
echo     Kurulum Basarıyla Tamamlandi!
echo  ======================================================
echo.
echo  Sistemi baslatmak icin:
echo  1. .env dosyasina API anahtarlarinizi girin.
echo  2. 'scripts\baslat.bat' dosyasini calistirin.
echo.
pause
