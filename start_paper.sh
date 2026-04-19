#!/bin/bash

# LLM Trading System - Paper Mode Başlatıcı (Linux)
# Kullanım: ./start_paper.sh

set -e

# Renk kodları
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "============================================"
echo "  LLM TRADING SYSTEM - PAPER MODE"
echo "============================================"
echo ""

# Python kontrolü
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[HATA] Python3 bulunamadı!${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}[OK]${NC} Python bulundu: $PYTHON_VERSION"

# .env kontrolü
if [ ! -f ".env" ]; then
    echo -e "${RED}[HATA] .env dosyası bulunamadı!${NC}"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} .env bulundu"
echo ""

# Paper trading başlat
echo -e "${GREEN}[BAŞLIYOR]${NC} Paper trading başlatılıyor..."
echo -e "${YELLOW}[BİLGİ]${NC} Komut için \"/\" tuşuna basın"
echo -e "${YELLOW}[BİLGİ]${NC} Model: qwen3.5-flash"
echo ""

python3 scripts/run_live.py \
    --symbol AUTO \
    --paper \
    --watchdog \
    --auto-scan \
    --model "qwen/qwen3.5-flash-02-23"

echo ""
echo -e "${GREEN}[BİTTİ]${NC} İşlem tamamlandı."
