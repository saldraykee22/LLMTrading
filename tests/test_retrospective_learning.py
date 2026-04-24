"""
Retrospektif Öğrenme Testleri (Faz 5)
======================================
Dinamik kural üretimi ve prompt enjeksiyonu testleri.
"""

import pytest
from datetime import datetime, timezone, timedelta


class TestRetrospectiveAgent:
    """RetrospectiveAgent dinamik kural testleri."""
    
    def test_should_review_trade_interval(self):
        """Her 20 işlemde bir inceleme."""
        from agents.retrospective_agent import RetrospectiveAgent
        
        agent = RetrospectiveAgent()
        agent.last_review_date = datetime.now(timezone.utc).date()  # Bugün inceledik
        
        # 15 işlem: Henüz erken
        assert agent.should_review(cycle=100, completed_trades=15) is False
        
        # 20 işlem: Zamanı geldi
        assert agent.should_review(cycle=100, completed_trades=20) is True
        
        # 25 işlem: Geçti
        assert agent.should_review(cycle=100, completed_trades=25) is True
    
    def test_should_review_weekly_interval(self):
        """Haftalık inceleme."""
        from agents.retrospective_agent import RetrospectiveAgent
        
        agent = RetrospectiveAgent()
        agent.last_review_date = datetime.now(timezone.utc).date() - timedelta(days=8)
        
        # 8 gün geçti: Zamanı geldi
        assert agent.should_review(cycle=100, completed_trades=5) is True
        
        # Son inceleme bugün: Henüz erken
        agent.last_review_date = datetime.now(timezone.utc).date()
        assert agent.should_review(cycle=100, completed_trades=5) is False
    
    def test_validate_rules_valid(self):
        """Geçerli kurallar validasyonu."""
        from agents.retrospective_agent import RetrospectiveAgent
        
        agent = RetrospectiveAgent()
        
        valid_rules = {
            "adjust_trend_weight": 0.05,
            "reduce_position_size": 0.8,
            "avoid_low_confidence": 0.7,
            "preferred_timeframe": "4h",
            "max_positions": 4,
            "avoid_downtrend_entries": True,
            "notes": "Test kuralları",
        }
        
        assert agent._validate_rules(valid_rules) is True
    
    def test_validate_rules_invalid_range(self):
        """Geçersiz aralık validasyonu."""
        from agents.retrospective_agent import RetrospectiveAgent
        
        agent = RetrospectiveAgent()
        
        # adjust_trend_weight out of range (> 0.1)
        invalid_rules = {
            "adjust_trend_weight": 0.5,  # Max 0.1 olmalı
        }
        
        assert agent._validate_rules(invalid_rules) is False
    
    def test_validate_rules_invalid_timeframe(self):
        """Geçersiz timeframe validasyonu."""
        from agents.retrospective_agent import RetrospectiveAgent
        
        agent = RetrospectiveAgent()
        
        invalid_rules = {
            "preferred_timeframe": "5h",  # Sadece 1h, 4h, 1d geçerli
        }
        
        assert agent._validate_rules(invalid_rules) is False
    
    def test_save_and_load_dynamic_rules(self):
        """Dinamik kuralları kaydet ve yükle."""
        from agents.retrospective_agent import RetrospectiveAgent
        from config.settings import DATA_DIR
        
        agent = RetrospectiveAgent()
        
        test_rules = {
            "adjust_trend_weight": 0.05,
            "reduce_position_size": 0.8,
            "notes": "Test",
        }
        
        # Kaydet
        agent._save_dynamic_rules(test_rules)
        
        # Yükle
        loaded_rules = RetrospectiveAgent.load_dynamic_rules()
        
        assert loaded_rules is not None
        assert loaded_rules["adjust_trend_weight"] == 0.05
        assert loaded_rules["reduce_position_size"] == 0.8
        assert loaded_rules["notes"] == "Test"
        
        # Temizlik
        rules_file = DATA_DIR / "dynamic_rules.json"
        if rules_file.exists():
            rules_file.unlink()


class TestDynamicRulesInjection:
    """Dinamik kural prompt enjeksiyonu testleri."""
    
    def test_get_dynamic_rules_context(self):
        """Dinamik kuralları context olarak formatla."""
        from utils.dynamic_rules import get_dynamic_rules_context
        from agents.retrospective_agent import RetrospectiveAgent
        from config.settings import DATA_DIR
        
        # Test kuralları kaydet
        test_rules = {
            "adjust_trend_weight": 0.05,
            "reduce_position_size": 0.8,
            "avoid_low_confidence": 0.7,
            "preferred_timeframe": "4h",
            "notes": "Test",
        }
        
        agent = RetrospectiveAgent()
        agent._save_dynamic_rules(test_rules)
        
        # Context al
        context = get_dynamic_rules_context()
        
        assert context != ""
        # Türkçe karakter yerine İngilizce kontrol
        assert "Trend" in context or "trend" in context
        assert "position" in context.lower() or "Pozisyon" in context
        assert "0.7" in context or "confidence" in context.lower()
        assert "4h" in context
        
        # Temizlik
        rules_file = DATA_DIR / "dynamic_rules.json"
        if rules_file.exists():
            rules_file.unlink()
    
    def test_inject_dynamic_rules_into_prompt(self):
        """Dinamik kuralları prompt'a enjekte et."""
        from utils.dynamic_rules import inject_dynamic_rules_into_prompt
        from agents.retrospective_agent import RetrospectiveAgent
        
        # Test kuralları kaydet
        test_rules = {
            "reduce_position_size": 0.8,
        }
        
        agent = RetrospectiveAgent()
        agent._save_dynamic_rules(test_rules)
        
        # Orijinal prompt
        original_prompt = "Sen bir tradersın. Görevin: alım-satım kararı vermek."
        
        # Enjekte et
        enhanced_prompt = inject_dynamic_rules_into_prompt(
            original_prompt,
            agent_name="Trader"
        )
        
        assert original_prompt in enhanced_prompt
        assert "Öğrenilen Kurallar" in enhanced_prompt
        assert "Pozisyon boyutunu %20 azalt" in enhanced_prompt
        
        # Temizlik
        from config.settings import DATA_DIR
        rules_file = DATA_DIR / "dynamic_rules.json"
        if rules_file.exists():
            rules_file.unlink()
    
    def test_inject_no_rules(self):
        """Kural yoksa orijinal prompt dönmeli."""
        from utils.dynamic_rules import inject_dynamic_rules_into_prompt
        
        original_prompt = "Sen bir tradersın."
        
        enhanced_prompt = inject_dynamic_rules_into_prompt(original_prompt)
        
        # Kurallar yoksa aynı prompt
        assert enhanced_prompt == original_prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
