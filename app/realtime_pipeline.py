"""在线会议的音频、ASR 与智能辅助异步协同调度器。"""

from __future__ import annotations

import asyncio
import logging
import wave
from collections import deque
from datetime import datetime
from pathlib import Path

from app.assistant_runner import (
    append_assistant_hint,
    generate_assistant_hint,
    print_assistant_hint,
)
from app.asr_client import AsrError, QwenAsrClient
from app.audio_recorder import AudioRecorderError, audio_stream
from app.config import AppConfig
from app.llm_client import DummyLlmClient, LlmError, OpenAiCompatibleClient
from app.models import (
    AsrFinalResult,
    AsrResultChunk,
    LlmAssistantHint,
    MeetingProject,
)


LOGGER = logging.getLogger(__name__)
AsrResult = AsrResultChunk | AsrFinalResult


class RealtimePipelineError(Exception):
    """实时会议协同链路启动、运行或停止失败。"""


async def run_realtime_meeting(
    project: MeetingProject,
    config: AppConfig,
) -> None:
    """并发运行音频生产、ASR 收发和 LLM 辅助三个协程。"""
    if not config.asr_api_key or not config.asr_websocket_url:
        raise RealtimePipelineError("暂未配置在线参数，无法启动实时会议。")

    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
    transcript_queue: asyncio.Queue[AsrResult] = asyncio.Queue(maxsize=200)
    stop_event = asyncio.Event()
    captured_pcm = bytearray()
    _append_realtime_session_header(project.transcript_file)

    tasks = [
        asyncio.create_task(
            _audio_producer(audio_queue, captured_pcm, stop_event, config),
            name="audio_producer",
        ),
        asyncio.create_task(
            _asr_consumer(
                audio_queue,
                transcript_queue,
                stop_event,
                project,
                config,
            ),
            name="asr_consumer",
        ),
        asyncio.create_task(
            _assistant_loop(transcript_queue, stop_event, project, config),
            name="assistant_loop",
        ),
    ]

    LOGGER.info("realtime_pipeline start: project=%s", project.safe_directory_name)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        raise
    except (AudioRecorderError, AsrError, LlmError, OSError) as error:
        raise RealtimePipelineError(str(error)) from error
    finally:
        stop_event.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        if config.pipeline_wav_save and captured_pcm:
            try:
                wav_path = _save_captured_wav(project, captured_pcm, config)
                LOGGER.info("实时会议 WAV 已保存：%s", wav_path)
            except OSError:
                LOGGER.exception("实时会议 WAV 保存失败。")
        LOGGER.info("realtime_pipeline stop: project=%s", project.safe_directory_name)


async def _audio_producer(
    audio_queue: asyncio.Queue[bytes],
    captured_pcm: bytearray,
    stop_event: asyncio.Event,
    config: AppConfig,
) -> None:
    """从麦克风异步取得 PCM，同时缓存并推送到 ASR 队列。"""
    async for chunk in audio_stream(
        sample_rate=config.audio_sample_rate,
        channels=config.audio_channels,
        block_size=config.audio_block_size,
    ):
        if stop_event.is_set():
            return
        captured_pcm.extend(chunk)
        await audio_queue.put(chunk)


