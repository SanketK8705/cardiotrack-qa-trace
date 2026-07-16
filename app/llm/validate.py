from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class GeneratedTestCase(BaseModel):
    title: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)


class GeneratedTestCases(BaseModel):
    test_cases: list[GeneratedTestCase] = Field(min_length=3, max_length=5)


class LLMGenerationResult(BaseModel):
    status: Literal["success", "failed"]
    raw_response: str
    parsed_test_cases: list[GeneratedTestCase]
    attempts: int
    errors: list[str] = Field(default_factory=list)


def parse_test_cases(raw_response: str) -> GeneratedTestCases:
    data = json.loads(raw_response)
    return GeneratedTestCases.model_validate(data)


def generate_with_retries(
    prompt: str,
    llm_call: Callable[[str], str],
    *,
    max_attempts: int = 3,
) -> LLMGenerationResult:
    errors: list[str] = []
    raw_response = ""

    for attempt in range(1, max_attempts + 1):
        try:
            raw_response = llm_call(prompt)
            parsed = parse_test_cases(raw_response)
            return LLMGenerationResult(
                status="success",
                raw_response=raw_response,
                parsed_test_cases=parsed.test_cases,
                attempts=attempt,
                errors=errors,
            )
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            errors.append(f"attempt {attempt}: {exc}")

    return LLMGenerationResult(
        status="failed",
        raw_response=raw_response,
        parsed_test_cases=[],
        attempts=max_attempts,
        errors=errors,
    )
