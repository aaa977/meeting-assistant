"""音频内存缓冲转换与静音检测测试。"""

import io

import numpy as np
import pytest

from app.audio_recorder import AudioRecorderError, _samples_from_buffer


def _buffer(values: list[float]) -> io.BytesIO:
    return io.BytesIO(np.asarray(values, dtype=np.float32).tobytes())


def test_non_silent_buffer_returns_channel_matrix() -> None:
    samples = _samples_from_buffer(_buffer([0.1, -0.1, 0.2, -0.2]), 1)
    assert samples.shape == (4, 1)


def test_silent_buffer_is_rejected() -> None:
    with pytest.raises(AudioRecorderError, match="没有检测到有效"):
        _samples_from_buffer(_buffer([0.0, 0.0, 0.0, 0.0]), 1)


def test_incomplete_channel_data_is_rejected() -> None:
    with pytest.raises(AudioRecorderError, match="数据不完整"):
        _samples_from_buffer(_buffer([0.1, 0.2, 0.3]), 2)
