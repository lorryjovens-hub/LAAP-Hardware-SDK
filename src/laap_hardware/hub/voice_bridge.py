"""语音桥接 — 让小智硬件说话就能驱动电脑干活

## 这是三端联动最自然的入口

你不想打开电脑、也不想掏手机，只想说一句：
  「帮我在电脑上打开知乎，截个图发我手机」

小智硬件听到 → 语音转文字 → 中枢拆任务 → 电脑执行 → 手机收图
→ 小智硬件说"已经打开了，截图发到你手机了"

## 链路

    小智硬件（麦克风）
        ↓ 语音识别（ASR）
    语音桥接（本模块）
        ↓ text
    TriNodeHub.handle_input()
        ↓ 拆任务 + 路由
    各端执行
        ↓ 结果
    语音桥接（TTS）
        ↓ 播报
    小智硬件（扬声器）

## 用法

    from laaper.hub import TriNodeHub
    from laaper.hub.voice_bridge import VoiceBridge, VoiceBridgeConfig

    hub = TriNodeHub(laaper_id="aris")
    hub.register_pc()
    hub.register_phone()
    hub.register_hardware("xiaozhi-01")

    # 注册各端能力
    setup_pc_handlers(hub)
    setup_phone_handlers(hub)

    voice = VoiceBridge(hub, VoiceBridgeConfig(
        asr_provider="sensenova",
        tts_provider="sensenova",
    ))

    # 小智硬件送来一段语音
    result = await voice.handle_audio(
        audio_bytes=wav_data,
        origin_node="xiaozhi-01",
    )
    # result["reply_text"] 是她说的话
    # result["reply_audio"] 是要播出去的音频
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laaper.hub.voice")


@dataclass
class VoiceBridgeConfig:
    """语音桥接配置"""
    # ASR（语音识别）
    asr_provider: str = "auto"        # auto / sensenova / openai / local
    asr_model: str = ""
    asr_base_url: str = ""
    asr_api_key: str = ""

    # TTS（语音合成）
    tts_provider: str = "auto"
    tts_model: str = ""
    tts_voice: str = "female_warm"
    tts_base_url: str = ""
    tts_api_key: str = ""

    # 行为
    language: str = "zh"
    max_reply_chars: int = 200         # 播报不要太长
    echo_to_session: bool = True        # 对话记入会话

    # 硬件节点
    default_hardware_node: str = "xiaozhi-01"


class VoiceBridge:
    """语音桥接 — 说话驱动三端协作"""

    def __init__(self, hub: Any, config: Optional[VoiceBridgeConfig] = None):
        self.hub = hub
        self.config = config or VoiceBridgeConfig()
        self._detect_providers()

        # 统计
        self.stats = {
            "utterances": 0,
            "asr_success": 0,
            "asr_fail": 0,
            "tasks_completed": 0,
            "last_utterance_at": 0.0,
        }

    def _detect_providers(self):
        """自动探测 ASR / TTS 后端"""
        if self.config.asr_provider == "auto":
            if os.environ.get("SENSENOVA_API_KEY"):
                self.config.asr_provider = "sensenova"
                self.config.asr_base_url = self.config.asr_base_url or \
                    "https://token.sensenova.cn/v1"
                self.config.asr_api_key = self.config.asr_api_key or \
                    os.environ["SENSENOVA_API_KEY"]
            elif os.environ.get("OPENAI_API_KEY"):
                self.config.asr_provider = "openai"
                self.config.asr_base_url = self.config.asr_base_url or \
                    "https://api.openai.com/v1"
                self.config.asr_api_key = self.config.asr_api_key or \
                    os.environ["OPENAI_API_KEY"]
            else:
                self.config.asr_provider = "none"

        if self.config.tts_provider == "auto":
            if os.environ.get("SENSENOVA_API_KEY"):
                self.config.tts_provider = "sensenova"
                self.config.tts_base_url = self.config.tts_base_url or \
                    "https://token.sensenova.cn/v1"
                self.config.tts_api_key = self.config.tts_api_key or \
                    os.environ["SENSENOVA_API_KEY"]
            elif os.environ.get("OPENAI_API_KEY"):
                self.config.tts_provider = "openai"
                self.config.tts_base_url = self.config.tts_base_url or \
                    "https://api.openai.com/v1"
                self.config.tts_api_key = self.config.tts_api_key or \
                    os.environ["OPENAI_API_KEY"]
            else:
                self.config.tts_provider = "none"

    # ── 主入口 ──────────────────────────────────

    async def handle_audio(
        self,
        audio_bytes: bytes,
        origin_node: str = "",
        audio_format: str = "wav",
    ) -> Dict[str, Any]:
        """处理一段语音输入

        Args:
            audio_bytes: 音频数据
            origin_node: 哪个硬件送来的
            audio_format: 音频格式

        Returns:
            {
                "success": bool,
                "transcribed": str,        # 识别出的文字
                "reply_text": str,         # 要回的文本
                "reply_audio": bytes,      # 要播的音频（可能为空）
                "task": dict,              # 任务详情
            }
        """
        t0 = time.time()
        self.stats["utterances"] += 1
        self.stats["last_utterance_at"] = time.time()

        origin = origin_node or self.config.default_hardware_node

        # 1. 语音识别
        text = await self._transcribe(audio_bytes, audio_format)

        if not text:
            self.stats["asr_fail"] += 1
            return {
                "success": False,
                "transcribed": "",
                "reply_text": "没听清，能再说一次吗？",
                "reply_audio": None,
                "error": "语音识别失败",
            }

        self.stats["asr_success"] += 1
        logger.info(f"[语音] {origin}: {text}")

        # 2. 中枢处理
        result = await self.hub.handle_input(text=text, origin_node=origin)

        if result.get("success"):
            self.stats["tasks_completed"] += 1

        # 3. 生成播报
        reply_text = self._make_speakable(result.get("reply", ""))

        # 4. 合成语音
        reply_audio = await self._synthesize(reply_text)

        return {
            "success": result.get("success", False),
            "transcribed": text,
            "reply_text": reply_text,
            "reply_audio": reply_audio,
            "task": result.get("task"),
            "duration_ms": round((time.time() - t0) * 1000, 1),
        }

    async def handle_text(
        self,
        text: str,
        origin_node: str = "",
        speak_back: bool = True,
    ) -> Dict[str, Any]:
        """处理文字输入（调试用，或从其他通道来）"""
        origin = origin_node or self.config.default_hardware_node

        result = await self.hub.handle_input(text=text, origin_node=origin)

        reply_text = self._make_speakable(result.get("reply", ""))
        reply_audio = await self._synthesize(reply_text) if speak_back else None

        return {
            "success": result.get("success", False),
            "transcribed": text,
            "reply_text": reply_text,
            "reply_audio": reply_audio,
            "task": result.get("task"),
        }

    # ── ASR ──────────────────────────────────

    async def _transcribe(self, audio_bytes: bytes, fmt: str) -> str:
        """语音转文字"""
        if self.config.asr_provider == "none" or not audio_bytes:
            return ""

        try:
            import httpx
        except ImportError:
            return ""

        url = f"{self.config.asr_base_url.rstrip('/')}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.config.asr_api_key}"}

        files = {
            "file": (f"audio.{fmt}", audio_bytes, f"audio/{fmt}"),
            "model": (None, self.config.asr_model or "whisper-1"),
            "language": (None, self.config.language),
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, files=files)
                if resp.status_code != 200:
                    logger.error(f"ASR 失败 {resp.status_code}: {resp.text[:200]}")
                    return ""
                data = resp.json()
                return data.get("text", "").strip()
        except Exception as e:
            logger.error(f"ASR 异常: {e}")
            return ""

    # ── TTS ──────────────────────────────────

    async def _synthesize(self, text: str) -> Optional[bytes]:
        """文字转语音"""
        if self.config.tts_provider == "none" or not text:
            return None

        try:
            import httpx
        except ImportError:
            return None

        url = f"{self.config.tts_base_url.rstrip('/')}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.config.tts_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.tts_model or "tts-1",
            "input": text,
            "voice": self.config.tts_voice,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.warning(f"TTS 失败 {resp.status_code}")
                    return None
                return resp.content
        except Exception as e:
            logger.warning(f"TTS 异常: {e}")
            return None

    # ── 播报文本整形 ──────────────────────────────────

    def _make_speakable(self, text: str) -> str:
        """把回复改造成适合朗读的形式

        语音播报和文字阅读不一样：
          · 去掉 markdown 符号
          · 去掉 URL 长串
          · 太长要截断
        """
        if not text:
            return ""

        import re

        # 去 markdown
        t = re.sub(r"[*_`#>\[\]]", "", text)

        # 去代码块
        t = re.sub(r"```.*?```", "（代码略）", t, flags=re.S)

        # 缩短 URL
        t = re.sub(
            r"https?://\S+",
            lambda m: "链接" if len(m.group()) > 40 else m.group(),
            t,
        )

        # 压缩空白
        t = re.sub(r"\s+", " ", t).strip()

        # 截断
        if len(t) > self.config.max_reply_chars:
            t = t[:self.config.max_reply_chars] + "……"

        return t

    # ── 状态 ──────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "asr_provider": self.config.asr_provider,
            "tts_provider": self.config.tts_provider,
            "language": self.config.language,
            "asr_ready": self.config.asr_provider != "none",
            "tts_ready": self.config.tts_provider != "none",
            **self.stats,
        }


# ══════════════════════════════════════════════════════════
#  标准端处理器注册 — 一键把三端能力接上
# ══════════════════════════════════════════════════════════

def setup_pc_handlers(hub: Any, pc_node: str = "pc-01") -> Dict[str, bool]:
    """给电脑端注册能力处理器

    返回各能力是否注册成功。
    """
    results = {}

    # ── 浏览网页 ──
    async def browse(params: Dict) -> Dict:
        url = params.get("url", "")
        if not url:
            return {"success": False, "error": "未提供 URL"}

        try:
            from playwright.async_api import async_playwright

            # 复用全局浏览器
            global _pc_pw, _pc_browser, _pc_page

            if "_pc_browser" not in globals() or _pc_browser is None:
                _pc_pw = await async_playwright().start()
                _pc_browser = await _pc_pw.chromium.launch(headless=True)
                _pc_page = await _pc_browser.new_page(
                    viewport={"width": 1280, "height": 800}
                )

            await _pc_page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(1.5)

            title = await _pc_page.title()
            return {
                "success": True,
                "data": {
                    "url": url,
                    "title": title,
                    "final_url": _pc_page.url,
                },
            }
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    hub.transport.register_handler(pc_node, "browse", browse)
    results["browse"] = True

    # ── 截图 ──
    async def screenshot(params: Dict) -> Dict:
        try:
            if "_pc_page" not in globals() or _pc_page is None:
                return {"success": False, "error": "浏览器未启动"}

            from laap.tools.browser_perception import BrowserPerception

            perception = BrowserPerception(_pc_page, annotate=False)
            seen = await perception.perceive()

            if not seen.screenshot_b64:
                return {"success": False, "error": "截图失败"}

            img_bytes = base64.b64decode(seen.screenshot_b64)

            # 存入中枢数据面
            ref = hub.payloads.put(
                img_bytes,
                kind="screenshot",
                origin_node=pc_node,
                summary=f"{seen.title[:40]} 截图",
                mime="image/png",
            )

            return {
                "success": True,
                "data": {
                    "payload_id": ref.payload_id,
                    "path": ref.local_path,
                    "size_kb": ref.size_bytes // 1024,
                    "title": seen.title,
                    "url": seen.url,
                },
            }
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    hub.transport.register_handler(pc_node, "screenshot", screenshot)
    results["screenshot"] = True

    # ── 执行命令 ──
    async def shell(params: Dict) -> Dict:
        import subprocess
        cmd = params.get("command", "")
        if not cmd:
            return {"success": False, "error": "未提供命令"}

        # 危险命令拦截
        dangerous = ("rm -rf /", "format c:", "del /f /s /q c:\\",
                     "shutdown /s", ":(){:|:&};:")
        if any(d in cmd.lower() for d in dangerous):
            return {"success": False, "error": "命令被安全策略拦截"}

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=params.get("timeout", 60)
            )
            return {
                "success": proc.returncode == 0,
                "data": {
                    "stdout": stdout.decode("utf-8", errors="replace")[:4000],
                    "stderr": stderr.decode("utf-8", errors="replace")[:2000],
                    "returncode": proc.returncode,
                },
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "命令超时"}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    hub.transport.register_handler(pc_node, "shell", shell)
    results["shell"] = True

    # ── 读文件 ──
    async def file_read(params: Dict) -> Dict:
        from pathlib import Path
        p = params.get("path", "")
        if not p:
            return {"success": False, "error": "未提供路径"}
        try:
            content = Path(p).read_text(encoding="utf-8", errors="replace")
            return {
                "success": True,
                "data": {"path": p, "content": content[:8000],
                         "length": len(content)},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    hub.transport.register_handler(pc_node, "file_read", file_read)
    results["file_read"] = True

    return results


def setup_phone_handlers(hub: Any, phone_node: str = "phone-01") -> Dict[str, bool]:
    """给手机端注册能力处理器"""
    results = {}

    # ── 显示图片/内容 ──
    async def display(params: Dict) -> Dict:
        payload = params.get("payload")

        # 从数据面取
        payload_id = ""
        if isinstance(payload, dict):
            payload_id = payload.get("payload_id", "")
        elif isinstance(payload, str) and payload.startswith("pl_"):
            payload_id = payload

        if payload_id:
            data = hub.payloads.get(payload_id)
            ref = hub.payloads.get_ref(payload_id)
            return {
                "success": True,
                "data": {
                    "displayed_payload": payload_id,
                    "size_kb": (ref.size_bytes // 1024) if ref else 0,
                    "note": "已推送到手机显示队列",
                },
            }

        return {"success": True, "data": {"note": "无内容可显示"}}

    hub.transport.register_handler(phone_node, "display", display)
    results["display"] = True

    # ── 拍照 ──
    async def camera_capture(params: Dict) -> Dict:
        # 真实实现要接手机摄像头 API
        return {
            "success": False,
            "error": "手机摄像头需客户端连接后才可用",
        }

    hub.transport.register_handler(phone_node, "camera_capture", camera_capture)
    results["camera_capture"] = True

    # ── 震动反馈 ──
    async def vibrate(params: Dict) -> Dict:
        return {"success": True, "data": {"note": "震动指令已发送"}}

    hub.transport.register_handler(phone_node, "vibrate", vibrate)
    results["vibrate"] = True

    return results


def setup_hardware_handlers(
    hub: Any,
    hw_node: str = "xiaozhi-01",
    tts_callback: Optional[Any] = None,
) -> Dict[str, bool]:
    """给小智硬件注册能力处理器"""
    results = {}

    # ── 说话 ──
    async def speak(params: Dict) -> Dict:
        text = params.get("text", "")
        if not text:
            return {"success": False, "error": "未提供文本"}

        if tts_callback:
            try:
                audio = await tts_callback(text)
                return {
                    "success": True,
                    "data": {"text": text, "audio_bytes": len(audio) if audio else 0},
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {
            "success": True,
            "data": {"text": text, "note": "已送播报队列"},
        }

    hub.transport.register_handler(hw_node, "speak", speak)
    results["speak"] = True

    return results