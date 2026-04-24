import pytest
from unittest.mock import patch, MagicMock

from agents.risk_manager import risk_manager_node
from agents.state import create_initial_state
from config.settings import TradingParams

# A dummy TradingParams object to use in tests
def mock_get_trading_params():
    params = TradingParams()
    params.risk.max_open_positions = 5
    params.risk.max_drawdown_pct = 0.15
    params.risk.max_daily_loss_pct = 0.03
    params.risk.max_position_pct = 0.05
    params.stop_loss.atr_multiplier = 2.5
    params.limits.min_risk_reward = 1.5
    return params

def create_mock_state():
    state = create_initial_state("BTC/USDT")
    state["sentiment"] = {"confidence": 0.8, "signal": "neutral"}
    state["debate_result"] = {"consensus_score": 0.8, "hallucinations_detected": []}
    state["technical_signals"] = {"signal": "neutral", "current_price": 50000, "atr_14": 1000}
    state["portfolio_state"] = {
        "open_positions": 2,
        "current_drawdown": 0.05,
        "equity": 10000,
        "daily_pnl": 100
    }
    return state

@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
@patch("agents.risk_manager.create_agent_llm")
@patch("agents.risk_manager.invoke_with_retry")
def test_risk_manager_basic_structure(mock_invoke, mock_create_llm, mock_drift, mock_params):
    # Setup mocks
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8
    mock_invoke.return_value = {"decision": "approved", "approved_size": 500}

    state = create_mock_state()

    result = risk_manager_node(state)

    # Assert basic structure
    assert "messages" in result
    assert "risk_assessment" in result
    assert "risk_approved" in result
    assert "phase" in result

    assert isinstance(result["risk_assessment"], dict)
    assert "decision" in result["risk_assessment"]
    assert "approved_size" in result["risk_assessment"]
    assert "stop_loss_level" in result["risk_assessment"]
    assert "take_profit_level" in result["risk_assessment"]

@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
def test_risk_manager_max_open_positions(mock_drift, mock_params):
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8

    state = create_mock_state()
    state["portfolio_state"]["open_positions"] = 6 # > max 5

    result = risk_manager_node(state)

    assert result["risk_approved"] is False
    assert result["phase"] == "analysis"
    assert result["risk_assessment"]["decision"] == "rejected"
    assert any("Max pozisyon limiti aşıldı" in msg for msg in result["risk_assessment"]["checks_failed"])
    assert result["risk_assessment"]["approved_size"] == 0

@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
def test_risk_manager_max_drawdown(mock_drift, mock_params):
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8

    state = create_mock_state()
    state["portfolio_state"]["current_drawdown"] = 0.20 # > max 0.15

    result = risk_manager_node(state)

    assert result["risk_approved"] is False
    assert result["phase"] == "analysis"
    assert result["risk_assessment"]["decision"] == "rejected"
    assert any("Drawdown limiti aşıldı" in msg for msg in result["risk_assessment"]["checks_failed"])

@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
def test_risk_manager_max_daily_loss(mock_drift, mock_params):
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8

    state = create_mock_state()
    state["portfolio_state"]["daily_pnl"] = -400 # 400 / 10000 = 0.04 > max 0.03

    result = risk_manager_node(state)

    assert result["risk_approved"] is False
    assert result["phase"] == "analysis"
    assert result["risk_assessment"]["decision"] == "rejected"
    assert any("Günlük kayıp limiti aşıldı" in msg for msg in result["risk_assessment"]["checks_failed"])


@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
@patch("agents.risk_manager.create_agent_llm")
@patch("agents.risk_manager.invoke_with_retry")
def test_risk_manager_llm_approved(mock_invoke, mock_create_llm, mock_drift, mock_params):
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8
    # 10000 * 0.05 = 500, so 400 is within max_allowed limit
    mock_invoke.return_value = {"decision": "approved", "approved_size": 400}

    state = create_mock_state()
    # Ensure debate and sentiment are not purely neutral to bypass the neutral-neutral check
    state["debate_result"]["adjusted_signal"] = "bullish"

    result = risk_manager_node(state)

    assert result["risk_approved"] is True
    assert result["phase"] == "trade"
    assert result["risk_assessment"]["decision"] == "approved"
    assert result["risk_assessment"]["approved_size"] == 400

@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
@patch("agents.risk_manager.create_agent_llm")
@patch("agents.risk_manager.invoke_with_retry")
def test_risk_manager_llm_exceeds_max_size(mock_invoke, mock_create_llm, mock_drift, mock_params):
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8
    # max_allowed is 10000 * 0.05 = 500. 600 > 500
    mock_invoke.return_value = {"decision": "approved", "approved_size": 600}

    state = create_mock_state()
    state["debate_result"]["adjusted_signal"] = "bullish"

    result = risk_manager_node(state)

    assert result["risk_approved"] is False
    assert result["phase"] == "analysis"
    assert result["risk_assessment"]["decision"] == "rejected"
    assert any("LLM önerilen pozisyon boyutu limiti aştı" in msg for msg in result["risk_assessment"]["checks_failed"])

@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
@patch("agents.risk_manager.create_agent_llm")
@patch("agents.risk_manager.invoke_with_retry")
def test_risk_manager_llm_fallback_on_error(mock_invoke, mock_create_llm, mock_drift, mock_params):
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8
    # Mock invoke_with_retry to simulate throwing an exception
    mock_invoke.side_effect = Exception("API timeout")

    state = create_mock_state()
    state["debate_result"]["adjusted_signal"] = "bullish"

    result = risk_manager_node(state)

    assert result["risk_approved"] is False
    assert result["phase"] == "analysis"
    assert result["risk_assessment"]["decision"] == "rejected"
    assert result["risk_assessment"]["approved_size"] == 0

@patch("agents.risk_manager.get_trading_params", side_effect=mock_get_trading_params)
@patch("agents.risk_manager._get_drift_monitor")
@patch("agents.risk_manager.create_agent_llm")
@patch("agents.risk_manager.invoke_with_retry")
def test_risk_manager_llm_empty_response(mock_invoke, mock_create_llm, mock_drift, mock_params):
    mock_drift.return_value.get_agent_accuracy.return_value = 0.8
    # Empty response mock
    mock_invoke.return_value = {}

    state = create_mock_state()
    state["debate_result"]["adjusted_signal"] = "bullish"

    result = risk_manager_node(state)

    assert result["risk_approved"] is False
    assert result["phase"] == "analysis"
    assert result["risk_assessment"]["decision"] == "rejected"
