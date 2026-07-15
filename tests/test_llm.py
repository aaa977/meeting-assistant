"""Dummy LLM 固定 JSON 契约测试。"""

import asyncio
import json

from app.llm_client import DummyLlmClient


def test_dummy_assistant_response_has_required_keys() -> None:
    client = DummyLlmClient()
    response = asyncio.run(
        client.chat(
            [
                {"role": "system", "content": "assistant_hint_json"},
                {"role": "user", "content": "会议转录"},
            ]
        )
    )
    data = json.loads(response)
    assert set(data) == {"terms", "key_points", "risks", "follow_up"}
    assert all(isinstance(value, list) for value in data.values())


def test_dummy_summary_response_has_six_sections() -> None:
    client = DummyLlmClient()
    response = asyncio.run(
        client.chat(
            [
                {"role": "system", "content": "meeting_summary_json"},
                {"role": "user", "content": "完整会议转录"},
            ]
        )
    )
    data = json.loads(response)
    assert set(data) == {
        "meeting_objectives",
        "confirmed_information",
        "key_questions",
        "risks_and_uncertainties",
        "follow_up_questions",
        "action_items",
    }
