"""
JSON Utility Functions
=======================
LLM yanıtlarından JSON çıkarma, validasyon ve dönüşüm işlemleri.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict[str, Any]:
    """
    LLM yanıtından JSON bloğunu çıkarır.

    Sırayla dener:
    1. ```json ... ``` bloğu
    2. Düz JSON parse
    3. { ... } regex bloğu

    Args:
        text: LLM ham yanıtı

    Returns:
        Ayrıştırılmış dict veya boş dict
    """
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("JSON çıkarılamadı, ham yanıt: %s", text[:200])
    return {}
