import logging
import sys
from pathlib import Path

# Proje kökünü ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from execution.exchange_client import ExchangeClient
from config.settings import get_settings, get_trading_params

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def test_connectivity():
    settings = get_settings()
    params = get_trading_params()
    
    logger.info(f"--- Exchange Connectivity Test ---")
    logger.info(f"Exchange ID: {params.execution.exchange}")
    logger.info(f"Trading Mode: {params.execution.mode.value}")
    
    if not settings.binance_api_key or settings.binance_api_key == "YOUR_API_KEY":
        logger.error("API Key is not set in .env!")
        return
    
    try:
        client = ExchangeClient()
        # 1. Bağlantı ve Bakiye Testi
        balance = client.get_balance()
        if "error" in balance:
            logger.error(f"Balance fetch failed: {balance['error']}")
        else:
            logger.info("✅ Connection Successful!")
            logger.info(f"Balance Summary: {balance}")
        
        # 2. Precision Testi
        exchange = client._get_exchange()
        symbol = "BTC/USDT"
        if symbol in exchange.markets:
            market = exchange.market(symbol)
            logger.info(f"--- Precision Info for {symbol} ---")
            logger.info(f"Amount Precision: {market['precision']['amount']}")
            logger.info(f"Price Precision: {market['precision']['price']}")
            
            test_amount = 0.123456789123
            rounded_amount = exchange.amount_to_precision(symbol, test_amount)
            logger.info(f"Test Amount: {test_amount} -> Rounded: {rounded_amount}")
            
            test_price = 61234.56789123
            rounded_price = exchange.price_to_precision(symbol, test_price)
            logger.info(f"Test Price: {test_price} -> Rounded: {rounded_price}")
        else:
            logger.warning(f"Symbol {symbol} not found in exchange markets.")
            
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    test_connectivity()
