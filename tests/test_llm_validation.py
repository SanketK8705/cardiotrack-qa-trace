import json
import pytest
from pydantic import ValidationError

from app.llm.validate import (
    generate_with_retries,
    parse_test_cases,
    GeneratedTestCases,
)


def test_valid_response_parses_successfully() -> None:
    # 1. Mock LLM client returning valid JSON matching schema (needs at least 3 test cases)
    valid_response = {
        "test_cases": [
            {
                "title": "Verify cardiograph normal status",
                "steps": [
                    "Power on device",
                    "Observe LED color",
                ],
                "expected_result": "LED turns green indicating normal status",
            },
            {
                "title": "Verify cardiograph low battery status",
                "steps": [
                    "Drain battery below 10%",
                    "Power on device",
                ],
                "expected_result": "LED flashes amber indicating low battery",
            },
            {
                "title": "Verify cardiograph error status",
                "steps": [
                    "Simulate sensor disconnect",
                    "Power on device",
                ],
                "expected_result": "LED turns red and error code E01 is displayed",
            },
        ]
    }
    raw_json = json.dumps(valid_response)

    def mock_llm_call(prompt: str) -> str:
        return raw_json

    # 2. Assert validation passes and returns parsed test cases
    result = generate_with_retries(
        prompt="Generate cardiograph test cases",
        llm_call=mock_llm_call,
        max_attempts=3,
    )

    assert result.status == "success"
    assert result.attempts == 1
    assert len(result.parsed_test_cases) == 3
    assert result.parsed_test_cases[0].title == "Verify cardiograph normal status"
    assert result.parsed_test_cases[0].steps == ["Power on device", "Observe LED color"]
    assert (
        result.parsed_test_cases[0].expected_result
        == "LED turns green indicating normal status"
    )
    assert len(result.errors) == 0


def test_malformed_response_triggers_retry_then_fails() -> None:
    attempts_count = 0

    # 1. Mock invalid JSON on all attempts
    def mock_llm_call_malformed(prompt: str) -> str:
        nonlocal attempts_count
        attempts_count += 1
        return "Not a valid JSON response {"

    # 2. Assert retries expected count then fails status, no fabricated data
    result = generate_with_retries(
        prompt="Generate cardiograph test cases",
        llm_call=mock_llm_call_malformed,
        max_attempts=3,
    )

    assert result.status == "failed"
    assert attempts_count == 3
    assert result.attempts == 3
    assert result.parsed_test_cases == []
    assert len(result.errors) == 3
    # Check that it returns the last raw response and contains JSON decode errors
    assert result.raw_response == "Not a valid JSON response {"
    
    # Assert each error record contains the attempt info
    for i, err in enumerate(result.errors):
        assert f"attempt {i+1}:" in err
        assert len(err) > len(f"attempt {i+1}:")


def test_valid_json_wrong_shape_fails_validation() -> None:
    # 1. Mock valid JSON missing required field (no 'steps')
    invalid_shape_response = {
        "test_cases": [
            {
                "title": "Verify cardiograph normal status",
                # missing 'steps'
                "expected_result": "LED turns green indicating normal status",
            },
            {
                "title": "Verify cardiograph low battery status",
                # missing 'steps'
                "expected_result": "LED flashes amber indicating low battery",
            },
            {
                "title": "Verify cardiograph error status",
                # missing 'steps'
                "expected_result": "LED turns red and error code E01 is displayed",
            },
        ]
    }
    raw_json = json.dumps(invalid_shape_response)

    # 2. Assert Pydantic rejects it directly
    with pytest.raises(ValidationError) as exc_info:
        parse_test_cases(raw_json)

    assert "steps" in str(exc_info.value)
    assert "Field required" in str(exc_info.value)

    # 3. Assert it is treated as a failure in retry loop, not silently accepted
    def mock_llm_call_wrong_shape(prompt: str) -> str:
        return raw_json

    result = generate_with_retries(
        prompt="Generate cardiograph test cases",
        llm_call=mock_llm_call_wrong_shape,
        max_attempts=3,
    )

    assert result.status == "failed"
    assert result.attempts == 3
    assert result.parsed_test_cases == []
    assert len(result.errors) == 3
    for i, err in enumerate(result.errors):
        assert f"attempt {i+1}:" in err
        assert "validation" in err.lower() or "value" in err.lower() or "required" in err.lower()
