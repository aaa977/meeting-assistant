"""读取 YAML 配置和本地环境变量。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_FILE = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(slots=True)
class AppConfig:
    """应用运行所需的配置。API 字段为后续阶段预留。"""

    app_name: str
    app_version: str
    projects_root: Path
    logs_root: Path
    log_level: str
    audio_sample_rate: int
    audio_channels: int
    audio_block_size: int
    asr_api_key: str
    asr_websocket_url: str
    asr_block_size: int
    asr_reconnect_seconds: float
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    ai_assistant_interval_seconds: int
    meeting_summary_interval_seconds: int
    max_speakers: int
    speaker_mfcc_n_mfcc: int
    speaker_cluster_threshold: float
    pipeline_wav_save: bool
    pipeline_wav_path_pattern: str


def load_config(
    settings_file: Path = DEFAULT_SETTINGS_FILE,
    env_file: Path = DEFAULT_ENV_FILE,
) -> AppConfig:
    """加载并校验配置；没有 .env 时仍可运行第一阶段。"""
    settings_file = Path(settings_file)
    if not settings_file.is_file():
        raise FileNotFoundError(f"配置文件不存在：{settings_file}")

    try:
        with settings_file.open("r", encoding="utf-8") as file:
            raw_config = yaml.safe_load(file) or {}
    except yaml.YAMLError as error:
        raise ValueError(f"YAML 配置格式错误：{error}") from error
    except OSError as error:
        raise OSError(f"无法读取配置文件：{settings_file}") from error

    if not isinstance(raw_config, dict):
        raise ValueError("settings.yaml 的最外层必须是 YAML 键值配置。")

    # 项目 .env 是本项目的明确配置来源，空值也应覆盖旧的进程环境变量。
    load_dotenv(dotenv_path=env_file, override=True)

    app = _section(raw_config, "app")
    paths = _section(raw_config, "paths")
    logging_config = _section(raw_config, "logging")
    audio = _section(raw_config, "audio")
    asr = _section(raw_config, "asr")
    llm = _section(raw_config, "llm")
    speaker = _section(raw_config, "speaker")

    config = AppConfig(
        app_name=_text(app, "name", "面向会议场景的实时语音转录与智能辅助系统"),
        app_version=_text(app, "version", "0.1.0"),
        projects_root=_resolve_path(_text(paths, "projects_root", "projects")),
        logs_root=_resolve_path(_text(paths, "logs_root", "logs")),
        log_level=_text(logging_config, "level", "INFO").upper(),
        audio_sample_rate=_positive_int(audio, "sample_rate", 16000),
        audio_channels=_positive_int(audio, "channels", 1),
        audio_block_size=_positive_int(audio, "block_size", 3200),
        asr_api_key=os.getenv("ASR_API_KEY", "").strip(),
        asr_websocket_url=_environment_or_config(
            "ASR_WEBSOCKET_URL", asr, "websocket_url"
        ),
        asr_block_size=_positive_int(asr, "block_size", 3200),
        asr_reconnect_seconds=_positive_float(
            asr, "reconnect_seconds", 3.0
        ),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_base_url=_environment_or_config("LLM_BASE_URL", llm, "base_url"),
        llm_model=_environment_or_config("LLM_MODEL", llm, "model"),
        ai_assistant_interval_seconds=_positive_int(
            llm, "assistant_interval_seconds", 30
        ),
        meeting_summary_interval_seconds=_positive_int(
            llm, "summary_interval_seconds", 180
        ),
        max_speakers=_positive_int(speaker, "max_speakers", 3),
        speaker_mfcc_n_mfcc=_positive_int(speaker, "mfcc_n_mfcc", 13),
        speaker_cluster_threshold=_positive_float(
            speaker, "cluster_threshold", 0.6
        ),
        pipeline_wav_save=_boolean(
            _section(raw_config, "pipeline"), "wav_save", True
        ),
        pipeline_wav_path_pattern=_text(
            _section(raw_config, "pipeline"),
            "wav_path_pattern",
            "%Y%m%d_%H%M%S.wav",
        ),
    )
    _validate_config(config)
    _log_optional_key_status(config)
    return config


def _section(config: dict[str, Any], name: str) -> dict[str, Any]:
    """读取一个 YAML 配置段，并检查其类型。"""
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"配置项 {name} 必须包含一组子配置。")
    return value


def _text(section: dict[str, Any], key: str, default: str) -> str:
    """读取文本配置，空值使用默认值。"""
    value = section.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"配置项 {key} 必须是文本。")
    return value.strip() or default


def _positive_int(section: dict[str, Any], key: str, default: int) -> int:
    """读取大于零的整数配置。"""
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"配置项 {key} 必须是大于 0 的整数。")
    return value


def _positive_float(
    section: dict[str, Any],
    key: str,
    default: float,
) -> float:
    """读取大于零的浮点数配置。"""
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"配置项 {key} 必须是大于 0 的数字。")
    return float(value)


def _boolean(section: dict[str, Any], key: str, default: bool) -> bool:
    """读取布尔配置。"""
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"配置项 {key} 必须是 true 或 false。")
    return value


def _resolve_path(path_text: str) -> Path:
    """把相对路径转换为以项目根目录为基准的绝对路径。"""
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _environment_or_config(
    environment_name: str,
    section: dict[str, Any],
    key: str,
) -> str:
    """环境变量优先，没有时读取 YAML。"""
    environment_value = os.getenv(environment_name)
    if environment_value is not None:
        return environment_value.strip()
    value = section.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"配置项 {key} 必须是文本。")
    return value.strip()


def _validate_config(config: AppConfig) -> None:
    """检查第一阶段运行所需的基础配置。"""
    if not config.app_name:
        raise ValueError("应用名称不能为空。")
    if not config.app_version:
        raise ValueError("应用版本不能为空。")
    if config.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("日志级别必须是 DEBUG、INFO、WARNING、ERROR 或 CRITICAL。")
    if config.projects_root == config.logs_root:
        raise ValueError("projects_root 和 logs_root 不能指向同一个目录。")
    if config.max_speakers > 3:
        raise ValueError("第五阶段最多支持 3 个说话人。")
    if config.speaker_cluster_threshold > 2:
        raise ValueError("speaker.cluster_threshold 不能大于 2。")
    wav_pattern = config.pipeline_wav_path_pattern
    if Path(wav_pattern).name != wav_pattern or not wav_pattern.lower().endswith(".wav"):
        raise ValueError("pipeline.wav_path_pattern 必须是不含目录的 WAV 文件名格式。")


def _log_optional_key_status(config: AppConfig) -> None:
    """只提示缺少的未来 API 密钥，不输出任何密钥内容。"""
    if not config.asr_api_key:
        LOGGER.info("未配置 ASR_API_KEY；离线模拟不连接 ASR，可继续运行。")
    if not config.llm_api_key:
        LOGGER.info("未配置 LLM_API_KEY；离线模拟不连接 LLM，可继续运行。")
