"""LAAP — Vision tool for image analysis.

真正的视觉分析：调用视觉模型理解图片内容，而不只是返回元数据。

支持的视觉后端（自动探测）：
  - SenseNova (sensenova-6.8-flash-lite) — SENSENOVA_API_KEY
  - OpenAI (gpt-4o)                      — OPENAI_API_KEY
  - 通义千问 (qwen-vl-max)                — DASHSCOPE_API_KEY
  - OpenRouter (claude-sonnet-4.5)       — OPENROUTER_API_KEY
  - Ollama (llava, 本地)                  — 无需 key
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
from typing import Any, Dict, Optional

from laap.tools.base import ToolResult

logger = logging.getLogger("laap.tools.vision")


def _run_async(coro, timeout: float = 90.0):
    """在同步环境里跑异步协程"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result(timeout=timeout)
    except RuntimeError:
        pass
    return asyncio.run(coro)


def screenshot_analyze(
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
    question: str = "",
) -> ToolResult:
    """分析图片 — 真正让视觉模型看懂内容

    Args:
        image_path: 本地图片路径
        image_base64: base64 图片数据（与 image_path 二选一）
        question: 想问图片的问题（留空则做通用描述）

    Returns:
        ToolResult，output 是视觉模型的描述（JSON），metadata 含图片信息
    """
    if not image_path and not image_base64:
        return ToolResult(
            success=False,
            output="",
            error="必须提供 image_path 或 image_base64",
        )

    # ── 1. 拿到图片字节 ─────────────────────────
    image_bytes: Optional[bytes] = None
    source = "unknown"

    if image_base64:
        try:
            image_bytes = base64.b64decode(image_base64)
            source = "base64"
        except Exception as e:
            return ToolResult(False, "", f"base64 解码失败: {e}")

    elif image_path:
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            source = image_path
        except Exception as e:
            return ToolResult(False, "", f"读取图片失败: {e}")

    if not image_bytes:
        return ToolResult(False, "", "无法加载图片")

    # ── 2. 图片元数据 ─────────────────────────
    metadata: Dict[str, Any] = {
        "source": source,
        "bytes": len(image_bytes),
    }

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        metadata["format"] = img.format
        metadata["mode"] = img.mode
        metadata["size"] = img.size
    except Exception:
        pass

    image_format = (metadata.get("format") or "PNG").lower()

    # ── 3. OCR（可选，作为补充）─────────────────────────
    ocr_text = ""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        ocr_text = pytesseract.image_to_string(img).strip()
        metadata["ocr_available"] = True
    except Exception:
        metadata["ocr_available"] = False

    # ── 4. 真正调用视觉模型 ─────────────────────────
    description = ""
    vision_available = False
    vision_model = ""

    try:
        from laap.tools.browser_perception import detect_vision_backend, VisionClient

        cfg = detect_vision_backend()
        vision_available = cfg.available
        vision_model = cfg.model

        if cfg.available:
            b64 = base64.b64encode(image_bytes).decode()

            if question:
                prompt = question
            else:
                prompt = (
                    "请描述这张图片的内容。"
                    "如果图中有文字，请原样列出关键文字。"
                    "如果有界面元素（按钮/输入框/菜单），说明它们的位置和用途。"
                    "控制在 200 字内。"
                )

            client = VisionClient(cfg)
            description = _run_async(client.describe(b64, prompt, image_format))

    except Exception as e:
        logger.error(f"视觉模型调用失败: {e}")
        metadata["vision_error"] = str(e)

    # ── 5. 组装结果 ─────────────────────────
    metadata.update({
        "vision_available": vision_available,
        "vision_model": vision_model,
        "has_description": bool(description),
    })

    output = json.dumps(
        {
            "description": description,
            "ocr_text": ocr_text,
            "format": metadata.get("format"),
            "size": metadata.get("size"),
            "vision_model": vision_model,
            "note": (
                "" if description
                else (
                    "未检测到视觉模型或调用失败。"
                    "设置 SENSENOVA_API_KEY / OPENAI_API_KEY / DASHSCOPE_API_KEY 启用。"
                    if not vision_available
                    else "视觉模型调用失败，详见 metadata.vision_error"
                )
            ),
        },
        ensure_ascii=False,
    )

    return ToolResult(
        success=bool(description or ocr_text),
        output=output,
        error="" if description or ocr_text else "视觉理解和 OCR 都不可用",
        metadata=metadata,
    )


def ask_image(
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
    question: str = "",
) -> ToolResult:
    """针对图片提一个具体问题（screenshot_analyze 的简化版）"""
    return screenshot_analyze(
        image_path=image_path,
        image_base64=image_base64,
        question=question,
    )


def vision_status() -> ToolResult:
    """当前视觉能力状态"""
    try:
        from laap.tools.browser_perception import get_vision_status
        return ToolResult(
            success=True,
            output=json.dumps(get_vision_status(), ensure_ascii=False),
        )
    except Exception as e:
        return ToolResult(False, "", str(e))
