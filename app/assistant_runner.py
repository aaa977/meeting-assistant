"""周期读取转录文本并生成离线实时辅助提示。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.llm_client import LlmError, OpenAiCompatibleClient
from app.models import LlmAssistantHint


LOGGER = logging.getLogger(__name__)


class AssistantRunnerError(Exception):
    """实时辅助读取、解析或写入失败。"""


async def run_assistant_loop(
    transcript_path: Path,
    assistant_path: Path,
    llm_client: OpenAiCompatibleClient,
    interval_sec: int = 30,
) -> None:
    """持续监控转录变化，生成提示并追加到实时辅助文件。"""
    transcript_path = Path(transcript_path)
    assistant_path = Path(assistant_path)
    if interval_sec <= 0:
        raise AssistantRunnerError("实时辅助间隔必须大于 0 秒。")
    if not transcript_path.is_file():
        raise AssistantRunnerError(f"找不到转录文件：{transcript_path}")

    LOGGER.info("LLM 模拟开始：实时辅助。")
    try:
        while True:
            transcript_text = _read_transcript(transcript_path)
            if transcript_text.strip():
                hint = await _generate_hint(llm_client, transcript_text)
                _append_hint(assistant_path, hint)
                _print_hint(hint)
            await asyncio.sleep(interval_sec)
    finally:
        LOGGER.info("LLM 模拟结束：实时辅助。")


def _read_transcript(transcript_path: Path) -> str:
    """读取 UTF-8 转录文件。"""
    try:
        return transcript_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise AssistantRunnerError(f"无法读取转录文件：{error}") from error


async def _generate_hint(
    llm_client: OpenAiCompatibleClient,
    transcript_text: str,
) -> LlmAssistantHint:
    """请求结构化辅助 JSON 并转换为数据模型。"""
    recent_text = transcript_text[-6000:]
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "assistant_hint_json：仅返回 JSON，字段为 terms、key_points、"
                "risks、follow_up，每个字段都是字符串数组。"
            ),
        },
        {"role": "user", "content": recent_text},
    ]
    response_text = await llm_client.chat(messages)
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise LlmError("LLM 实时辅助结果不是有效 JSON。") from error
    if not isinstance(data, dict):
        raise LlmError("LLM 实时辅助结果必须是 JSON 对象。")
    return LlmAssistantHint(
        terms=_string_list(data, "terms"),
        key_points=_string_list(data, "key_points"),
        risks=_string_list(data, "risks"),
        follow_up=_string_list(data, "follow_up"),
    )


async def generate_assistant_hint(
    llm_client: OpenAiCompatibleClient,
    transcript_text: str,
) -> LlmAssistantHint:
    """公开的单次辅助提示生成接口，供实时流水线复用。"""
    return await _generate_hint(llm_client, transcript_text)


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    """读取 JSON 中的字符串数组。"""
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LlmError(f"LLM 返回字段 {key} 必须是字符串数组。")
    return [item.strip() for item in value if item.strip()]


def _append_hint(assistant_path: Path, hint: LlmAssistantHint) -> None:
    """把一次提示以 Markdown 形式追加到实时辅助文件。"""
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    section = (
        f"\n\n## 离线辅助更新 {timestamp}\n\n"
        f"### 术语解释\n{_markdown_items(hint.terms)}\n\n"
        f"### 关键点\n{_markdown_items(hint.key_points)}\n\n"
        f"### 风险\n{_markdown_items(hint.risks)}\n\n"
        f"### 待追问问题\n{_markdown_items(hint.follow_up)}\n"
    )
    try:
        assistant_path.parent.mkdir(parents=True, exist_ok=True)
        with assistant_path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(section)
    except OSError as error:
        raise AssistantRunnerError(f"无法写入实时辅助文件：{error}") from error


def append_assistant_hint(assistant_path: Path, hint: LlmAssistantHint) -> None:
    """公开的辅助提示追加接口。"""
    _append_hint(Path(assistant_path), hint)


def _markdown_items(items: list[str]) -> str:
    """把文本列表转换为 Markdown 列表。"""
    return "\n".join(f"- {item}" for item in items) or "- <模拟暂无内容>"


def _print_hint(hint: LlmAssistantHint) -> None:
    """在终端显示本次辅助提示的简短摘要。"""
    term = hint.terms[0] if hint.terms else "<模拟暂无新术语>"
    key_point = hint.key_points[0] if hint.key_points else "<模拟暂无关键点>"
    risk = hint.risks[0] if hint.risks else "<模拟暂无风险>"
    follow_up = hint.follow_up[0] if hint.follow_up else "<模拟暂无待追问问题>"
    print(f"🛈 新术语：{term}", flush=True)
    print(f"🛈 关键点：{key_point}", flush=True)
    print(f"⚠ 风险：{risk}", flush=True)
    print(f"🛈 待追问：{follow_up}", flush=True)


def print_assistant_hint(hint: LlmAssistantHint) -> None:
    """公开的终端提示输出接口。"""
    _print_hint(hint)
