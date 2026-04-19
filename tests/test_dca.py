"""
DCA (Kademeli Alım-Satım) Testleri
===================================
Faz 1 uygulamasının birim testleri.
"""

import pytest
from pathlib import Path
from risk.portfolio import PortfolioState, Position


class TestPositionDCA:
    """Position DCA alanları testleri."""
    
    def test_position_initial_dca_values(self):
        """Pozisyon ilk oluşturulduğunda DCA alanları otomatik doldurulmalı."""
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time="2026-04-19T10:00:00Z",
        )
        
        assert pos.target_size == 0.1
        assert pos.target_size_usd == 5000.0
        assert pos.executed_tranches == 0  # Başlangıçta 0
        assert pos.remaining_size == 0.0  # İlk alımda kalan yok
    
    def test_position_with_explicit_dca_values(self):
        """Pozisyon açık DCA değerleriyle oluşturulabilmeli."""
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.05,  # İlk kademe: 0.05
            entry_time="2026-04-19T10:00:00Z",
            target_size=0.2,  # Hedef: 0.2
            target_size_usd=10000.0,
            executed_tranches=1,
            remaining_size=0.15,  # Kalan: 0.15
        )
        
        assert pos.target_size == 0.2
        assert pos.target_size_usd == 10000.0
        assert pos.executed_tranches == 1
        assert pos.remaining_size == 0.15
        assert not pos.is_dca_complete()
    
    def test_add_tranche(self):
        """DCA kademesi ekleme testi."""
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.05,
            entry_time="2026-04-19T10:00:00Z",
            target_size=0.2,
            target_size_usd=10000.0,
            remaining_size=0.15,
            executed_tranches=1,
        )
        
        # İkinci kademe ekle: 0.05 @ 49000
        pos.add_tranche(0.05, 49000.0)
        
        assert pos.amount == 0.1  # Toplam miktar arttı
        assert pos.executed_tranches == 2  # Kademe sayısı arttı
        assert pos.remaining_size == 0.1  # Kalan azaldı
        # Ağırlıklı ortalama: (0.05*50000 + 0.05*49000) / 0.1 = 49500
        assert abs(pos.entry_price - 49500.0) < 0.01
    
    def test_is_dca_complete(self):
        """DCA tamamlanma kontrolü."""
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time="2026-04-19T10:00:00Z",
            target_size=0.2,
            remaining_size=0.1,
        )
        
        assert not pos.is_dca_complete()
        
        # Kalan kadar ekle
        pos.add_tranche(0.1, 51000.0)
        
        assert pos.is_dca_complete()
        assert pos.remaining_size <= 0


