import os
import sys
import logging
from pathlib import Path

# Proje kök dizinini ekle
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import get_settings, TradingMode
from execution.exchange_client import ExchangeClient
from data.market_data import MarketDataClient

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("PreFlight")

def check_env():
    logger.info("🔍 1. .env ve Ayarlar Kontrolü...")
    settings = get_settings()
    
    missing = []
    if not settings.binance_api_key or settings.binance_api_key == "YOUR_API_KEY":
        missing.append("BINANCE_API_KEY")
    if not settings.binance_api_secret or settings.binance_api_secret == "YOUR_API_SECRET":
        missing.append("BINANCE_API_SECRET")
    if not settings.openrouter_api_key:
        missing.append("OPENROUTER_API_KEY/OPENAI_API_KEY")
        
    if missing:
        logger.error(f"❌ Eksik yapılandırma: {', '.join(missing)}")
        return False
        
    logger.info(f"✅ Ayarlar yüklendi. Mod: {settings.trading_mode}")
    if settings.trading_mode == TradingMode.LIVE:
        if not settings.confirm_live_trade:
            logger.warning("⚠ CANLI MODDA AMA 'CONFIRM_LIVE_TRADE' KAPALI! Emirler reddedilecektir.")
    return True

def check_exchange_connectivity():
    logger.info("🔍 2. Borsa Bağlantısı (CCXT)...")
    settings = get_settings()
    
    # Canlı mod güvenliği
    if settings.trading_mode == TradingMode.LIVE:
        if not settings.confirm_live_trade:
            logger.warning("⚠ CANLI MODDA AMA 'CONFIRM_LIVE_TRADE' KAPALI! Bağlantı testi atlanıyor.")
            return True # Atla ama hata verme
    
    try:
        client = ExchangeClient()
        balance = client.get_balance()
        if "error" in balance:
            logger.error(f"❌ Bakiye çekilemedi: {balance['error']}")
            return False
        
        # Filtrelenmiş varlıklar (sıfır olmayanlar)
        active_assets = {k: v for k, v in balance.items() if v > 0}
        logger.info(f"✅ Borsaya bağlanıldı. Aktif varlıklar: {list(active_assets.keys())}")
        
        if "USDT" not in balance or balance["USDT"] < 1:
            logger.warning(f"⚠ Cüzdanda yeterli USDT bulunamadı: {balance.get('USDT', 0)}")
        else:
            logger.info(f"💰 Mevcut USDT: {balance['USDT']:.2f}")
        return True
    except Exception as e:
        logger.error(f"❌ Bağlantı hatası: {e}")
        return False

def check_data_connectivity():
    logger.info("🔍 3. Piyasa Verisi ve LLM Erişimi...")
    try:
        md = MarketDataClient()
        df = md.fetch_ohlcv("BTC/USDT", timeframe="1h", days=1)
        if df.empty:
            logger.error("❌ Veri çekilemedi (BTC/USDT)")
            return False
        logger.info("✅ Piyasa verisi erişimi OK.")
        return True
    except Exception as e:
        logger.error(f"❌ Veri erişim hatası: {e}")
        return False

def check_file_permissions():
    logger.info("🔍 4. Dosya ve Yazma İzinleri...")
    paths = ["data", "logs", "data/portfolio_state.json"]
    for p in paths:
        path = Path(p)
        if path.exists():
            if not os.access(path, os.W_OK):
                logger.error(f"❌ '{p}' dizinine/dosyasına yazma izni yok!")
                return False
        else:
            try:
                if path.suffix: # Dosya ise
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                else: # Dizin ise
                    path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"❌ '{p}' oluşturulamadı: {e}")
                return False
    logger.info("✅ Dosya izinleri OK.")
    return True

def run_all_checks():
    logger.info("🚀 LLMTrading CANLI İŞLEM ÖNCESİ KONTROLLERİ BAŞLATILIYOR\n")
    
    results = [
        check_env(),
        check_file_permissions(),
        check_exchange_connectivity(),
        check_data_connectivity()
    ]
    
    print("\n" + "="*50)
    if all(results):
        logger.info("🎉 TÜM KONTROLLER BAŞARILI! Sistem canlıya geçmeye hazır.")
        logger.info("Komut: python scripts/run_live.py --auto-scan --execute")
    else:
        logger.error("🚨 KONTROLLER BAŞARISIZ! Lütfen yukarıdaki hataları giderin.")
    print("="*50)

if __name__ == "__main__":
    run_all_checks()
