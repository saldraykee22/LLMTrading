# 🐧 Linux Hızlı Başlangıç

## 🚀 Kolay Başlatma

### **1. Script'i Executable Yap**
```bash
chmod +x start_paper.sh
```

### **2. Başlat**
```bash
./start_paper.sh
```

---

## 🎯 ALIAS KURULUMU (ÖNERİLEN)

### **Kurulum:**
```bash
chmod +x install_linux_alias.sh
./install_linux_alias.sh
source ~/.bashrc  # veya ~/.zshrc
```

### **Kullanılabilir Komutlar:**

| Komut | Açıklama |
|-------|----------|
| `llm-start` | Paper mode başlat (AUTO scanner) |
| `llm-stop` | Bot'u durdur |
| `llm-status` | Sistem durumu göster |
| `llm-fallback` | Fallback istatistikleri |
| `llm-circuit` | Circuit breaker durumu |
| `llm-notes` | Kullanıcı notları |
| `llm-log` | Canlı log izleme |

### **Örnek Kullanım:**
```bash
# Bot'u başlat
llm-start

# Başka terminal'de durum kontrolü
llm-status

# Fallback'leri izle
llm-fallback

# Bot'u durdur
llm-stop
```

---

## 📋 MANUEL KOMUTLAR

### **Paper Mode Başlatma:**
```bash
python3 scripts/run_live.py \
    --symbol AUTO \
    --paper \
    --watchdog \
    --auto-scan \
    --model "qwen/qwen3.5-flash-02-23"
```

### **CLI ile:**
```bash
python3 cli.py calistir \
    --sembol AUTO \
    --bekci \
    --oto-tarama \
    --model "qwen/qwen3.5-flash-02-23"
```

---

## 🔧 İNTERAKTİF KOMUTLAR

Bot çalışırken her cycle sonunda:
```
> _ (komut için / yazın)
```

**Komutlar:**
- `/durum` veya `/d` - Sistem durumu
- `/pozisyon` veya `/p` - Açık pozisyonlar
- `/fallback` veya `/f` - Fallback istatistikleri
- `/circuit` veya `/c` - Circuit breaker
- `/log` veya `/l` - Son hatalar
- `/not-yaz` - Not ekle
- `/notlar` veya `/n` - Tüm notlar
- `/yardim` veya `/h` - Yardım
- `/cikis` veya `/q` - Çıkış

---

## 📁 DOSYA YAPISI

```
LLMTrading/
├── start_paper.sh           ← Linux başlatıcı
├── install_linux_alias.sh   ← Alias kurulumu
├── start_paper.bat          ← Windows başlatıcı
├── scripts/
│   ├── run_live.py
│   └── interactive_commands.py
├── cli.py
├── logs/
│   └── trading.log
└── data/
    ├── user_notes.jsonl
    ├── fallback_audit.jsonl
    └── exports/
```

---

## ⚙️ SİSTEM GEREKSİNİMLERİ

- Python 3.10+
- Linux (Ubuntu, Debian, Fedora, vb.)
- Bash veya Zsh

---

## 🐛 SORUN GİDERME

### **Python bulunamadı:**
```bash
sudo apt install python3 python3-pip  # Debian/Ubuntu
sudo dnf install python3 python3-pip  # Fedora
```

### **Permission denied:**
```bash
chmod +x start_paper.sh
chmod +x install_linux_alias.sh
```

### **Alias'lar çalışmıyor:**
```bash
source ~/.bashrc  # veya ~/.zshrc
```

### **ModuleNotFoundError:**
```bash
pip3 install -r requirements.txt
```

---

## 📞 HIZLI KOMUTLAR

```bash
# Başlat
./start_paper.sh

# Veya alias ile
llm-start

# Durum kontrolü
python3 cli.py durum

# Fallback'ler
python3 cli.py fallbacklar

# Circuit breaker
python3 cli.py circuit-breaker

# Durdur
touch data/STOP

# Veya alias ile
llm-stop
```
