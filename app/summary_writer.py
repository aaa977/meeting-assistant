"""分批整理完整转录并覆盖写入结构化会议纪要。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.llm_client import LlmError, OpenAiCompatibleClient
from app.models import MeetingSummary


LOGGER = logging.getLogger(__name__)
TRANSCRIPT_BATCH_CHARACTERS = 4000


class SummaryWriterError(Exception):
    """会议纪要读取、解析或写入失败。"""


async def write_meeting_summary(
    transcript_path: Path,
    summary_path: Path,
    llm_client: OpenAiCompatibleClient,
) -> None:
    """分批处理完整转录，生成六章纪要并覆盖 Markdown 文件。"""
    transcript_text = _read_transcript(Path(transcript_path))
    if not transcript_text.strip():
        raise SummaryWriterError("转录文件没有可用于整理纪要的文本。")

    LOGGER.info("LLM 模拟开始：会议纪要。")
    try:
        summaries: list[MeetingSummary] = []
        for batch in _split_transcript(transcript_text):
            summaries.append(await _summarize_batch(llm_client, batch))
        merged_summary = _merge_summaries(summaries)
        _write_summary(Path(summary_path), merged_summary)
    finally:
        LOGGER.info("LLM 模拟结束：会议纪要。")


def _read_transcript(transcript_path: Path) -> str:
    """读取完整 UTF-8 转录。"""
    if not transcript_path.is_file():
        raise SummaryWriterError(f"找不到转录文件：{transcript_path}")
    try:
        return transcript_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SummaryWriterError(f"无法读取转录文件：{error}") from error


def _split_transcript(transcript_text: str) -> list[str]:
    """按字符数把长转录拆成多个批次。"""
    return [
        transcript_text[index : index + TRANSCRIPT_BATCH_CHARACTERS]
        for index in range(0, len(transcript_text), TRANSCRIPT_BATCH_CHARACTERS)
    ]


async def _summarize_batch(
    llm_client: OpenAiCompatibleClient,
    transcript_batch: str,
) -> MeetingSummary:
    """请求一批转录对应的六章纪要 JSON。"""
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "meeting_summary_json：仅返回 JSON，字段为 meeting_objectives、"
                "confirmed_information、key_questions、risks_and_uncertainties、"
                "follow_up_questions、action_items，每个字段都是字符串数组。"
            ),
        },
        {"role": "user", "content": transcript_batch},
    ]
    response_text = await llm_client.chat(messages)
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise LlmError("LLM 会议纪要结果不是有效 JSON。") from error
    if not isinstance(data, dict):
        raise LlmError("LLM 会议纪要结果必须是 JSON 对象。")
    return MeetingSummary(
        meeting_objectives=_string_list(data, "meeting_objectives"),
        confirmed_information=_string_list(data, "confirmed_information"),
        key_questions=_string_list(data, "key_questions"),
        risks_and_uncertainties=_string_list(data, "risks_and_uncertainties"),
        follow_up_questions=_string_list(data, "follow_up_questions"),
        action_items=_string_list(data, "action_items"),
    )


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    """读取 JSON 中的字符串数组。"""
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LlmError(f"LLM 返回字段 {key} 必须是字符串数组。")
    return [item.strip() for item in value if item.strip()]


def _merge_summaries(summaries: list[MeetingSummary]) -> MeetingSummary:
    """合并每批纪要，并按原始顺序去除重复项。"""
    return MeetingSummary(
        meeting_objectives=_unique_items(
            summary.meeting_objectives for summary in summaries
        ),
        confirmed_information=_unique_items(
            summary.confirmed_information for summary in summaries
        ),
        key_questions=_unique_items(summary.key_questions for summary in summaries),
        risks_and_uncertainties=_unique_items(
            summary.risks_and_uncertainties for summary in summaries
        ),
        follow_up_questions=_unique_items(
            summary.follow_up_questions for summary in summaries
        ),
        action_items=_unique_items(summary.action_items for summary in summaries),
    )


def _unique_items(groups: Any) -> list[str]:
    """展开多个列表，并在保留顺序的同时去重。"""
    items: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item not in seen:
                seen.add(item)
                items.append(item)
    return items


def _write_summary(summary_path: Path, summary: MeetingSummary) -> None:
    """覆盖写入六个固定 Markdown 章节。"""
    content = (
        "# 会议纪要（离线模拟）\n\n"
        f"## 会议目标\n{_markdown_items(summary.meeting_objectives)}\n\n"
        f"## 已确认信息\n{_markdown_items(summary.confirmed_information)}\n\n"
        f"## 关键问题\n{_markdown_items(summary.key_questions)}\n\n"
        "## 风险和不确定性\n"
        f"{_markdown_items(summary.risks_and_uncertainties)}\n\n"
        f"## 待追问问题\n{_markdown_items(summary.follow_up_questions)}\n\n"
        f"## 行动项\n{_markdown_items(summary.action_items)}\n"
    )
    try:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as error:
        raise SummaryWriterError(f"无法写入会议纪要文件：{error}") from error


def _markdown_items(items: list[str]) -> str:
    """把文本列表转换为 Markdown 列表。"""
    return "\n".join(f"- {item}" for item in items) or "- <模拟暂无内容>"
