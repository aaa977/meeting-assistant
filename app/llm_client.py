"""OpenAI-compatible LLM 接口与完全离线的模拟客户端。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any


LOGGER = logging.getLogger(__name__)


class LlmError(Exception):
    """LLM 配置、调用或返回内容不正确。"""


class OpenAiCompatibleClient:
    """兼容 OpenAI Chat Completions API 的异步客户端。"""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.strip()
        self.model = model.strip()

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        """调用 OpenAI-compatible Chat API 并返回文本；离线菜单不会调用。"""
        if not self.api_key:
            raise LlmError("LLM_API_KEY 尚未配置。")
        if not self.model:
            raise LlmError("LLM_MODEL 尚未配置。")
        if not messages:
            raise LlmError("LLM 消息列表不能为空。")

        try:
            # 延迟导入，确保离线 Dummy 演示不依赖或初始化真实客户端。
            from openai import AsyncOpenAI
        except ImportError as error:
            raise LlmError("缺少 openai 依赖，无法使用真实 LLM 客户端。") from error

        try:
            client_options: dict[str, str] = {"api_key": self.api_key}
            if self.base_url:
                client_options["base_url"] = self.base_url
            client = AsyncOpenAI(**client_options)
            LOGGER.info("llm request: model=%s", self.model)
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            content = response.choices[0].message.content
        except Exception as error:
            LOGGER.exception("LLM Chat API 调用失败。")
            raise LlmError(f"LLM 请求失败：{error}") from error

        if not isinstance(content, str) or not content.strip():
            raise LlmError("LLM 没有返回有效文本。")
        return content.strip()


class DummyLlmClient(OpenAiCompatibleClient):
    """返回固定 JSON 模板且绝不访问网络的离线 LLM 客户端。"""

    def __init__(self) -> None:
        super().__init__(api_key="", base_url="", model="dummy-offline")

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        """根据任务标记返回辅助提示或会议纪要模拟 JSON。"""
        if not messages:
            raise LlmError("离线模拟消息列表不能为空。")

        prompt_text = "\n".join(
            str(message.get("content", "")) for message in messages
        )
        LOGGER.info("llm request: dummy-offline")
        await asyncio.sleep(0)
        if "meeting_summary_json" in prompt_text:
            result = {
                "meeting_objectives": ["<模拟会议目标：明确本次会议的讨论范围>"],
                "confirmed_information": ["<模拟已确认信息：现有转录已完成整理>"],
                "key_questions": ["<模拟关键问题：仍需确认核心需求优先级>"],
                "risks_and_uncertainties": ["<模拟风险：部分信息可能缺少负责人>"],
                "follow_up_questions": ["<模拟待追问：下一步由谁负责推进？>"],
                "action_items": ["<模拟行动项：会后补充时间计划与负责人>"],
            }
        else:
            result = {
                "terms": ["<模拟术语：实时转录，指持续把语音转换为文字>"],
                "key_points": ["<模拟关键点：会议正在讨论项目实施方案>"],
                "risks": ["<模拟风险：需求边界和交付时间仍需确认>"],
                "follow_up": ["<模拟待追问：各项任务的负责人是谁？>"],
            }
        return json.dumps(result, ensure_ascii=False)
