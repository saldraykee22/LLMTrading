"""
Dynamic Rules Injection Utility
===============================
Dinamik olarak üretilen kuralları ajan prompt'larına enjekte eder.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from config.constants import MAX_DYNAMIC_RULES_LENGTH

logger = logging.getLogger(__name__)


def sanitize_dynamic_rules(rules: str) -> str:
    """
    Dynamic rules'ü güvenlik için sanitize eder. Tüm ajanlar için kullanılır.

    Security layers:
    1. Max length enforcement
    2. Unicode normalization (bypass prevention)
    3. Template injection blocking (nested patterns dahil)
    4. Code injection blocking
    5. HTML/JS injection blocking
    6. Path traversal blocking
    7. SQL injection blocking
    8. Base64 encoded payload detection
    9. Null byte injection
    10. Control characters
    """
    if not rules:
        return ""

    # 1. Max length enforcement
    sanitized = rules[:MAX_DYNAMIC_RULES_LENGTH]

    # 2. Unicode normalization (NFKC)
    import unicodedata
    sanitized = unicodedata.normalize('NFKC', sanitized)

    # 3. Template injection blocking
    sanitized = re.sub(r'\{\{.*?\}\}', '[BLOCKED_TEMPLATE]', sanitized, flags=re.DOTALL)
    sanitized = re.sub(r'\{%.*?%\}', '[BLOCKED_JINJA]', sanitized, flags=re.DOTALL)
    sanitized = re.sub(r'\{#.*?#\}', '[BLOCKED_COMMENT]', sanitized, flags=re.DOTALL)
    sanitized = re.sub(r'\{+', '[BLOCKED]', sanitized)
    sanitized = re.sub(r'\}+', '[BLOCKED]', sanitized)

    # 4. Code injection blocking
    sanitized = re.sub(r'`[^`]*`', '[BLOCKED_CODE]', sanitized)
    dangerous_funcs = [
        r'\beval\s*\(', r'\bexec\s*\(', r'\b__import__\s*\(',
        r'\bcompile\s*\(', r'\bgetattr\s*\(', r'\bsetattr\s*\(',
        r'\bdelattr\s*\(', r'\bvars\s*\(', r'\bdir\s*\(',
        r'\bopen\s*\(', r'\bfile\s*\(', r'\bos\.', r'\bsys\.',
        r'\bsubprocess\.', r'\bshutil\.', r'\bimportlib\.',
    ]
    for pattern in dangerous_funcs:
        sanitized = re.sub(pattern, '[BLOCKED_FUNC]', sanitized, flags=re.IGNORECASE)

    # 5. HTML/JS injection blocking
    sanitized = re.sub(r'<script[^>]*>.*?</script>', '[BLOCKED_SCRIPT]', sanitized, flags=re.IGNORECASE | re.DOTALL)
    sanitized = re.sub(r'<[^>]+>', '[BLOCKED_HTML]', sanitized)
    sanitized = re.sub(r'\bon\w+\s*=', '[BLOCKED_EVENT]', sanitized, flags=re.IGNORECASE)

    # 6. Path traversal blocking
    sanitized = re.sub(r'\.\./', '[BLOCKED_PATH]', sanitized)
    sanitized = re.sub(r'\.\.\\', '[BLOCKED_PATH]', sanitized)

    # 7. SQL injection blocking
    sanitized = re.sub(r'--', '[BLOCKED]', sanitized)
    sanitized = re.sub(r'/\*.*?\*/', '[BLOCKED]', sanitized, flags=re.DOTALL)

    # 8. Base64 encoded payload detection
    base64_pattern = r'[A-Za-z0-9+/]{200,}={0,2}'
    sanitized = re.sub(base64_pattern, '[BLOCKED_BASE64]', sanitized)

    # 9. Null byte injection
    sanitized = sanitized.replace('\x00', '')

    # 10. Control characters (except \n, \t)
    sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', sanitized)

    if len(sanitized) < len(rules) * 0.8:
        logger.warning(
            "Dynamic rules heavy sanitization: %d → %d chars (%.1f%% removed)",
            len(rules), len(sanitized), (1 - len(sanitized)/len(rules)) * 100
        )

    return sanitized.strip()


def validate_dynamic_rules(rules: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Dinamik kuralları valide et.

    Args:
        rules: Valide edilecek kurallar dict

    Returns:
        (is_valid, list_of_errors)
    """
    errors: list[str] = []

    if not rules:
        return True, []

    raw_str = str(rules)

    if len(raw_str) > 2000:
        errors.append("Kurallar çok uzun (max 2000 karakter)")

    forbidden_words = ["ignore", "bypass", "skip", "override", "disable", "forget"]
    for word in forbidden_words:
        if word in raw_str.lower():
            errors.append(f"Yasaklı kelime tespit edildi: {word}")

    if "adjust_trend_weight" in rules:
        val = rules["adjust_trend_weight"]
        if not isinstance(val, (int, float)) or not -0.5 <= val <= 0.5:
            errors.append("adjust_trend_weight -0.5 ile 0.5 arasında olmalı")

    if "adjust_sentiment_weight" in rules:
        val = rules["adjust_sentiment_weight"]
        if not isinstance(val, (int, float)) or not -0.5 <= val <= 0.5:
            errors.append("adjust_sentiment_weight -0.5 ile 0.5 arasında olmalı")

    if "reduce_position_size" in rules:
        val = rules["reduce_position_size"]
        if not isinstance(val, (int, float)) or not 0.1 <= val <= 1.0:
            errors.append("reduce_position_size 0.1 ile 1.0 arasında olmalı")

    if "avoid_low_confidence" in rules:
        val = rules["avoid_low_confidence"]
        if not isinstance(val, (int, float)) or not 0.0 <= val <= 1.0:
            errors.append("avoid_low_confidence 0.0 ile 1.0 arasında olmalı")

    if "max_positions" in rules:
        val = rules["max_positions"]
        if not isinstance(val, int) or not 1 <= val <= 10:
            errors.append("max_positions 1 ile 10 arasında olmalı")

    if "stop_loss_multiplier" in rules:
        val = rules["stop_loss_multiplier"]
        if not isinstance(val, (int, float)) or not 0.5 <= val <= 2.0:
            errors.append("stop_loss_multiplier 0.5 ile 2.0 arasında olmalı")

    if "take_profit_multiplier" in rules:
        val = rules["take_profit_multiplier"]
        if not isinstance(val, (int, float)) or not 0.5 <= val <= 2.0:
            errors.append("take_profit_multiplier 0.5 ile 2.0 arasında olmalı")

    return len(errors) == 0, errors


