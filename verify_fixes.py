"""Verify all 30 fixes are present in the codebase."""

import sys

checks = []

# P1
with open("agents/rl_environment.py", encoding="utf-8") as f:
    c = f.read()
    checks.append(("P1: RL obs training/inference", "if self.training:" in c))

# P2
with open("agents/trader.py") as f:
    c = f.read()
    checks.append(
        ("P2: Trader blending fix", '"buy_large": 4' in c and '"sell": 0' in c)
    )

# P3
with open("scripts/run_live.py") as f:
    c = f.read()
    checks.append(
        (
            "P3: CircuitBreaker shared",
            "circuit_breaker: CircuitBreaker | None = None" in c,
        )
    )

# P4
with open("scripts/run_live.py") as f:
    c = f.read()
    checks.append(("P4: result = None init", "result = None" in c))

# P5
with open("execution/paper_engine.py") as f:
    c = f.read()
    checks.append(("P5: No double slippage", "exec_price = pos_price" in c))

# P6
with open("scripts/run_live.py") as f:
    c = f.read()
    checks.append(
        ("P6: Portfolio single load", c.count("PortfolioState.load_from_file()") == 1)
    )

# P7
with open("data/sentiment_store.py") as f:
    c = f.read()
    checks.append(
        ("P7: SentimentStore Lock", "threading.Lock()" in c and "with self._lock:" in c)
    )

# P8
with open("risk/portfolio.py") as f:
    c = f.read()
    checks.append(
        ("P8: Portfolio Lock", "_portfolio_lock" in c and "with _portfolio_lock:" in c)
    )

# P9
with open("agents/prompt_evolver.py") as f:
    c = f.read()
    checks.append(
        ("P9: PromptEvolver Lock + atomic", "_manifest_lock" in c and ".tmp" in c)
    )

# P10
with open("evaluation/drift_monitor.py") as f:
    c = f.read()
    checks.append(("P10: DriftMonitor Lock", "_drift_lock" in c))

# P11
with open("agents/debate.py") as f:
    c = f.read()
    checks.append(
        ("P11: Debate JSON schema", '"key_points"' in c and '"supporting_data"' in c)
    )

# P12
with open("agents/research_analyst.py") as f:
    c = f.read()
    checks.append(
        ("P12: Parse error logging", "__parse_error__" in c and "parse_error" in c)
    )

# P13
with open("agents/debate.py") as f:
    c = f.read()
    checks.append(("P13: No bare except", "except Exception as e:" in c))

# P14
with open("agents/risk_manager.py") as f:
    c = f.read()
    checks.append(("P14: Risk LLM conditional", "if checks_failed:" in c))

# P15
with open("agents/retrospective_agent.py") as f:
    c = f.read()
    checks.append(("P15: Retrospective retry", "invoke_with_retry" in c))

# P16
with open("dashboard/index.html") as f:
    c = f.read()
    checks.append(("P16: Dashboard ID fix", "sentimentValue" in c))

# P17
with open("dashboard/app.js") as f:
    c = f.read()
    checks.append(("P17: API key header", "apiFetch" in c and "X-API-Key" in c))

# P18
with open("monitoring/prometheus.yml") as f:
    c = f.read()
    checks.append(("P18: Prometheus port", "bot:8000" in c))

# P19
with open("monitoring/grafana-dashboard.json") as f:
    c = f.read()
    checks.append(
        ("P19: Grafana clean", "rl_reward" not in c and "drift_accuracy" not in c)
    )

# P20
with open("dashboard/index.html") as f:
    c = f.read()
    checks.append(
        ("P20: Benchmark HTML", "benchmarkSymbol" in c and "benchmarkReturn" in c)
    )

# P21
with open("agents/prompt_evolver.py") as f:
    c = f.read()
    checks.append(("P21: Prompt max length", "MAX_PROMPT_LENGTH" in c))

# P22
with open("risk/cvar_optimizer.py") as f:
    c = f.read()
    checks.append(("P22: default_rng", "np.random.default_rng" in c))

# P23
with open("risk/circuit_breaker.py") as f:
    c = f.read()
    checks.append(
        (
            "P23: Resume resets counters",
            "def resume(self)" in c and "self.consecutive_losses = 0" in c,
        )
    )

# P24
with open("agents/graph.py") as f:
    c = f.read()
    checks.append(
        (
            "P24: trim_messages in graph",
            "trim_messages" in c and 'add_node("trim_messages"' in c,
        )
    )

# P25
with open("models/sentiment_analyzer.py") as f:
    c = f.read()
    checks.append(("P25: TTLCache guard", "and self._timestamps" in c))

# P26
with open("agents/ensemble_voter.py") as f:
    c = f.read()
    checks.append(("P26: Ensemble worker cap", "min(len(target_models), 3)" in c))

# P27
with open("data/symbol_resolver.py") as f:
    c = f.read()
    checks.append(("P27: CRYPTO_BASES update", "CRYPTO_BASES.clear()" in c))

# P28
with open("evaluation/drift_monitor.py") as f:
    c = f.read()
    checks.append(("P28: Drift default 0.0", "return 0.0" in c))

# P29
with open("utils/llm_retry.py") as f:
    c = f.read()
    checks.append(("P29: Retry jitter", "random.uniform" in c))

# P30
with open("config/settings.py") as f:
    c = f.read()
    checks.append(
        (
            "P30: LLMParams + max_correlation",
            "class LLMParams" in c and "max_correlation_threshold" in c,
        )
    )

passed = sum(1 for _, ok in checks if ok)
failed = sum(1 for _, ok in checks if not ok)

for name, ok in checks:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")

print(f"\n{passed}/30 verified, {failed} failed")
if failed > 0:
    sys.exit(1)
