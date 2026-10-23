"""视觉模型客户端 — 支持多家 API

把截图发给视觉模型，让它理解界面并决定动作。

支持:
- OpenAI (GPT-4o / GPT-4V)
- Anthropic (Claude)
- 通义千问 (Qwen-VL)
- DeepSeek (如支持视觉)
- 本地模型 (Ollama / vLLM)
"""
from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.phone.vision")


@dataclass
class VisionConfig:
    """视觉模型配置"""
    provider: str = "openai"        # openai / anthropic / qwen / ollama / custom
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 1024
    temperature: float = 0.1


class VisionModelClient:
    """统一的视觉模型客户端

    用法:
        client = VisionModelClient(VisionConfig(
            provider="openai",
            model="gpt-4o",
            api_key=os.environ["OPENAI_API_KEY"],
        ))
        answer = await client.chat_with_image(prompt, image_bytes, "png")
    """

    def __init__(self, config: Optional[VisionConfig] = None):
        self.config = config or self._auto_config()

    def _auto_config(self) -> VisionConfig:
        """自动检测可用配置"""
        # OpenAI
        if os.environ.get("OPENAI_API_KEY"):
            return VisionConfig(
                provider="openai",
                model="gpt-4o",
                api_key=os.environ["OPENAI_API_KEY"],
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )

        # Anthropic
        if os.environ.get("ANTHROPIC_API_KEY"):
            return VisionConfig(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                api_key=os.environ["ANTHROPIC_API_KEY"],
                base_url="https://api.anthropic.com",
            )

        # 通义千问
        if os.environ.get("DASHSCOPE_API_KEY"):
            return VisionConfig(
                provider="qwen",
                model="qwen-vl-max",
                api_key=os.environ["DASHSCOPE_API_KEY"],
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )

        # 本地 Ollama
        return VisionConfig(
            provider="ollama",
            model="llava",
            base_url="http://localhost:11434/v1",
        )

    async def chat_with_image(
        self,
        prompt: str,
        image_data: bytes,
        image_format: str = "png",
    ) -> str:
        """发送带图片的对话

        Args:
            prompt: 提示词
            image_data: 图片二进制
            image_format: 图片格式

        Returns:
            模型回复文本
        """
        b64 = base64.b64encode(image_data).decode()

        if self.config.provider in ("openai", "qwen", "ollama", "custom"):
            return await self._call_openai_compatible(prompt, b64, image_format)
        elif self.config.provider == "anthropic":
            return await self._call_anthropic(prompt, b64, image_format)
        else:
            raise ValueError(f"不支持的 provider: {self.config.provider}")

    async def _call_openai_compatible(
        self,
        prompt: str,
        b64_image: str,
        image_format: str,
    ) -> str:
        """OpenAI 兼容接口（OpenAI / Qwen / Ollama / 自定义）"""
        try:
            import httpx
        except ImportError:
            logger.error("需要安装 httpx: pip install httpx")
            raise

        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{b64_image}"
                            },
                        },
                    ],
                }
            ],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.error(f"视觉模型调用失败: {resp.status_code} {resp.text[:200]}")
                raise RuntimeError(f"API 错误: {resp.status_code}")

            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _call_anthropic(
        self,
        prompt: str,
        b64_image: str,
        image_format: str,
    ) -> str:
        """Anthropic Claude 接口"""
        try:
            import httpx
        except ImportError:
            logger.error("需要安装 httpx: pip install httpx")
            raise

        url = f"{self.config.base_url}/v1/messages"

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": f"image/{image_format}",
                                "data": b64_image,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.error(f"Claude 调用失败: {resp.status_code} {resp.text[:200]}")
                raise RuntimeError(f"API 错误: {resp.status_code}")

            data = resp.json()
            return data["content"][0]["text"]


# ── 带 UI 元素提示的视觉分析 ──────────────────────────────────

class UIAwareVisionClient:
    """带 UI 元素提示的视觉分析器

    Android 可以 dump UI 元素树，把这个信息一起给模型，
    准确率会高得多 —— 模型不用猜坐标。
    """

    def __init__(self, client: VisionModelClient):
        self.client = client

    async def analyze_with_elements(
        self,
        frame_data: bytes,
        frame_format: str,
        instruction: str,
        elements: List[Dict],
        history: List[str],
    ) -> str:
        """带 UI 元素的视觉分析"""
        # 构建元素列表
        elements_text = "\n".join(
            f"  [{i}] text={e.get('text', '')!r} "
            f"desc={e.get('desc', '')!r} "
            f"class={e.get('class', '').split('.')[-1]} "
            f"center={e.get('center', [])} "
            f"clickable={e.get('clickable')}"
            for i, e in enumerate(elements[:40])
        )

        history_text = ""
        if history:
            history_text = "已执行:\n" + "\n".join(f"  {h}" for h in history[-5:])

        prompt = f"""你是手机操作助手。

任务: {instruction}

{history_text}

当前屏幕的可点击元素（已按顺序编号）:
{elements_text}

请决定下一个动作。优先用元素的 index（比猜坐标准确）。

输出 JSON:
{{"action": "tap_index", "index": 5, "reason": "点击设置按钮"}}
{{"action": "tap", "x": 540, "y": 1200, "reason": "..."}}
{{"action": "type", "text": "hello", "reason": "..."}}
{{"action": "swipe", "direction": "up", "reason": "..."}}
{{"action": "key", "key": "back", "reason": "..."}}
{{"action": "finish", "message": "任务完成", "reason": "..."}}

只输出 JSON。"""

        return await self.client.chat_with_image(
            prompt, frame_data, frame_format
        )

    async def analyze_vision_only(
        self,
        frame_data: bytes,
        frame_format: str,
        instruction: str,
        history: List[str],
    ) -> str:
        """纯视觉分析（iOS 用，没有 UI 元素）"""
        history_text = ""
        if history:
            history_text = "已执行:\n" + "\n".join(f"  {h}" for h in history[-5:])

        prompt = f"""你是手机操作助手。看着这张截图完成任务。

任务: {instruction}

{history_text}

坐标用归一化的 0-1（不是像素）。

输出 JSON:
{{"action": "tap", "x": 0.5, "y": 0.8, "reason": "点击设置"}}
{{"action": "type", "text": "hello", "reason": "输入"}}
{{"action": "swipe", "direction": "up", "reason": "滚动"}}
{{"action": "finish", "message": "完成", "reason": "..."}}

只输出 JSON。"""

        return await self.client.chat_with_image(
            prompt, frame_data, frame_format
        )