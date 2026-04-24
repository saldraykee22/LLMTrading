import json
import pytest
from unittest.mock import MagicMock, patch, call
from utils.llm_retry import invoke_with_retry

class TestInvokeWithRetry:

    def test_success_first_attempt(self):
        """Test successful invocation on the first attempt without retries."""
        mock_fn = MagicMock(return_value="Success")
        result = invoke_with_retry(mock_fn, max_retries=3)

        assert result == "Success"
        mock_fn.assert_called_once()

    def test_success_after_retries(self):
        """Test successful invocation after initial failures."""
        mock_fn = MagicMock(side_effect=[ValueError("Error 1"), ValueError("Error 2"), "Success"])

        with patch('time.sleep') as mock_sleep:
            result = invoke_with_retry(mock_fn, max_retries=3, base_delay=1.0)

        assert result == "Success"
        assert mock_fn.call_count == 3
        assert mock_sleep.call_count == 2

    def test_failure_after_max_retries(self):
        """Test failure after max_retries is reached."""
        mock_fn = MagicMock(side_effect=ValueError("Persistent Error"))

        with patch('time.sleep') as mock_sleep:
            with pytest.raises(ValueError, match="Persistent Error"):
                invoke_with_retry(mock_fn, max_retries=3, base_delay=1.0)

        assert mock_fn.call_count == 3
        assert mock_sleep.call_count == 2

    @patch('random.uniform', return_value=1.0)
    def test_exponential_backoff_delays(self, mock_random):
        """Test that delay calculations follow exponential backoff."""
        mock_fn = MagicMock(side_effect=ValueError("Error"))

        with patch('time.sleep') as mock_sleep:
            with pytest.raises(ValueError):
                invoke_with_retry(mock_fn, max_retries=4, base_delay=2.0, max_delay=10.0)

        assert mock_sleep.call_count == 3
        # Attempt 0 -> delay = min(2.0 * 2^0, 10.0) = 2.0
        # Attempt 1 -> delay = min(2.0 * 2^1, 10.0) = 4.0
        # Attempt 2 -> delay = min(2.0 * 2^2, 10.0) = 8.0
        mock_sleep.assert_has_calls([call(2.0), call(4.0), call(8.0)])

    def test_empty_response_raises_value_error(self):
        """Test that empty response raises ValueError."""
        # Empty string
        mock_fn = MagicMock(return_value="")

        with patch('time.sleep'):
            with pytest.raises(ValueError, match="LLM empty response"):
                invoke_with_retry(mock_fn, max_retries=1)

    def test_json_validation_valid(self):
        """Test valid JSON passes."""
        valid_json_str = '{"key": "value"}'
        mock_fn = MagicMock(return_value=valid_json_str)

        result = invoke_with_retry(mock_fn, validate_json=True, max_retries=1)
        assert result == valid_json_str

    def test_json_validation_invalid(self):
        """Test invalid JSON fails and retries."""
        mock_fn = MagicMock(side_effect=["invalid json", '{"key": "value"}'])

        with patch('time.sleep') as mock_sleep:
            result = invoke_with_retry(mock_fn, validate_json=True, max_retries=2)

        assert result == '{"key": "value"}'
        assert mock_fn.call_count == 2
        assert mock_sleep.call_count == 1

    def test_json_validation_with_markdown_blocks(self):
        """Test JSON validation strips markdown blocks."""
        markdown_json = "```json\n{\"key\": \"value\"}\n```"
        mock_fn = MagicMock(return_value=markdown_json)

        result = invoke_with_retry(mock_fn, validate_json=True, max_retries=1)
        assert result == markdown_json

    def test_timeout_kwarg_propagation(self):
        """Test that request_timeout is added to kwargs as timeout."""
        mock_fn = MagicMock(return_value="Success")

        invoke_with_retry(mock_fn, request_timeout=45, other_arg="test")

        # Check that timeout=45 is in the kwargs of the mock_fn call
        mock_fn.assert_called_once_with(timeout=45, other_arg="test")

    def test_schema_validation_success(self):
        """Test successful Pydantic schema validation."""
        try:
            from pydantic import BaseModel
        except ImportError:
            pytest.skip("Pydantic not installed")

        class MySchema(BaseModel):
            name: str
            age: int

        mock_fn = MagicMock(return_value='{"name": "Alice", "age": 30}')

        result = invoke_with_retry(mock_fn, response_schema=MySchema, max_retries=1)
        assert result == '{"name": "Alice", "age": 30}'

    def test_schema_validation_failure(self):
        """Test failed Pydantic schema validation."""
        try:
            from pydantic import BaseModel
        except ImportError:
            pytest.skip("Pydantic not installed")

        class MySchema(BaseModel):
            name: str
            age: int

        # missing age
        mock_fn = MagicMock(side_effect=['{"name": "Alice"}', '{"name": "Alice", "age": 30}'])

        with patch('time.sleep') as mock_sleep:
            result = invoke_with_retry(mock_fn, response_schema=MySchema, max_retries=2)

        assert result == '{"name": "Alice", "age": 30}'
        assert mock_fn.call_count == 2
        assert mock_sleep.call_count == 1
