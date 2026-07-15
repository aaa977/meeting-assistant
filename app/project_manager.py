"""创建、列出和加载会议项目目录。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.models import MeetingProject


LOGGER = logging.getLogger(__name__)
INVALID_WINDOWS_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ProjectManager:
    """管理 projects 目录下的会议项目。"""

    def __init__(self, projects_root: Path, project_version: str = "0.1.0") -> None:
        self.projects_root = Path(projects_root)
        self.project_version = project_version
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def create_project(self, project_name: str) -> MeetingProject:
        """创建一个新会议项目，不覆盖任何已有目录。"""
        safe_name = self.make_safe_directory_name(project_name)
        project_directory = self._available_project_directory(safe_name)
        created_at = datetime.now().astimezone()

        try:
            project_directory.mkdir(parents=False, exist_ok=False)
            project = self._build_project(
                project_name=project_name.strip(),
                directory=project_directory,
                created_at=created_at,
            )
            self._create_project_directories(project)
            self._write_initial_files(project)
        except OSError as error:
            LOGGER.error("创建项目失败：%s", error)
            raise OSError(f"无法创建会议项目：{error}") from error

        LOGGER.info("已创建会议项目：%s", project.safe_directory_name)
        return project

    def list_projects(self) -> list[MeetingProject]:
        """列出所有结构有效的会议项目。"""
        if not self.projects_root.exists():
            return []

        projects: list[MeetingProject] = []
        for directory in sorted(
            self.projects_root.iterdir(),
            key=lambda path: path.name.casefold(),
        ):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            try:
                project = self.load_project(directory.name)
            except (FileNotFoundError, OSError, ValueError, yaml.YAMLError) as error:
                LOGGER.warning("忽略无效项目目录 %s：%s", directory, error)
                continue
            projects.append(project)
        return projects

    def load_project(self, directory_name: str) -> MeetingProject:
        """根据安全目录名称加载一个会议项目。"""
        if not directory_name or Path(directory_name).name != directory_name:
            raise ValueError("项目目录名称无效。")

        directory = self.projects_root / directory_name
        if not self.is_valid_project_directory(directory):
            raise FileNotFoundError(f"项目不存在或目录结构不完整：{directory_name}")

        metadata_file = directory / "project_info.yaml"
        try:
            with metadata_file.open("r", encoding="utf-8") as file:
                metadata = yaml.safe_load(file) or {}
        except OSError as error:
            raise OSError(f"无法读取项目说明文件：{metadata_file}") from error

        if not isinstance(metadata, dict):
            raise ValueError(f"项目说明文件格式不正确：{metadata_file}")

        project_name = self._metadata_text(metadata, "project_name")
        saved_directory_name = self._metadata_text(metadata, "directory_name")
        if saved_directory_name != directory.name:
            raise ValueError("项目说明中的目录名称与实际目录不一致。")

        created_at = self._parse_created_at(metadata.get("created_at"))
        return self._build_project(project_name, directory, created_at)

    def is_valid_project_directory(self, directory: Path) -> bool:
        """检查目录是否具备第一阶段所需的文件结构。"""
        directory = Path(directory)
        required_files = (
            directory / "project_info.yaml",
            directory / "hotwords.md",
            directory / "background" / "README.md",
            directory / "transcripts" / "raw_transcript.md",
            directory / "notes" / "meeting_notes.md",
            directory / "assistant" / "realtime_assistant.md",
        )
        required_directories = (
            directory / "background",
            directory / "transcripts",
            directory / "notes",
            directory / "assistant",
            directory / "recordings",
        )
        return (
            directory.is_dir()
            and all(path.is_file() for path in required_files)
            and all(path.is_dir() for path in required_directories)
        )

    @staticmethod
    def make_safe_directory_name(project_name: str) -> str:
        """保留中文并替换 Windows 文件名中的非法字符。"""
        cleaned_name = INVALID_WINDOWS_CHARACTERS.sub("_", project_name.strip())
        cleaned_name = re.sub(r"\s+", " ", cleaned_name).rstrip(". ")
        if not cleaned_name:
            raise ValueError("项目名称不能为空，也不能只包含文件名非法字符。")
        if cleaned_name.upper() in WINDOWS_RESERVED_NAMES:
            cleaned_name = f"{cleaned_name}_项目"
        return cleaned_name

    def _available_project_directory(self, safe_name: str) -> Path:
        """同名时增加时间戳和序号，确保不覆盖原项目。"""
        first_choice = self.projects_root / safe_name
        if not first_choice.exists():
            return first_choice

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = self.projects_root / f"{safe_name}_{timestamp}"
        sequence = 2
        while candidate.exists():
            candidate = self.projects_root / f"{safe_name}_{timestamp}_{sequence}"
            sequence += 1
        return candidate

    @staticmethod
    def _build_project(
        project_name: str,
        directory: Path,
        created_at: datetime,
    ) -> MeetingProject:
        """根据项目根目录构造统一的数据对象。"""
        return MeetingProject(
            project_name=project_name,
            safe_directory_name=directory.name,
            project_directory=directory,
            created_at=created_at,
            transcript_file=directory / "transcripts" / "raw_transcript.md",
            ai_notes_file=directory / "notes" / "meeting_notes.md",
            ai_assistant_file=directory / "assistant" / "realtime_assistant.md",
            hotwords_file=directory / "hotwords.md",
            background_directory=directory / "background",
            recordings_directory=directory / "recordings",
            metadata_file=directory / "project_info.yaml",
        )

    @staticmethod
    def _create_project_directories(project: MeetingProject) -> None:
        """创建标准子目录。"""
        for directory in (
            project.background_directory,
            project.transcript_file.parent,
            project.ai_notes_file.parent,
            project.ai_assistant_file.parent,
            project.recordings_directory,
        ):
            directory.mkdir(exist_ok=False)

    def _write_initial_files(self, project: MeetingProject) -> None:
        """写入 UTF-8 项目说明和 Markdown 模板。"""
        created_text = project.created_at.isoformat(timespec="seconds")
        metadata: dict[str, Any] = {
            "project_name": project.project_name,
            "directory_name": project.safe_directory_name,
            "created_at": created_text,
            "project_version": self.project_version,
        }
        with project.metadata_file.open("x", encoding="utf-8", newline="\n") as file:
            yaml.safe_dump(metadata, file, allow_unicode=True, sort_keys=False)

        initial_files = {
            project.hotwords_file: (
                "# 项目热词\n\n"
                "# 使用说明：请删除示例，并按每行一个热词或 Markdown 列表填写。\n"
                "# 示例：\n"
                "- WebSocket\n"
                "- Qwen-ASR\n"
            ),
            project.background_directory / "README.md": (
                "# 背景资料使用说明\n\n"
                "请把与本次会议有关的 Markdown 文件放入此目录。\n\n"
                "支持 `.md` 和 `.markdown` 文件，也可以建立子目录分类保存。\n"
            ),
            project.transcript_file: (
                f"# {project.project_name} - 原始转录\n\n"
                f"创建时间：{created_text}\n\n"
                "> 当前阶段尚未实现语音转录，本文件供后续阶段写入。\n"
            ),
            project.ai_notes_file: (
                f"# {project.project_name} - 会议纪要\n\n"
                "## 会议目标\n\n"
                "## 已确认信息\n\n"
                "## 关键问题\n\n"
                "## 风险和不确定性\n\n"
                "## 待追问问题\n\n"
                "## 行动项\n"
            ),
            project.ai_assistant_file: (
                f"# {project.project_name} - 实时辅助\n\n"
                "> 当前阶段尚未实现 LLM 实时辅助，本文件供后续阶段写入。\n"
            ),
            project.recordings_directory / ".gitkeep": "",
        }
        for path, content in initial_files.items():
            path.write_text(content, encoding="utf-8", newline="\n")

    @staticmethod
    def _metadata_text(metadata: dict[str, Any], key: str) -> str:
        """读取项目说明中的必填文本。"""
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"project_info.yaml 缺少有效的 {key}。")
        return value.strip()

    @staticmethod
    def _parse_created_at(value: Any) -> datetime:
        """把项目创建时间转换为 datetime。"""
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("project_info.yaml 缺少有效的 created_at。")
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("project_info.yaml 中的 created_at 格式不正确。") from error
