from __future__ import annotations

from typing import TypedDict


class PromptNode(TypedDict):
    logical_id: str
    heading: str
    body: str


def build_test_case_prompt(nodes: list[PromptNode]) -> str:
    sections = []
    for node in nodes:
        sections.append(
            "\n".join(
                [
                    f"Logical ID: {node['logical_id']}",
                    f"Heading: {node['heading']}",
                    "Body:",
                    node["body"],
                ]
            )
        )

    source_text = "\n\n---\n\n".join(sections)
    return f"""You are a QA analyst creating concise test case ideas from selected medical-device manual sections.

Generate 3 to 5 QA test case ideas that verify the behavior, limits, and user-visible outcomes described in the selected sections.

Return ONLY valid JSON. Do not include markdown fences. Do not include prose before or after the JSON.

The JSON must have exactly this shape:
{{
  "test_cases": [
    {{
      "title": "short descriptive title",
      "steps": ["step 1", "step 2"],
      "expected_result": "observable expected result"
    }}
  ]
}}

Rules:
- Produce between 3 and 5 test cases.
- Each title must be non-empty.
- Each test case must have at least one step.
- Each expected_result must be non-empty.
- Base every test case only on the selected source sections below.

Selected source sections:
{source_text}
"""
