"""把 PCM WAV 文件异步切分为固定样本数的音频块。"""

from __future__ import annotations

import asyncio
import wave
from collections.abc import AsyncIterator
from pathlib import Path


EXPECTED_SAMPLE_RATE = 16000
EXPECTED_SAMPLE_WIDTH = 2
EXPECTED_CHANNELS = 1


class AudioStreamError(Exception):
    """WAV 文件不存在、格式不正确或读取失败。"""


async def generate_wav_chunks(
    file_path: Path,
    block_size: int,
) -> AsyncIterator[bytes]:
    """按 block_size 个样本异步读取 16 kHz、16-bit、单声道 WAV。"""
    file_path = Path(file_path)
    if block_size <= 0:
        raise AudioStreamError("ASR 音频块大小必须大于 0。")
    if not file_path.is_file():
        raise AudioStreamError(f"找不到 WAV 文件：{file_path}")

    try:
        with wave.open(str(file_path), "rb") as wav_file:
            _validate_wav_format(wav_file, file_path)
            while True:
                chunk = wav_file.readframes(block_size)
                if not chunk:
                    break
                yield chunk
                await asyncio.sleep(0)
    except (OSError, EOFError, wave.Error) as error:
        raise AudioStreamError(f"无法读取 WAV 文件：{error}") from error


def _validate_wav_format(wav_file: wave.Wave_read, file_path: Path) -> None:
    """检查 ASR 离线模拟要求的 WAV 参数。"""
    if wav_file.getframerate() != EXPECTED_SAMPLE_RATE:
        raise AudioStreamError(
            f"WAV 采样率必须是 {EXPECTED_SAMPLE_RATE} Hz：{file_path.name}"
        )
    if wav_file.getsampwidth() != EXPECTED_SAMPLE_WIDTH:
        raise AudioStreamError(f"WAV 必须是 16-bit PCM：{file_path.name}")
    if wav_file.getnchannels() != EXPECTED_CHANNELS:
        raise AudioStreamError(f"WAV 必须是单声道：{file_path.name}")
    if wav_file.getcomptype() != "NONE":
        raise AudioStreamError(f"WAV 必须是未压缩 PCM：{file_path.name}")
