"""本地麦克风录音与 WAV 文件保存。"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from app.models import MeetingProject


LOGGER = logging.getLogger(__name__)
MINIMUM_RMS_LEVEL = 0.0001


class AudioRecorderError(Exception):
    """录音设备、音频采集或 WAV 保存失败。"""


async def audio_stream(
    sample_rate: int,
    channels: int,
    block_size: int,
) -> AsyncIterator[bytes]:
    """异步产生 16-bit little-endian PCM，不在本函数中写 WAV。"""
    _validate_audio_settings(None, sample_rate, channels, block_size)
    loop = asyncio.get_running_loop()
    pcm_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)

    def enqueue_chunk(chunk: bytes) -> None:
        """在事件循环线程中放入 PCM；积压时丢弃最旧音频块。"""
        if pcm_queue.full():
            try:
                pcm_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            LOGGER.warning("实时音频队列已满，已丢弃一个旧音频块。")
        pcm_queue.put_nowait(chunk)

    def stream_callback(
        input_data: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """从 PortAudio 回调线程安全地投递 PCM。"""
        del frames, time_info
        if status:
            LOGGER.warning("实时录音设备状态提示：%s", status)
        chunk = input_data.astype(np.int16, copy=False).tobytes()
        loop.call_soon_threadsafe(enqueue_chunk, chunk)

    try:
        _ensure_input_device_available(channels)
        sd.check_input_settings(
            device=None,
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
        )
        with sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            blocksize=block_size,
            dtype="int16",
            callback=stream_callback,
        ):
            LOGGER.info("实时 PCM 音频流已启动。")
            while True:
                yield await pcm_queue.get()
    except sd.PortAudioError as error:
        LOGGER.exception("实时麦克风采集失败。")
        raise AudioRecorderError(
            "找不到可用麦克风，或麦克风正在被其他程序占用。"
        ) from error
    except asyncio.CancelledError:
        raise
    except AudioRecorderError:
        raise
    except Exception as error:
        LOGGER.exception("实时 PCM 音频流发生错误。")
        raise AudioRecorderError(f"实时音频采集失败：{error}") from error
    finally:
        LOGGER.info("实时 PCM 音频流已关闭。")


def record_and_save(
    project: MeetingProject,
    duration_seconds: int | None = None,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    block_size: int = 3200,
) -> Path:
    """
    录音并保存 WAV，返回文件路径。

    duration_seconds=None 表示录音开始后，等待用户按 Enter 停止。
    """
    _validate_audio_settings(duration_seconds, sample_rate, channels, block_size)
    project.recordings_directory.mkdir(parents=True, exist_ok=True)
    output_path = _make_available_output_path(project.recordings_directory)
    audio_buffer = io.BytesIO()

    def audio_callback(
        input_data: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """把每个音频块复制到内存缓冲区。"""
        del frames, time_info
        if status:
            LOGGER.warning("录音设备状态提示：%s", status)
        audio_buffer.write(input_data.astype(np.float32, copy=False).tobytes())

    LOGGER.info(
        "开始录音：项目=%s，采样率=%d，声道=%d，块大小=%d",
        project.safe_directory_name,
        sample_rate,
        channels,
        block_size,
    )

    try:
        # Windows 有时会保留不可用的默认设备条目，因此分两步检查。
        _ensure_input_device_available(channels)
        sd.check_input_settings(
            device=None,
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
        )
        with sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            blocksize=block_size,
            dtype="float32",
            callback=audio_callback,
        ) as stream:
            if duration_seconds is None:
                input()
            else:
                sd.sleep(duration_seconds * 1000)
            if not stream.active:
                raise AudioRecorderError(
                    "录音过程中麦克风连接已中断，请检查设备后重试。"
                )

        samples = _samples_from_buffer(audio_buffer, channels)
        sf.write(
            output_path,
            samples,
            sample_rate,
            format="WAV",
            subtype="PCM_16",
        )
    except (sd.PortAudioError, ValueError, RuntimeError) as error:
        LOGGER.exception("输入设备不可用或无法使用当前音频配置。")
        raise AudioRecorderError(
            "找不到可用麦克风，或麦克风正在被其他程序占用。"
        ) from error
    except (OSError, sf.LibsndfileError) as error:
        LOGGER.exception("WAV 文件保存失败：%s", output_path)
        raise AudioRecorderError(f"无法保存 WAV 文件：{error}") from error
    except (KeyboardInterrupt, EOFError):
        LOGGER.info("用户取消了本次录音。")
        raise
    except AudioRecorderError:
        LOGGER.exception("录音未完成。")
        raise
    except Exception as error:
        LOGGER.exception("录音过程中发生未预期错误。")
        raise AudioRecorderError(f"录音失败：{error}") from error
    finally:
        audio_buffer.close()

    LOGGER.info("保存 WAV 完成：%s", output_path)
    return output_path


def get_wav_duration(file_path: Path) -> float:
    """读取 WAV 文件时长，供命令行显示保存结果。"""
    try:
        return float(sf.info(file_path).duration)
    except (OSError, sf.LibsndfileError) as error:
        LOGGER.warning("无法读取 WAV 时长 %s：%s", file_path, error)
        raise AudioRecorderError(f"无法读取录音文件信息：{error}") from error


def _validate_audio_settings(
    duration_seconds: int | None,
    sample_rate: int,
    channels: int,
    block_size: int,
) -> None:
    """检查录音参数，避免把明显错误的配置交给音频设备。"""
    if duration_seconds is not None and duration_seconds <= 0:
        raise AudioRecorderError("固定录音时长必须大于 0 秒。")
    if sample_rate <= 0:
        raise AudioRecorderError("音频采样率必须大于 0。")
    if channels <= 0:
        raise AudioRecorderError("音频声道数必须大于 0。")
    if block_size <= 0:
        raise AudioRecorderError("音频块大小必须大于 0。")


def _ensure_input_device_available(required_channels: int) -> None:
    """确认系统存在满足声道数要求的默认输入设备。"""
    try:
        device_info = sd.query_devices(kind="input")
        max_input_channels = int(device_info.get("max_input_channels", 0))
    except (sd.PortAudioError, ValueError, TypeError, KeyError) as error:
        raise AudioRecorderError(
            "找不到可用麦克风，或麦克风正在被其他程序占用。"
        ) from error

    if max_input_channels < required_channels:
        raise AudioRecorderError(
            "当前麦克风没有可用的输入声道，请检查设备连接和系统权限。"
        )


def _samples_from_buffer(audio_buffer: io.BytesIO, channels: int) -> np.ndarray:
    """把内存中的 float32 字节转换为 soundfile 可写入的数组。"""
    samples = np.frombuffer(audio_buffer.getvalue(), dtype=np.float32)
    if samples.size == 0:
        raise AudioRecorderError("没有采集到音频，请确认麦克风可用后重试。")
    if samples.size % channels != 0:
        raise AudioRecorderError("采集到的音频数据不完整，请重新录音。")
    if not np.all(np.isfinite(samples)):
        raise AudioRecorderError("麦克风返回了无效音频数据，请重新连接设备。")

    rms_level = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms_level < MINIMUM_RMS_LEVEL:
        LOGGER.warning("麦克风输入电平过低：RMS=%.8f", rms_level)
        raise AudioRecorderError(
            "没有检测到有效的麦克风声音，请检查设备连接、静音状态、"
            "Windows 麦克风权限和默认输入设备。"
        )
    return samples.reshape(-1, channels)


def _make_available_output_path(recordings_directory: Path) -> Path:
    """生成时间戳文件名；极短时间内重名时增加序号。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = recordings_directory / f"{timestamp}.wav"
    sequence = 2
    while output_path.exists():
        output_path = recordings_directory / f"{timestamp}_{sequence}.wav"
        sequence += 1
    return output_path
