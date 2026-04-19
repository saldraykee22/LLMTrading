"""
Self-Evolving Prompt System
=============================
Manages prompt versioning, evolution from drift/retrospective data,
and automatic rollback capabilities.

Storage:
  data/prompt_versions/{agent_name}_v{N}.txt
  data/prompt_versions/manifest.json
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR, PROMPTS_DIR

logger = logging.getLogger(__name__)

VERSIONS_DIR = DATA_DIR / "prompt_versions"
MANIFEST_FILE = VERSIONS_DIR / "manifest.json"
_manifest_lock = threading.Lock()


from functools import lru_cache

@lru_cache(maxsize=64)
def _read_prompt_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""

def _ensure_dirs() -> None:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)

def _load_manifest() -> dict[str, Any]:
    _ensure_dirs()
    with _manifest_lock:
        if MANIFEST_FILE.exists():
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    return {"agents": {}}

def _save_manifest(manifest: dict[str, Any]) -> None:
    _ensure_dirs()
    with _manifest_lock:
        tmp = MANIFEST_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        tmp.replace(MANIFEST_FILE)

def _read_original_prompt(agent_name: str) -> str:
    prompt_file = PROMPTS_DIR / f"{agent_name}.txt"
    return _read_prompt_file(prompt_file)


class PromptEvolver:
    MAX_PROMPT_LENGTH = 8000

    def store_prompt_version(
        self,
        agent_name: str,
        prompt_content: str,
        version: int,
        changelog: str,
        is_draft: bool = True,
    ) -> str:
        _ensure_dirs()
        version_str = f"v{version}_draft" if is_draft else f"v{version}"
        version_file = VERSIONS_DIR / f"{agent_name}_{version_str}.txt"
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(prompt_content)

        manifest = _load_manifest()
        if agent_name not in manifest["agents"]:
            manifest["agents"][agent_name] = {"versions": [], "current_version": 0}

        entry = {
            "version": version,
            "changelog": changelog,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file": str(version_file),
            "rolled_back": False,
            "status": "pending_review" if is_draft else "active"
        }
        manifest["agents"][agent_name]["versions"].append(entry)
        
        if not is_draft:
            manifest["agents"][agent_name]["current_version"] = version
            
        _save_manifest(manifest)

        logger.info("Prompt stored: %s %s (%s)", agent_name, version_str, changelog)
        return str(version_file)

    def get_current_prompt(self, agent_name: str) -> str:
        manifest = _load_manifest()
        agent_data = manifest.get("agents", {}).get(agent_name)
        if not agent_data or not agent_data["versions"]:
            return _read_original_prompt(agent_name)

        current_version = agent_data["current_version"]
        version_file = VERSIONS_DIR / f"{agent_name}_v{current_version}.txt"
        if version_file.exists():
            return _read_prompt_file(version_file)
        return _read_original_prompt(agent_name)

    def get_prompt_history(self, agent_name: str) -> list[dict]:
        manifest = _load_manifest()
        agent_data = manifest.get("agents", {}).get(agent_name)
        if not agent_data:
            return []
        return agent_data.get("versions", [])

    def rollback_prompt(self, agent_name: str, version: int) -> bool:
        manifest = _load_manifest()
        agent_data = manifest.get("agents", {}).get(agent_name)
        if not agent_data:
            logger.warning("Rollback failed: agent %s not found", agent_name)
            return False

        target_file = VERSIONS_DIR / f"{agent_name}_v{version}.txt"
        if not target_file.exists():
            logger.warning("Rollback failed: version file %s not found", target_file)
            return False

        for entry in agent_data["versions"]:
            entry["rolled_back"] = entry["version"] == version

        agent_data["current_version"] = version
        _save_manifest(manifest)

        logger.info("Rolled back %s to version %d", agent_name, version)
        return True

    def evolve_from_drift(self, agent_name: str, drift_data: dict) -> str:
        base_prompt = self.get_current_prompt(agent_name)
        accuracy = drift_data.get("accuracy", 1.0)
        warnings = drift_data.get("warnings", [])

        drift_section = "\n\n## DİKKAT\n"
        drift_section += f"Son drift analizi: isabet oranı %{accuracy * 100:.1f}\n"
        if warnings:
            drift_section += "Tespit edilen sorunlar:\n"
            for w in warnings:
                drift_section += f"- {w}\n"
        drift_section += "Bu uyarıları dikkate alarak karar ver.\n"

        new_prompt = base_prompt.rstrip() + drift_section

        if len(new_prompt) > self.MAX_PROMPT_LENGTH:
            lines = base_prompt.splitlines()
            while len(new_prompt) > self.MAX_PROMPT_LENGTH and len(lines) > 10:
                lines.pop(0)
                base_prompt = "\n".join(lines)
                new_prompt = base_prompt.rstrip() + drift_section
            logger.warning(
                "Prompt exceeded max length, truncated %s to %d chars",
                agent_name,
                len(new_prompt),
            )

        history = self.get_prompt_history(agent_name)
        next_version = len(history) + 1
        changelog = (
            f"Drift evolution: accuracy={accuracy:.2%}, warnings={len(warnings)}"
        )
        self.store_prompt_version(agent_name, new_prompt, next_version, changelog)

        logger.info("Evolved %s from drift: v%d", agent_name, next_version)
        return new_prompt

    def evolve_from_retrospective(
        self, agent_name: str, retrospective_lessons: list[dict]
    ) -> str:
        base_prompt = self.get_current_prompt(agent_name)

        lessons_section = "\n\n## ÖĞRENİLEN DERSLER\n"
        for lesson in retrospective_lessons:
            root_cause = lesson.get("root_cause", "")
            lesson_text = lesson.get("lesson_learned", "")
            category = lesson.get("root_cause_category", "")
            lessons_section += f"- [{category}] {root_cause} → {lesson_text}\n"
        lessons_section += "Geçmiş hatalardan ders çıkar.\n"

        new_prompt = base_prompt.rstrip() + lessons_section

        if len(new_prompt) > self.MAX_PROMPT_LENGTH:
            lines = base_prompt.splitlines()
            while len(new_prompt) > self.MAX_PROMPT_LENGTH and len(lines) > 10:
                lines.pop(0)
                base_prompt = "\n".join(lines)
                new_prompt = base_prompt.rstrip() + lessons_section
            logger.warning(
                "Prompt exceeded max length, truncated %s to %d chars",
                agent_name,
                len(new_prompt),
            )

        history = self.get_prompt_history(agent_name)
        next_version = len(history) + 1
        changelog = f"Retrospective evolution: {len(retrospective_lessons)} lessons"
        self.store_prompt_version(agent_name, new_prompt, next_version, changelog)

        logger.info("Evolved %s from retrospective: v%d", agent_name, next_version)
        return new_prompt

    def apply_evolution(self, agent_name: str) -> bool:
        from evaluation.drift_monitor import DriftMonitor

        evolved = False

        try:
            drift_monitor = DriftMonitor()
            accuracy = drift_monitor.get_agent_accuracy(agent_name)
            if accuracy < 0.60:
                drift_data = {
                    "accuracy": accuracy,
                    "warnings": [f"Agent accuracy below 60%: {accuracy:.2%}"],
                }
                self.evolve_from_drift(agent_name, drift_data)
                evolved = True
        except Exception as e:
            logger.error("Drift evolution failed for %s: %s", agent_name, e)

        try:
            from data.vector_store import AgentMemoryStore

            memory_store = AgentMemoryStore()
            lessons = memory_store.query_lessons(agent_name, n_results=5)
            if lessons:
                self.evolve_from_retrospective(agent_name, lessons)
                evolved = True
        except Exception as e:
            logger.error("Retrospective evolution failed for %s: %s", agent_name, e)

        return evolved
