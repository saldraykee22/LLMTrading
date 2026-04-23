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
        except json.JSONDecodeError as e:
            logger.debug("JSONDecodeError in block parsing: %s", e)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.debug("JSONDecodeError in direct parsing: %s", e)

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError as e:
            logger.debug("JSONDecodeError in brace parsing: %s", e)

    # Fallback: json.JSONDecoder.raw_decode (nested JSON güvenli)
    try:
        decoder = json.JSONDecoder()
        start_idx = text.find("{")
        if start_idx != -1:
            obj, _ = decoder.raw_decode(text, start_idx)
            if isinstance(obj, dict):
                return obj
    except (json.JSONDecodeError, ValueError):
        pass

    logger.error("JSON parse FAILED — raw response (first 300 chars): %s", text[:300])
    return {"__parse_error__": True, "__raw_text__": text[:500]}


def extract_json_array(text: str) -> list[dict[str, Any]]:
    """
    LLM yanıtından JSON array çıkarır (Lead Scout vb. için).

    Sırayla dener:
    1. ```json ... ``` bloğu
    2. Düz JSON parse
    3. [ ... ] regex bloğu

    Args:
        text: LLM ham yanıtı

    Returns:
        Ayrıştırılmış list veya boş list
    """
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(1))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError as e:
            logger.debug("JSONDecodeError in block parsing: %s", e)

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError as e:
        logger.debug("JSONDecodeError in direct parsing: %s", e)

    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            result = json.loads(bracket_match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError as e:
            logger.debug("JSONDecodeError in bracket parsing: %s", e)

    # Fallback: json.JSONDecoder.raw_decode (nested JSON güvenli)
    try:
        decoder = json.JSONDecoder()
        start_idx = text.find("[")
        if start_idx != -1:
            obj, _ = decoder.raw_decode(text, start_idx)
            if isinstance(obj, list):
                return obj
    except (json.JSONDecodeError, ValueError):
        pass

    logger.error("JSON array parse FAILED — raw response (first 300 chars): %s", text[:300])
    return []