def get_dynamic_rules_context() -> str:
    """
    Dinamik kuralları prompt context'i olarak formatla.

    Returns:
        Formatlanmış kurallar metni veya boş string
    """
    from agents.retrospective_agent import RetrospectiveAgent

    rules = RetrospectiveAgent.load_dynamic_rules()

    if not rules:
        return ""

    is_valid, errors = validate_dynamic_rules(rules)
    if not is_valid:
        logger.error(f"Dynamic rules validation failed: {errors}")
        return ""

    # Formatla
    lines = ["## Öğrenilen Kurallar (Son Retrospektif Analiz)"]
    
    if "adjust_trend_weight" in rules:
        direction = "artır" if rules["adjust_trend_weight"] > 0 else "azalt"
        lines.append(
            f"- Trend ağırlığını %{abs(rules['adjust_trend_weight']) * 100:.0f} {direction} "
            f"(son analizde trend sinyalleri {'güçlü' if rules['adjust_trend_weight'] > 0 else 'zayıf'} bulundu)"
        )
    
    if "adjust_sentiment_weight" in rules:
        direction = "artır" if rules["adjust_sentiment_weight"] > 0 else "azalt"
        lines.append(
            f"- Sentiment ağırlığını %{abs(rules['adjust_sentiment_weight']) * 100:.0f} {direction}"
        )
    
    if "reduce_position_size" in rules:
        reduction = (1 - rules["reduce_position_size"]) * 100
        lines.append(
            f"- Pozisyon boyutunu %{reduction:.0f} azalt "
            f"(risk yönetimi iyileştirme)"
        )
    
    if "avoid_low_confidence" in rules:
        lines.append(
            f"- Güven skoru <{rules['avoid_low_confidence']:.1f} ise işlem açma "
            f"(erken giriş hatası tespit edildi)"
        )
    
    if "preferred_timeframe" in rules:
        lines.append(
            f"- {rules['preferred_timeframe']} timeframe'ine odaklan "
            f"(daha tutarlı sinyaller)"
        )
    
    if "max_positions" in rules:
        lines.append(
            f"- Max {rules['max_positions']} pozisyon ile sınırlı kal "
            f"(dağılma riskini azalt)"
        )
    
    if "stop_loss_multiplier" in rules:
        if rules["stop_loss_multiplier"] > 1:
            lines.append(
                f"- Stop-loss mesafesini %{(rules['stop_loss_multiplier'] - 1) * 100:.0f} genişlet "
                f"(premature stop azaltma)"
            )
        else:
            lines.append(
                f"- Stop-loss mesafesini %{(1 - rules['stop_loss_multiplier']) * 100:.0f} daralt "
                f"(risk kontrolü)"
            )
    
    if "take_profit_multiplier" in rules:
        if rules["take_profit_multiplier"] > 1:
            lines.append(
                f"- Take-profit mesafesini %{(rules['take_profit_multiplier'] - 1) * 100:.0f} genişlet "
                f"(kar realizasyonu geciktirme)"
            )
        else:
            lines.append(
                f"- Take-profit mesafesini %{(1 - rules['take_profit_multiplier']) * 100:.0f} daralt "
                f"(hızlı kar alma)"
            )
    
    if "avoid_downtrend_entries" in rules and rules["avoid_downtrend_entries"]:
        lines.append(
            "- Düşüş trendinde yeni alış işlemi açma "
            "(trend tersine dönene kadar bekle)"
        )
    
    if "require_volume_confirmation" in rules and rules["require_volume_confirmation"]:
        lines.append(
            "- Hacim artışı olmadan işlem açma "
            "(sessiz birikim bekleniyor)"
        )
    
    if "notes" in rules:
        lines.append(f"\nNot: {rules['notes']}")
    
    return "\n".join(lines)


def inject_dynamic_rules_into_prompt(prompt: str, agent_name: str = "Trader") -> str:
    """
    Dinamik kuralları prompt'a enjekte et. Tüm ajanlar için sanitization uygulanır.

    Args:
        prompt: Orijinal prompt
        agent_name: Ajan adı (Trader, RiskManager, vb.)

    Returns:
        Güncellenmiş prompt (sanitize edilmiş kurallar ile)
    """
    rules_context = get_dynamic_rules_context()

    if not rules_context:
        return prompt

    # Security: Sanitize rules for ALL agents (not just trader)
    sanitized_rules = sanitize_dynamic_rules(rules_context)
    logger.debug("Dynamic rules sanitized for %s: %d chars (original: %d)", agent_name, len(sanitized_rules), len(rules_context))

    return f"{prompt}\n\n{sanitized_rules}"


if __name__ == "__main__":
    # Test
    context = get_dynamic_rules_context()
    
    if context:
        print("Dinamik Kurallar:")
        print("=" * 60)
        print(context)
    else:
        print("Henüz dinamik kural bulunamadı")
