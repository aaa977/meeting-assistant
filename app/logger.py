"""统一配置终端日志和文件日志。"""

from __future__ import annotations

import logging
from pathlib import Path


LOG_FILE_NAME = "meeting_assistant.log"
_HANDLER_MARKER = "_meeting_assistant_handler"


def setup_logging(logs_root: Path, log_level: str) -> None:
    """设置根日志器，同时把日志输出到终端和 UTF-8 文件。"""
    logs_root = Path(logs_root)
    logs_root.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 只移除本项目上一次添加的 Handler，避免重复输出。
    for handler in list(root_logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root_logger.removeHandler(handler)
            handler.close()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    setattr(console_handler, _HANDLER_MARKER, True)

    file_handler = logging.FileHandler(
        logs_root / LOG_FILE_NAME,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_MARKER, True)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
