#!/bin/bash

# LLM Trading - Linux Alias Kurulumu
# Bu script, terminal'e kolay komutlar ekler

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RC_FILE="$HOME/.bashrc"

# Zsh kontrolü
if [ -n "$ZSH_VERSION" ]; then
    RC_FILE="$HOME/.zshrc"
elif [ -n "$BASH_VERSION" ]; then
    RC_FILE="$HOME/.bashrc"
fi

echo "============================================"
echo "  LLM Trading - Alias Kurulumu"
echo "============================================"
echo ""

# Alias'lar
ALIASES='
# LLM Trading System
alias llm-start="cd '$SCRIPT_DIR' && python3 scripts/run_live.py --symbol AUTO --paper --watchdog --auto-scan --model qwen/qwen3.5-flash-02-23"
alias llm-stop="touch '$SCRIPT_DIR'/data/STOP"
alias llm-status="cd '$SCRIPT_DIR' && python3 cli.py durum"
alias llm-fallback="cd '$SCRIPT_DIR' && python3 cli.py fallbacklar"
alias llm-circuit="cd '$SCRIPT_DIR' && python3 cli.py circuit-breaker"
alias llm-notes="cd '$SCRIPT_DIR' && python3 cli.py notlar"
alias llm-log="tail -f '$SCRIPT_DIR'/logs/trading.log"
'

# RC dosyasına ekle
if grep -q "LLM Trading System" "$RC_FILE" 2>/dev/null; then
    echo "Alias'lar zaten mevcut. Güncelleniyor..."
    # Eski alias'ları kaldır ve yenilerini ekle
    sed -i '/# LLM Trading System/,/llm-log/d' "$RC_FILE"
fi

echo "$ALIASES" >> "$RC_FILE"

echo "✓ Alias'lar eklendi: $RC_FILE"
echo ""
echo "Kullanılabilir komutlar:"
echo "  llm-start     - Paper mode başlat (AUTO scanner)"
echo "  llm-stop      - Bot'u durdur"
echo "  llm-status    - Sistem durumu"
echo "  llm-fallback  - Fallback istatistikleri"
echo "  llm-circuit   - Circuit breaker durumu"
echo "  llm-notes     - Kullanıcı notları"
echo "  llm-log       - Canlı log izleme"
echo ""
echo "NOT: Alias'ların aktif olması için terminal'i yeniden başlatın"
echo "     veya şu komutu çalıştırın: source $RC_FILE"
echo ""
