"""ASR JSON 与 Realtime 事件解析测试。"""

import json

import pytest

from app.asr_client import AsrError, QwenAsrClient
from app.models import AsrFinalResult, AsrResultChunk


def test_parse_direct_partial_result() -> None:
    result = QwenAsrClient._parse_result_message(
        json.dumps(
            {
                "status": 0,
                "text": "中间文本",
                "is_final": False,
                "start_time": 0,
                "end_time": 1,
            }
        )
    )
    assert isinstance(result, AsrResultChunk)
    assert result.text == "中间文本"


def test_parse_direct_final_result() -> None:
    result = QwenAsrClient._parse_result_message(
        json.dumps({"status": 0, "text": "最终文本", "is_final": True})
    )
    assert isinstance(result, AsrFinalResult)
    assert result.text == "最终文本"


def test_nonzero_status_raises_asr_error() -> None:
    with pytest.raises(AsrError, match="错误状态"):
        QwenAsrClient._parse_result_message(
            json.dumps({"status": 401, "message": "unauthorized"})
        )


def test_parse_realtime_delta_event() -> None:
    result = QwenAsrClient._parse_result_message(
        json.dumps(
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "delta": "你好",
            }
        )
    )
    assert isinstance(result, AsrResultChunk)
    assert result.text == "你好"


def test_parse_realtime_completed_event() -> None:
    result = QwenAsrClient._parse_result_message(
        json.dumps(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "会议开始",
            }
        )
    )
    assert isinstance(result, AsrFinalResult)
    assert result.text == "会议开始"


def test_control_event_is_ignored() -> None:
    result = QwenAsrClient._parse_result_message(
        json.dumps({"type": "session.created", "session": {"id": "demo"}})
    )
    assert result is None


def test_realtime_error_event_raises_asr_error() -> None:
    with pytest.raises(AsrError, match="invalid_request"):
        QwenAsrClient._parse_result_message(
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "code": "invalid_request",
                        "message": "bad payload",
                    },
                }
            )
        )
