"""读取项目热词和 Markdown 背景资料。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.models import MeetingProject, ProjectContext


LOGGER = logging.getLogger(__name__)
MARKDOWN_SUFFIXES = {".md", ".markdown"}
LIST_MARKER = re.compile(r"^[-+*]\s+")


def load_project_context(project: MeetingProject) -> ProjectContext:
    """加载指定项目的热词和全部背景 Markdown 文件。"""
    hotwords = _load_hotwords(project.hotwords_file)
    background_documents = _load_background_documents(
        project.background_directory
    )
    combined_text = _combine_background_documents(background_documents)

    LOGGER.info(
        "已加载项目背景：项目=%s，热词=%d，背景文件=%d，总字符=%d",
        project.safe_directory_name,
        len(hotwords),
        len(background_documents),
        len(combined_text),
    )
    return ProjectContext(
        project_name=project.project_name,
        hotwords=hotwords,
        background_documents=background_documents,
        combined_background_text=combined_text,
    )


def _load_hotwords(hotwords_file: Path) -> list[str]:
    """读取热词，去除列表符号并按原始顺序去重。"""
    if not hotwords_file.is_file():
        LOGGER.info("项目没有热词文件：%s", hotwords_file)
        return []

    try:
        content = hotwords_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        LOGGER.warning("无法读取热词文件 %s：%s", hotwords_file, error)
        return []

    hotwords: list[str] = []
    seen: set[str] = set()
    for original_line in content.splitlines():
        line = original_line.strip()
        if not line or line.startswith("#"):
            continue
        line = LIST_MARKER.sub("", line).strip()
        if line and line not in seen:
            seen.add(line)
            hotwords.append(line)
    return hotwords


def _load_background_documents(background_directory: Path) -> dict[str, str]:
    """递归读取非隐藏的 Markdown 文件，单个失败时继续。"""
    documents: dict[str, str] = {}
    if not background_directory.is_dir():
        LOGGER.info("项目没有背景资料目录：%s", background_directory)
        return documents

    candidates = sorted(
        background_directory.rglob("*"),
        key=lambda path: path.as_posix().casefold(),
    )
    for path in candidates:
        if not path.is_file() or path.suffix.lower() not in MARKDOWN_SUFFIXES:
            continue
        relative_path = path.relative_to(background_directory)
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        try:
            documents[relative_path.as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            LOGGER.warning("无法读取背景文件 %s，已跳过：%s", path, error)
    return documents


def _combine_background_documents(documents: dict[str, str]) -> str:
    """在每份背景正文前标记相对文件名并进行拼接。"""
    sections = [
        f"## 背景文件：{file_name}\n\n{content.strip()}"
        for file_name, content in documents.items()
    ]
    return "\n\n---\n\n".join(sections)
