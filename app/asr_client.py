"""Qwen-ASR WebSocket 客户端接口与离线模拟实现。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from types import TracebackType
from typing import Any, AsyncIterator, Self

import websockets

from app.models import AsrFinalResult, AsrResultChunk


LOGGER = logging.getLogger(__name__)


class AsrError(Exception):
    """ASR 连接、发送或结果解析失败。"""


class QwenAsrClient:
    """通过 WebSocket 发送 PCM 音频并异步接收 Qwen-ASR 结果。"""

    def __init__(
        self,
        websocket_url: str,
        api_key: str,
        sample_rate: int,
        ping_interval_seconds: float = 20.0,
    ) -> None:
        self.websocket_url = websocket_url.strip()
        self.api_key = api_key.strip()
        self.sample_rate = sample_rate
        self.ping_interval_seconds = ping_interval_seconds
        self._websocket: Any | None = None
        self._uses_realtime_events = "/realtime" in self.websocket_url.casefold()

    async def __aenter__(self) -> Self:
        """建立 WebSocket 连接；离线演示不会调用此实现。"""
        if not self.websocket_url:
            raise AsrError("ASR WebSocket 地址尚未配置。")
        if not self.api_key:
            raise AsrError("ASR_API_KEY 尚未配置。")
        if self.sample_rate <= 0:
            raise AsrError("ASR 采样率必须大于 0。")

        try:
            self._websocket = await websockets.connect(
                self.websocket_url,
                additional_headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "OpenAI-Beta": "realtime=v1",
                },
                # websockets 15+ 会自动读取系统代理；此项目的 ASR 端点直连 443。
                proxy=None,
                ping_interval=self.ping_interval_seconds,
                ping_timeout=self.ping_interval_seconds,
                close_timeout=10,
                max_size=None,
            )
        except Exception as error:
            LOGGER.exception("ASR WebSocket 连接失败。")
            raise AsrError(f"无法连接 ASR 服务：{error}") from error

        if self._uses_realtime_events:
            await self._send_session_update()
        LOGGER.info("ASR WebSocket 连接已建立。")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """关闭 WebSocket 连接。"""
        del exc_type, exc_value, traceback
        if self._websocket is not None:
            try:
                await self._websocket.close()
            except Exception:
                LOGGER.exception("关闭 ASR WebSocket 时发生错误。")
            finally:
                self._websocket = None
        LOGGER.info("ASR WebSocket 连接已关闭。")

    async def reconnect(self, delay_seconds: float) -> Self:
        """关闭旧连接，等待指定时间后重新连接。"""
        if delay_seconds <= 0:
            raise AsrError("ASR 重连等待时间必须大于 0。")
        LOGGER.info("asr reconnect: %.1f seconds", delay_seconds)
        await self.__aexit__(None, None, None)
        await asyncio.sleep(delay_seconds)
        return await self.__aenter__()

    async def send_audio(self, chunk: bytes, is_last: bool = False) -> None:
        """异步发送 16-bit little-endian PCM。"""
        websocket = self._require_connection()
        if not isinstance(chunk, bytes):
            raise AsrError("ASR 音频块必须是 bytes。")
        if not chunk and not is_last:
            raise AsrError("ASR 音频块不能为空。")

        try:
            if chunk:
                if self._uses_realtime_events:
                    append_message = {
                        "event_id": _event_id(),
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode("ascii"),
                    }
                    await websocket.send(json.dumps(append_message))
                else:
                    await websocket.send(chunk)
            if is_last:
                if self._uses_realtime_events:
                    finish_payload = {
                        "event_id": _event_id(),
                        "type": "input_audio_buffer.commit",
                    }
                else:
                    finish_payload = {"event": "finish", "is_last": True}
                finish_message = json.dumps(finish_payload, ensure_ascii=False)
                await websocket.send(finish_message)
        except Exception as error:
            LOGGER.exception("发送 ASR 音频块失败。")
            raise AsrError(f"发送音频数据失败：{error}") from error

    async def receive_results(
        self,
    ) -> AsyncIterator[AsrResultChunk | AsrFinalResult]:
        """异步迭代结果，解析 JSON 并转换为 dataclass。"""
        websocket = self._require_connection()
        try:
            async for raw_message in websocket:
                result = self._parse_result_message(raw_message)
                if result is None:
                    continue
                yield result
        except AsrError:
            raise
        except Exception as error:
            LOGGER.exception("接收 ASR 结果失败。")
            raise AsrError(f"接收 ASR 结果失败：{error}") from error

    def _require_connection(self) -> Any:
        """取得当前连接，未连接时给出明确错误。"""
        if self._websocket is None:
            raise AsrError("ASR WebSocket 尚未连接。")
        return self._websocket

    async def _send_session_update(self) -> None:
        """按 Qwen Realtime 事件协议配置 PCM 与服务端 VAD。"""
        websocket = self._require_connection()
        session_message = {
            "event_id": _event_id(),
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "input_audio_format": "pcm",
                "sample_rate": self.sample_rate,
                "input_audio_transcription": {},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.2,
                    "silence_duration_ms": 800,
                },
            },
        }
        try:
            await websocket.send(json.dumps(session_message, ensure_ascii=False))
        except Exception as error:
            LOGGER.exception("发送 ASR 会话配置失败。")
            raise AsrError(f"无法配置 ASR 实时会话：{error}") from error

    @staticmethod
    def _parse_result_message(
        raw_message: str | bytes,
    ) -> AsrResultChunk | AsrFinalResult | None:
        """解析包含 status、text 和时间字段的 ASR JSON。"""
        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")
            message = json.loads(raw_message)
        except (UnicodeError, json.JSONDecodeError, TypeError) as error:
            raise AsrError("ASR 返回了无法解析的 JSON 数据。") from error

        if not isinstance(message, dict):
            raise AsrError("ASR 返回结果必须是 JSON 对象。")

        event_type = str(message.get("type", ""))
        if event_type == "error":
            error_data = message.get("error", {})
            if not isinstance(error_data, dict):
                error_data = {}
            error_code = error_data.get("code") or message.get("code") or "unknown"
            error_message = (
                error_data.get("message")
                or message.get("message")
                or "未知错误"
            )
            raise AsrError(f"ASR 服务返回错误 {error_code}：{error_message}")

        realtime_result = _parse_realtime_transcription_event(message, event_type)
        if realtime_result is not None:
            return realtime_result
        if event_type:
            # session.created、session.updated、VAD 和缓冲区确认等控制事件不输出。
            return None

        result_data = _find_result_data(message)
        try:
            status = int(result_data.get("status", message.get("status", 0)))
        except (TypeError, ValueError) as error:
            raise AsrError("ASR 返回的 status 字段格式不正确。") from error

        if status != 0:
            error_message = result_data.get("message") or message.get("message")
            raise AsrError(f"ASR 服务返回错误状态 {status}：{error_message or '未知错误'}")

        text = result_data.get("text", "")
        if not isinstance(text, str):
            raise AsrError("ASR 返回的 text 字段必须是文本。")

        is_final = bool(result_data.get("is_final", False))
        start_time = _optional_float(result_data.get("start_time"))
        end_time = _optional_float(result_data.get("end_time"))
        if is_final:
            return AsrFinalResult(
                status=status,
                text=text,
                start_time=start_time,
                end_time=end_time,
            )
        return AsrResultChunk(
            status=status,
            text=text,
            is_final=False,
            start_time=start_time,
            end_time=end_time,
        )


class DummyAsrClient(QwenAsrClient):
    """与真实客户端接口一致、但不会建立网络连接的离线模拟器。"""

    def __init__(self, sample_rate: int) -> None:
        super().__init__(websocket_url="", api_key="", sample_rate=sample_rate)
        self._audio_bytes_received = 0
        self._is_finished = False

    async def __aenter__(self) -> Self:
        """进入离线模拟上下文。"""
        LOGGER.info("ASR 离线模拟客户端已就绪。")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """结束离线模拟上下文。"""
        del exc_type, exc_value, traceback

    async def send_audio(self, chunk: bytes, is_last: bool = False) -> None:
        """接收音频块但不发送网络数据。"""
        if not isinstance(chunk, bytes):
            raise AsrError("ASR 音频块必须是 bytes。")
        self._audio_bytes_received += len(chunk)
        if is_last:
            self._is_finished = True
        await asyncio.sleep(0)

    async def receive_results(
        self,
    ) -> AsyncIterator[AsrResultChunk | AsrFinalResult]:
        """依次产生三条中间结果和一条最终模拟结果。"""
        if not self._is_finished or self._audio_bytes_received == 0:
            raise AsrError("离线模拟没有收到可用音频数据。")

        partial_texts = (
            "<模拟文本：正在识别会议音频>",
            "<模拟文本：这是离线中间结果>",
            "<模拟文本：音频切片链路工作正常>",
        )
        for index, text in enumerate(partial_texts):
            await asyncio.sleep(0.15)
            yield AsrResultChunk(
                status=0,
                text=text,
                is_final=False,
                start_time=float(index),
                end_time=float(index + 1),
            )

        await asyncio.sleep(0.15)
        yield AsrFinalResult(
            status=0,
            text="<模拟文本：离线 ASR 转录链路验证完成>",
            start_time=0.0,
            end_time=float(len(partial_texts)),
        )


def _find_result_data(message: dict[str, Any]) -> dict[str, Any]:
    """兼容结果字段位于 result、output 或 payload 中的 JSON。"""
    for key in ("result", "output", "payload"):
        value = message.get(key)
        if isinstance(value, dict) and any(
            field in value
            for field in ("status", "text", "is_final", "start_time", "end_time")
        ):
            return value
    return message


def _optional_float(value: Any) -> float | None:
    """把可选时间字段转换为浮点数。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise AsrError("ASR 返回的时间字段格式不正确。") from error


def _parse_realtime_transcription_event(
    message: dict[str, Any],
    event_type: str,
) -> AsrResultChunk | AsrFinalResult | None:
    """解析 Qwen/OpenAI-style Realtime 转录增量和完成事件。"""
    if not event_type:
        return None

    if event_type.endswith(".delta") and "transcription" in event_type:
        text = message.get("delta") or message.get("text") or ""
        if not isinstance(text, str) or not text:
            return None
        return AsrResultChunk(
            status=0,
            text=text,
            is_final=False,
            start_time=_optional_float(message.get("start_time")),
            end_time=_optional_float(message.get("end_time")),
        )

    if event_type.endswith(".completed") and "transcription" in event_type:
        text = (
            message.get("transcript")
            or message.get("text")
            or message.get("delta")
            or ""
        )
        if not isinstance(text, str):
            raise AsrError("ASR 完成事件中的转录文本格式不正确。")
        return AsrFinalResult(
            status=0,
            text=text,
            start_time=_optional_float(message.get("start_time")),
            end_time=_optional_float(message.get("end_time")),
        )
    return None


def _event_id() -> str:
    """生成 Realtime 客户端事件编号。"""
    return f"event_{uuid.uuid4().hex}"
