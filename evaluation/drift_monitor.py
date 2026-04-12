"""
LLM Concept Drift Monitor
==========================
Tracks prediction accuracy over time with time-decay weighting,
statistical significance testing, magnitude-aware drift analysis,
and per-agent accuracy tracking.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

DRIFT_HISTORY_FILE = DATA_DIR / "drift_history.jsonl"
_drift_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _exp_weight(age_seconds: float, half_life_seconds: float = 7 * 86400) -> float:
    if age_seconds <= 0:
        return 1.0
    return math.exp(-math.log(2) * age_seconds / half_life_seconds)


def _binomial_p_value(successes: int, trials: int, p_null: float = 0.5) -> float:
    if trials == 0:
        return 1.0
    observed = successes / trials
    if observed >= p_null:
        return 1.0
    from math import comb

    p = 0.0
    for k in range(successes + 1):
        p += comb(trials, k) * (p_null**k) * ((1 - p_null) ** (trials - k))
    return p


class DriftMonitor:
    """LLM Concept Drift ve İsabet Oranı Takipçisi."""

    def __init__(self, half_life_days: float = 7.0) -> None:
        self.half_life_seconds = half_life_days * 86400
        self._history: list[dict[str, Any]] = []
        self._load_history()

    def _load_history(self) -> None:
        if DRIFT_HISTORY_FILE.exists():
            with open(DRIFT_HISTORY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._history.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        logger.info("Drift history loaded: %d records", len(self._history))

    def _append_history(self, record: dict[str, Any]) -> None:
        record["logged_at"] = _now_iso()
        with _drift_lock:
            with open(DRIFT_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._history.append(record)

    def update_accuracy(
        self,
        symbol: str,
        predicted_direction: str,
        actual_direction: str,
        confidence: float = 0.5,
        magnitude_error: float = 0.0,
        agent_name: str = "analyst",
    ) -> float:
        correct = 1 if predicted_direction == actual_direction else 0
        record = {
            "symbol": symbol,
            "predicted_direction": predicted_direction,
            "actual_direction": actual_direction,
            "correct": correct,
            "confidence": confidence,
            "magnitude_error": magnitude_error,
            "agent_name": agent_name,
        }
        self._append_history(record)
        return self.get_agent_accuracy(symbol, agent_name)

    def get_agent_accuracy(self, symbol: str, agent_name: str | None = None) -> float:
        now = datetime.now(timezone.utc)
        weighted_correct = 0.0
        weighted_total = 0.0

        for r in self._history:
            if r["symbol"] != symbol:
                continue
            if agent_name is not None and r.get("agent_name") != agent_name:
                continue
            try:
                ts = _parse_ts(r["logged_at"])
                age = (now - ts).total_seconds()
            except (ValueError, KeyError):
                continue
            w = _exp_weight(age, self.half_life_seconds)
            weighted_correct += w * r["correct"]
            weighted_total += w

        if weighted_total == 0:
            return 0.60  # Yeni semboller için varsayılan (engelleme)
        return weighted_correct / weighted_total

    def is_significant_drift(
        self, symbol: str, threshold: float = 0.05, agent_name: str | None = None
    ) -> bool:
        successes = 0
        trials = 0
        now = datetime.now(timezone.utc)

        for r in self._history:
            if r["symbol"] != symbol:
                continue
            if agent_name is not None and r.get("agent_name") != agent_name:
                continue
            try:
                ts = _parse_ts(r["logged_at"])
                age = (now - ts).total_seconds()
            except (ValueError, KeyError):
                continue
            w = _exp_weight(age, self.half_life_seconds)
            if w < 0.01:
                continue
            trials += 1
            if r["correct"]:
                successes += 1

        if trials < 5:
            return False
        p_value = _binomial_p_value(successes, trials)
        is_drift = p_value < threshold
        if is_drift:
            logger.warning(
                "Significant drift detected for %s: p=%.4f (successes=%d, trials=%d)",
                symbol,
                p_value,
                successes,
                trials,
            )
        return is_drift

    def get_heatmap_data(self, days: int = 30) -> dict[str, dict[str, float]]:
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - days * 86400
        daily: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

        for r in self._history:
            try:
                ts = _parse_ts(r["logged_at"])
            except (ValueError, KeyError):
                continue
            if ts.timestamp() < cutoff:
                continue
            day_key = ts.strftime("%Y-%m-%d")
            symbol = r["symbol"]
            daily[symbol][day_key].append(r["correct"])

        heatmap: dict[str, dict[str, float]] = {}
        for symbol, days_data in daily.items():
            heatmap[symbol] = {}
            for day_key, results in days_data.items():
                accuracy = sum(results) / len(results) if results else 0.0
                heatmap[symbol][day_key] = round(accuracy, 4)

        return heatmap

    def is_drift_worsening(
        self, symbol: str, window: int = 7, agent_name: str | None = None
    ) -> bool:
        now = datetime.now(timezone.utc)
        recent_cutoff = now.timestamp() - window * 86400
        older_cutoff = now.timestamp() - 2 * window * 86400

        recent_correct = 0.0
        recent_total = 0.0
        older_correct = 0.0
        older_total = 0.0

        for r in self._history:
            if r["symbol"] != symbol:
                continue
            if agent_name is not None and r.get("agent_name") != agent_name:
                continue
            try:
                ts = _parse_ts(r["logged_at"])
                t = ts.timestamp()
            except (ValueError, KeyError):
                continue
            if t < older_cutoff:
                continue
            w = _exp_weight((now - ts).total_seconds(), self.half_life_seconds)
            if t >= recent_cutoff:
                recent_correct += w * r["correct"]
                recent_total += w
            else:
                older_correct += w * r["correct"]
                older_total += w

        if recent_total == 0 or older_total == 0:
            return False

        recent_acc = recent_correct / recent_total
        older_acc = older_correct / older_total
        return recent_acc < older_acc - 0.05

    def get_drift_summary(self) -> dict[str, Any]:
        symbols = set(r["symbol"] for r in self._history if "symbol" in r)
        agents = set(
            r.get("agent_name", "unknown") for r in self._history if "agent_name" in r
        )

        summary: dict[str, Any] = {
            "total_records": len(self._history),
            "symbols_tracked": sorted(symbols),
            "agents_tracked": sorted(agents),
            "per_symbol": {},
            "per_agent": {},
            "worsening_drifts": [],
            "significant_drifts": [],
            "generated_at": _now_iso(),
        }

        for symbol in symbols:
            acc = self.get_agent_accuracy(symbol)
            sig = self.is_significant_drift(symbol)
            worsening = self.is_drift_worsening(symbol)
            summary["per_symbol"][symbol] = {
                "accuracy": round(acc, 4),
                "significant_drift": sig,
                "worsening": worsening,
            }
            if sig:
                summary["significant_drifts"].append(symbol)
            if worsening:
                summary["worsening_drifts"].append(symbol)

        for agent in agents:
            agent_symbols = set(
                r["symbol"] for r in self._history if r.get("agent_name") == agent
            )
            agent_accs = {}
            for sym in agent_symbols:
                agent_accs[sym] = round(self.get_agent_accuracy(sym, agent), 4)
            summary["per_agent"][agent] = agent_accs

        return summary