class TestPortfolioDCA:
    """PortfolioState DCA testleri."""
    
    def test_open_position_with_dca(self):
        """DCA ile pozisyon açma."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        # İlk kademe: %50 (5000$)
        pos = portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.1,
            target_size=0.2,  # Hedef: 0.2 (10000$)
            target_size_usd=10000.0,
        )
        
        assert pos is not None
        assert pos.amount == 0.1
        assert pos.target_size == 0.2
        assert pos.remaining_size == 0.1
        assert portfolio.cash == 5000.0  # 5000$ harcandı
    
    def test_add_dca_tranche(self):
        """Mevcut pozisyona DCA kademesi ekleme."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        # İlk pozisyon
        pos1 = portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.05,
            target_size=0.2,
            target_size_usd=10000.0,
        )
        
        # İkinci kademe ekle
        pos2 = portfolio.add_dca_tranche(
            symbol="BTC/USDT",
            amount=0.05,
            price=49000.0,
        )
        
        assert pos2 is not None
        assert pos2.amount == 0.1  # Toplam miktar arttı
        assert pos2.executed_tranches == 2
        assert pos2.remaining_size == 0.1
        # Ağırlıklı ortalama: (0.05*50000 + 0.05*49000) / 0.1 = 49500
        assert abs(pos2.entry_price - 49500.0) < 0.01
        assert portfolio.cash == 5050.0  # 10000 - 2500 - 2450
    
    def test_add_dca_tranche_exceeds_remaining(self):
        """Kalan tahsisi aşan DCA isteği - yetersiz bakiye olarak reddedilir."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        # İlk pozisyon: 0.05 @ 50000 = 2500$, kalan 7500$
        # Hedef: 0.2, kalan tahsis: 0.15
        portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.05,
            target_size=0.2,
        )
        
        # Kalan tahsisten fazla isteme (0.15 yerine 0.2)
        # 0.2 * 49000 = 9800$ > 7500$ (yetersiz bakiye)
        result = portfolio.add_dca_tranche(
            symbol="BTC/USDT",
            amount=0.2,  # Kalan: 0.15, istenen: 0.2
            price=49000.0,
        )
        
        # Yetersiz bakiye nedeniyle reddedilmeli
        assert result is None
    
    def test_add_dca_tranche_insufficient_cash(self):
        """Yetersiz bakiye durumunda DCA reddedilmeli."""
        # Test 1: 1000$ ile başla, 500$ harca, 490$ iste (başarılı)
        portfolio1 = PortfolioState(initial_cash=1000.0)
        portfolio1.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.01,  # 500$
            target_size=0.1,
        )
        assert portfolio1.cash == 500.0, f"İlk pozisyon sonrası cash 500$ olmalı, {portfolio1.cash}"
        
        # 0.01 @ 49000 = 490$ < 500$ → başarılı
        result1 = portfolio1.add_dca_tranche(
            symbol="BTC/USDT",
            amount=0.01,
            price=49000.0,
        )
        assert result1 is not None, "0.01 miktarında DCA başarılı olmalı (490$ < 500$)"
        
        # Test 2: Yeni portfolio, 1000$ ile başla, 500$ harca, 600$ iste (başarısız)
        portfolio2 = PortfolioState(initial_cash=1000.0)
        portfolio2.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.01,  # 500$
            target_size=0.1,
        )
        
        # 0.012 @ 49000 = 588$ > 500$ → başarısız
        result2 = portfolio2.add_dca_tranche(
            symbol="BTC/USDT",
            amount=0.012,
            price=49000.0,
        )
        assert result2 is None, f"Yetersiz bakiye (588$ > 500$), cash={portfolio2.cash}"
    
    def test_dca_position_serialization(self):
        """DCA pozisyonu JSON'a doğru serileştirilmeli."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.05,
            target_size=0.2,
            target_size_usd=10000.0,
        )
        
        state_dict = portfolio.to_dict()
        
        assert len(state_dict["positions"]) == 1
        pos_data = state_dict["positions"][0]
        
        assert pos_data["symbol"] == "BTC/USDT"
        assert pos_data["amount"] == 0.05
        assert pos_data["target_size"] == 0.2
        assert abs(pos_data["target_size_usd"] - 10000.0) < 0.01
        assert abs(pos_data["remaining_size"] - 0.15) < 0.001  # Floating point tolerans
        assert pos_data["executed_tranches"] == 1
        assert "dca_complete" in pos_data


class TestTradeOrderDCA:
    """TradeOrder DCA testleri."""
    
    def test_trade_order_with_dca_fields(self):
        """TradeOrder DCA alanlarıyla oluşturulabilmeli."""
        from execution.order_manager import TradeOrder
        
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.05,
            execution_size_pct=0.5,  # %50 ilk kademe
            target_size=0.2,
            is_dca_tranche=True,
            tranche_number=1,
        )
        
        assert order.execution_size_pct == 0.5
        assert order.target_size == 0.2
        assert order.is_dca_tranche
        assert order.tranche_number == 1
    
    def test_parse_trade_decision_with_dca(self):
        """Trader kararından DCA parametreleriyle Order parse etme."""
        from execution.order_manager import parse_trade_decision
        
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "order_type": "market",
            "amount": 0.2,
            "target_size": 0.2,
            "execution_size_pct": 0.5,  # İlk kademe %50
            "stop_loss": 48000.0,
            "take_profit": 55000.0,
            "confidence": 0.75,
            "reasoning": "İlk kademe %50, destek test ediliyor",
        }
        
        order = parse_trade_decision(decision, current_price=50000.0)
        
        assert order is not None
        assert order.amount == 0.1  # 0.2 * 0.5 = 0.1 (ilk kademe)
        assert order.execution_size_pct == 0.5
        assert order.target_size == 0.2
        assert order.is_dca_tranche
    
    def test_parse_trade_decision_without_dca(self):
        """DCA parametresi yoksa varsayılan %100 kullanılmalı."""
        from execution.order_manager import parse_trade_decision
        
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "order_type": "market",
            "amount": 0.2,
            "stop_loss": 48000.0,
            "take_profit": 55000.0,
        }
        
        order = parse_trade_decision(decision, current_price=50000.0)
        
        assert order is not None
        assert order.amount == 0.2  # Tam miktar
        assert order.execution_size_pct == 1.0
        assert not order.is_dca_tranche


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