async def _asr_consumer(
    audio_queue: asyncio.Queue[bytes],
    transcript_queue: asyncio.Queue[AsrResult],
    stop_event: asyncio.Event,
    project: MeetingProject,
    config: AppConfig,
) -> None:
    """维持 ASR 连接，并在断线后按配置持续重连。"""
    while not stop_event.is_set():
        client = QwenAsrClient(
            websocket_url=config.asr_websocket_url,
            api_key=config.asr_api_key,
            sample_rate=config.audio_sample_rate,
        )
        sender_task: asyncio.Task[None] | None = None
        receiver_task: asyncio.Task[None] | None = None
        try:
            async with client:
                sender_task = asyncio.create_task(
                    _send_audio_chunks(client, audio_queue, stop_event),
                    name="asr_sender",
                )
                receiver_task = asyncio.create_task(
                    _receive_asr_results(
                        client,
                        transcript_queue,
                        stop_event,
                        project,
                    ),
                    name="asr_receiver",
                )
                done, pending = await asyncio.wait(
                    {sender_task, receiver_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    error = task.exception()
                    if error is not None:
                        raise error
                if not stop_event.is_set():
                    raise AsrError("ASR WebSocket 连接意外结束。")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if stop_event.is_set():
                return
            if _is_authentication_error(error):
                raise AsrError(
                    "ASR 认证失败，请检查 ASR_API_KEY 和 WebSocket 地址。"
                ) from error
            LOGGER.warning("ASR 连接中断：%s", error)
            LOGGER.info(
                "asr reconnect: waiting %.1f seconds",
                config.asr_reconnect_seconds,
            )
            await asyncio.sleep(config.asr_reconnect_seconds)
        finally:
            for task in (sender_task, receiver_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (sender_task, receiver_task) if task is not None),
                return_exceptions=True,
            )


async def _send_audio_chunks(
    client: QwenAsrClient,
    audio_queue: asyncio.Queue[bytes],
    stop_event: asyncio.Event,
) -> None:
    """持续消费 PCM 队列并发送给 ASR。"""
    try:
        while not stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            await client.send_audio(chunk)
    finally:
        try:
            await client.send_audio(b"", is_last=True)
        except Exception as error:
            LOGGER.warning("发送 ASR 结束标记失败：%s", error)


async def _receive_asr_results(
    client: QwenAsrClient,
    transcript_queue: asyncio.Queue[AsrResult],
    stop_event: asyncio.Event,
    project: MeetingProject,
) -> None:
    """接收 ASR 结果，实时落盘、显示并推送给助手队列。"""
    async for result in client.receive_results():
        if stop_event.is_set():
            return
        _append_realtime_result(project.transcript_file, result)
        prefix = "Final" if isinstance(result, AsrFinalResult) else "Partial"
        print(f"[{prefix}] {result.text}", flush=True)
        await transcript_queue.put(result)


async def _assistant_loop(
    transcript_queue: asyncio.Queue[AsrResult],
    stop_event: asyncio.Event,
    project: MeetingProject,
    config: AppConfig,
) -> None:
    """按固定时间汇总最新转录，并请求真实或 Dummy LLM。"""
    recent_texts: deque[str] = deque(maxlen=100)
    event_loop = asyncio.get_running_loop()
    next_request_time = event_loop.time() + config.ai_assistant_interval_seconds
    client = _select_llm_client(config)

    while not stop_event.is_set():
        timeout = max(0.0, next_request_time - event_loop.time())
        try:
            result = await asyncio.wait_for(transcript_queue.get(), timeout=timeout)
            if result.text.strip():
                recent_texts.append(result.text.strip())
        except TimeoutError:
            if recent_texts:
                transcript_text = "\n".join(recent_texts)
                hint, client = await _request_hint_with_fallback(
                    client,
                    transcript_text,
                )
                append_assistant_hint(project.ai_assistant_file, hint)
                print_assistant_hint(hint)
            next_request_time = event_loop.time() + config.ai_assistant_interval_seconds


def _select_llm_client(config: AppConfig) -> OpenAiCompatibleClient:
    """配置完整时使用真实 LLM，否则明确回退 Dummy。"""
    if config.llm_api_key and config.llm_model:
        return OpenAiCompatibleClient(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
    LOGGER.info("llm fallback dummy: missing API key or model")
    return DummyLlmClient()


async def _request_hint_with_fallback(
    client: OpenAiCompatibleClient,
    transcript_text: str,
) -> tuple[LlmAssistantHint, OpenAiCompatibleClient]:
    """真实 LLM 请求失败时回退 Dummy，保持会议链路继续运行。"""
    try:
        hint = await generate_assistant_hint(client, transcript_text)
        return hint, client
    except LlmError:
        if isinstance(client, DummyLlmClient):
            raise
        LOGGER.exception("真实 LLM 请求失败。")
        LOGGER.info("llm fallback dummy: request failed")
        dummy_client = DummyLlmClient()
        hint = await generate_assistant_hint(dummy_client, transcript_text)
        return hint, dummy_client


def _is_authentication_error(error: Exception) -> bool:
    """根据连接错误内容识别不可重试的认证失败。"""
    message = str(error).casefold()
    return any(
        marker in message
        for marker in ("401", "403", "unauthorized", "forbidden", "认证失败")
    )


def _append_realtime_session_header(transcript_path: Path) -> None:
    """在转录文件中追加一次在线会议会话标题。"""
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    _append_text(transcript_path, f"\n\n## 实时会议 {timestamp}\n")


def _append_realtime_result(transcript_path: Path, result: AsrResult) -> None:
    """把中间或最终 ASR 文本实时追加到 Markdown。"""
    timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
    result_type = "Final" if isinstance(result, AsrFinalResult) else "Partial"
    _append_text(
        transcript_path,
        f"\n[{timestamp}] [{result_type}] {result.text}\n",
    )


def _append_text(file_path: Path, text: str) -> None:
    """以 UTF-8 追加文本。"""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(text)
    except OSError as error:
        raise RealtimePipelineError(f"无法写入实时转录文件：{error}") from error


def _save_captured_wav(
    project: MeetingProject,
    captured_pcm: bytearray,
    config: AppConfig,
) -> Path:
    """把会议期间缓存的 PCM 保存为不覆盖旧文件的 WAV。"""
    project.recordings_directory.mkdir(parents=True, exist_ok=True)
    file_name = datetime.now().strftime(config.pipeline_wav_path_pattern)
    output_path = _available_wav_path(project.recordings_directory / file_name)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(config.audio_channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(config.audio_sample_rate)
        wav_file.writeframes(bytes(captured_pcm))
    return output_path


def _available_wav_path(output_path: Path) -> Path:
    """文件名冲突时增加序号，避免覆盖已有录音。"""
    candidate = output_path
    sequence = 2
    while candidate.exists():
        candidate = output_path.with_name(
            f"{output_path.stem}_{sequence}{output_path.suffix}"
        )
        sequence += 1
    return candidate
