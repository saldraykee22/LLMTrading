# Prompt Evolver — Self-Evolving Prompt System

## Overview

The Prompt Evolver automatically updates agent prompts when drift is detected or retrospective analysis reveals missed signals. It maintains version history and supports rollback.

## How Evolution Works

### Trigger Points

1. **Drift Detection** — When `DriftMonitor` reports agent accuracy below 60%
2. **Retrospective Analysis** — When `RetrospectiveAgent` identifies losing trades with actionable lessons

### Evolution Logic

| Trigger | Action |
|---------|--------|
| Drift detected | Appends `## DİKKAT` section with accuracy metrics and warnings |
| Retrospective lessons | Appends `## ÖĞRENİLEN DERSLER` section with root causes and lessons |
| Both | Combines both sections into comprehensive updated prompt |

### Versioning & Draft Mode (Human-in-the-loop)

- Prompt files are generated as drafts in `data/prompt_versions/{agent_name}_v{N}_draft.txt`
- Metadata is tracked in `data/prompt_versions/manifest.json` with status `"pending_review"`
- Agents continue to use the active `current_version` until a human manually approves the draft (changing the status in manifest and renaming the file). This prevents **Catastrophic Forgetting** caused by autonomous unverified modifications.
- Each version includes: changelog, timestamp, file path, rollback status

## Usage

### Automatic Evolution

```python
from agents.prompt_evolver import PromptEvolver

evolver = PromptEvolver()
evolved = evolver.apply_evolution("risk_manager")
```

This checks drift and retrospective data, evolving prompts if needed.

### Manual Evolution from Drift

```python
drift_data = {
    "accuracy": 0.45,
    "warnings": ["LLM isabet oranı düşüyor: %45.0"]
}
new_prompt = evolver.evolve_from_drift("research_analyst", drift_data)
```

### Manual Evolution from Retrospective

```python
lessons = [
    {
        "root_cause": "missed_news",
        "lesson_learned": "Check earnings calendar before entering positions",
        "root_cause_category": "missed_news"
    }
]
new_prompt = evolver.evolve_from_retrospective("trader", lessons)
```

### Viewing History

```python
history = evolver.get_prompt_history("risk_manager")
for entry in history:
    print(f"v{entry['version']}: {entry['changelog']} ({entry['timestamp']})")
```

### Rollback

```python
success = evolver.rollback_prompt("risk_manager", version=2)
```

## Integration with Agents

All agents check for evolved prompts before loading:

- `agents/research_analyst.py` — uses `PromptEvolver.get_current_prompt("research_analyst")`
- `agents/risk_manager.py` — uses `PromptEvolver.get_current_prompt("risk_manager")`
- `agents/trader.py` — uses `PromptEvolver.get_current_prompt("trader")`
- `agents/debate.py` — uses `PromptEvolver.get_current_prompt("debate_moderator")`

Fallback to original prompt files in `models/prompts/` if no evolved version exists.

## RAG Integration

The `AgentMemoryStore.query_lessons()` method retrieves retrospective lessons from the ChromaDB vector store. Lessons are queried by symbol and filtered by relevance to the agent's domain.

## Best Practices

1. **Review before deploying** — Check evolved prompts in `data/prompt_versions/` before running production trades
2. **Version control** — Commit prompt versions to git for audit trail
3. **Monitor accuracy** — Evolution should improve accuracy; if it degrades, rollback
4. **Limit prompt growth** — Excessive DİKKAT/ÖĞRENİLEN DERSLER sections can dilute prompt effectiveness; consider periodic summarization
5. **Test after rollback** — Verify agent behavior matches expected baseline after rollback

## File Structure

```
data/prompt_versions/
├── manifest.json
├── risk_manager_v1.txt
├── risk_manager_v2.txt
├── research_analyst_v1.txt
├── trader_v1.txt
└── debate_moderator_v1.txt
```

## Manifest Schema

```json
{
  "agents": {
    "risk_manager": {
      "current_version": 2,
      "versions": [
        {
          "version": 1,
          "changelog": "Initial evolution",
          "timestamp": "2026-04-05T12:00:00+00:00",
          "file": "data/prompt_versions/risk_manager_v1.txt",
          "rolled_back": false
        }
      ]
    }
  }
}
```
