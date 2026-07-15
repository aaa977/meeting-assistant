"""第一阶段使用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class MeetingProject:
    """一个会议项目及其常用文件路径。"""

    project_name: str
    safe_directory_name: str
    project_directory: Path
    created_at: datetime
    transcript_file: Path
    ai_notes_file: Path
    ai_assistant_file: Path
    hotwords_file: Path
    background_directory: Path
    recordings_directory: Path
    metadata_file: Path


@dataclass(slots=True)
class ProjectContext:
    """从会议项目中读取的热词和 Markdown 背景资料。"""

    project_name: str
    hotwords: list[str] = field(default_factory=list)
    background_documents: dict[str, str] = field(default_factory=dict)
    combined_background_text: str = ""


@dataclass(slots=True)
class AsrResultChunk:
    """ASR 返回的中间转录结果。"""

    status: int
    text: str
    is_final: bool
    start_time: float | None = None
    end_time: float | None = None


@dataclass(slots=True)
class AsrFinalResult:
    """ASR 返回的最终转录结果。"""

    status: int
    text: str
    start_time: float | None = None
    end_time: float | None = None
    is_final: bool = True


@dataclass(slots=True)
class LlmAssistantHint:
    """实时会议辅助的一次结构化提示。"""

    terms: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    follow_up: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MeetingSummary:
    """包含六个固定章节的结构化会议纪要。"""

    meeting_objectives: list[str] = field(default_factory=list)
    confirmed_information: list[str] = field(default_factory=list)
    key_questions: list[str] = field(default_factory=list)
    risks_and_uncertainties: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SpeakerSegment:
    """一段音频对应的说话人时间区间。"""

    start_time: float
    end_time: float
    speaker_id: str
