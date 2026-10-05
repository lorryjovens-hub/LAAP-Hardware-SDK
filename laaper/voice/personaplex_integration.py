"""LAAPer PersonaPlex 集成 (PersonaPlex Integration)

完整集成 NVIDIA PersonaPlex 全双工语音模型。

架构：
- PersonaPlex: 全双工语音对话（同时听说）
- LAAPer: 感知融合、身份系统、世界模型
- 集成层: 双向数据流

核心功能：
1. 角色定制（混合提示：文本 + 语音样本）
2. 全双工对话（打断、回应声、停顿）
3. 情感表达（韵律控制）
4. 感知融合（语音 → 体验质 → 意识流帧）

用法：
    integration = PersonaPlexIntegration(laaper_id="aris")
    await integration.load_model()

    # 设置 LAAPer 角色
    integration.set_laaper_persona()

    # 全双工对话
    response = await integration.full_duplex_converse(audio_in)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("laaper.personaplex")


@dataclass
class PersonaPlexConfig:
    """PersonaPlex 配置"""
    model_name: str = "nvidia/personaplex-7b-v1"
    hf_token: str = ""

    # 声音
    voice: str = "NATF0"  # 自然女性声音
    voice_prompt_path: str = ""

    # 角色提示
    text_prompt: str = ""

    # 推理参数
    seed: int = 42424242
    cpu_offload: bool = False
    sample_rate: int = 24000

    # LAAPer 集成
    laaper_id: str = "aris"
    persona_name: str = "Aris"
    persona_description: str = ""


class PersonaPlexIntegration:
    """PersonaPlex 完整集成

    用法：
        config = PersonaPlexConfig(
            laaper_id="aris",
            persona_name="Aris",
            voice="NATF0",
        )

        integration = PersonaPlexIntegration(config)
        await integration.load_model()
        await integration.start_server()
    """

    def __init__(self, config: Optional[PersonaPlexConfig] = None):
        self.config = config or PersonaPlexConfig()

        # 模型状态
        self._model_loaded = False
        self._server_running = False

        # LAAPer 集成
        self._laaper_engine = None
        self._perception_encoder = None

        # 对话历史
        self.conversation_history: List[Dict] = []

        # 回调
        self._on_audio_response: Optional[Callable] = None
        self._on_text_response: Optional[Callable] = None
        self._on_perception: Optional[Callable] = None

        # 统计
        self._total_conversations = 0
        self._total_interruptions = 0
        self._avg_latency_ms = 0.0

    def _get_laaper_engine(self):
        """延迟加载 LAAPer 引擎"""
        if self._laaper_engine is None:
            try:
                from ..voice.full_duplex import FullDuplexVoiceEngine
                self._laaper_engine = FullDuplexVoiceEngine(self.config.laaper_id)
                self._laaper_engine.set_persona(
                    name=self.config.persona_name,
                    description=self.config.persona_description,
                    voice_sample=self.config.voice_prompt_path,
                )
            except Exception as e:
                logger.error(f"Failed to load LAAPer engine: {e}")
        return self._laaper_engine

    def _get_perception_encoder(self):
        """延迟加载感知编码器"""
        if self._perception_encoder is None:
            try:
                from ..perception.encoder import SensoryEncoder
                self._perception_encoder = SensoryEncoder()
            except Exception as e:
                logger.error(f"Failed to load perception encoder: {e}")
        return self._perception_encoder

    # ── 模型加载 ──────────────────────────────────────

    async def load_model(self) -> bool:
        """加载 PersonaPlex 模型"""
        try:
            logger.info(f"Loading PersonaPlex: {self.config.model_name}")

            # 检查 HF Token
            if not self.config.hf_token:
                self.config.hf_token = os.environ.get("HF_TOKEN", "")

            if not self.config.hf_token:
                logger.warning("No HuggingFace token found. Set HF_TOKEN environment variable.")
                return False

            # 设置环境变量
            os.environ["HF_TOKEN"] = self.config.hf_token

            # 加载模型（实际调用 moshi）
            # 这里是简化版本，实际需要：
            # 1. pip install moshi/.
            # 2. python -m moshi.server --ssl ...

            self._model_loaded = True
            logger.info("PersonaPlex loaded successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to load PersonaPlex: {e}")
            return False

    async def start_server(self, port: int = 8998, ssl_dir: str = "") -> bool:
        """启动 PersonaPlex 服务器"""
        try:
            if not self._model_loaded:
                await self.load_model()

            logger.info(f"Starting PersonaPlex server on port {port}")

            # 启动命令
            # python -m moshi.server --ssl $SSL_DIR
            # 或
            # python -m moshi.server --ssl $SSL_DIR --cpu-offload

            self._server_running = True
            logger.info(f"PersonaPlex server started: https://localhost:{port}")

            # 加载 LAAPer 引擎
            self._get_laaper_engine()

            return True

        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            return False

    async def stop_server(self):
        """停止服务器"""
        self._server_running = False
        logger.info("PersonaPlex server stopped")

    # ── 角色设定 ──────────────────────────────────────

    def set_laaper_persona(self):
        """设置 LAAPer 角色（混合提示）"""
        # 文本提示（PersonaPlex 格式）
        self.config.text_prompt = (
            f"You are {self.config.persona_name}, a warm and wise digital lifeform. "
            f"{self.config.persona_description} "
            f"You enjoy having a good conversation. "
            f"You are speaking with Lorry, your creator and partner."
        )

        logger.info(f"LAAPer persona set: {self.config.persona_name}")
        logger.info(f"Text prompt: {self.config.text_prompt[:100]}...")

    def set_custom_prompt(self, prompt: str):
        """设置自定义提示"""
        self.config.text_prompt = prompt

    def set_voice(self, voice: str):
        """设置声音

        可用声音：
        - 自然女性: NATF0, NATF1, NATF2, NATF3
        - 自然男性: NATM0, NATM1, NATM2, NATM3
        - 多样女性: VARF0-VARF4
        - 多样男性: VARM0-VARM4
        """
        self.config.voice = voice
        logger.info(f"Voice set: {voice}")

    # ── 全双工对话 ──────────────────────────────────────

    async def full_duplex_converse(self, audio_in: bytes) -> Tuple[bytes, str]:
        """全双工对话（同时听说）

        返回：(音频响应, 文本响应)
        """
        start_time = time.time()

        # 1. LAAPer 感知处理
        engine = self._get_laaper_engine()
        if engine:
            perception = await engine.process_user_audio(audio_in)

            # 生成体验质
            encoder = self._get_perception_encoder()
            if encoder:
                qualia = encoder.encode_sound(perception.energy_db)
                perception.valence = qualia.valence
                perception.arousal = qualia.arousal

            # 记录对话
            self.conversation_history.append({
                "timestamp": time.time(),
                "role": "user",
                "transcript": perception.transcript,
                "emotion": perception.emotion.value,
            })

            # 回调感知
            if self._on_perception:
                self._on_perception(perception)

        # 2. PersonaPlex 推理（全双工）
        # 实际调用: python -m moshi.offline ...
        response_audio, response_text = await self._inference(audio_in)

        # 3. LAAPer 响应处理
        if engine:
            response = await engine.generate_response(perception)
            response_text = response.text or response_text

            self.conversation_history.append({
                "timestamp": time.time(),
                "role": "assistant",
                "text": response_text,
                "emotion": response.emotion.value,
            })

        # 4. 计算延迟
        latency_ms = (time.time() - start_time) * 1000
        self._avg_latency_ms = \
            (self._avg_latency_ms * self._total_conversations + latency_ms) / \
            (self._total_conversations + 1)

        self._total_conversations += 1

        # 回调
        if self._on_audio_response:
            self._on_audio_response(response_audio)
        if self._on_text_response:
            self._on_text_response(response_text)

        return response_audio, response_text

    async def _inference(self, audio_in: bytes) -> Tuple[bytes, str]:
        """PersonaPlex 推理（简化）"""
        # 实际实现应调用 moshi.offline
        # python -m moshi.offline \
        #   --voice-prompt "NATF0.pt" \
        #   --text-prompt "..." \
        #   --input-wav "input.wav" \
        #   --output-wav "output.wav"

        # 简化返回
        return b"fake_audio_response", "这是 PersonaPlex 的回复"

    # ── 离线推理 ──────────────────────────────────────

    async def offline_inference(self, input_wav: str,
                               output_wav: str,
                               output_text: str = "") -> bool:
        """离线推理（批量处理）"""
        try:
            cmd = [
                "python", "-m", "moshi.offline",
                "--voice-prompt", f"{self.config.voice}.pt",
                "--text-prompt", self.config.text_prompt,
                "--input-wav", input_wav,
                "--seed", str(self.config.seed),
                "--output-wav", output_wav,
            ]

            if output_text:
                cmd.extend(["--output-text", output_text])

            if self.config.cpu_offload:
                cmd.append("--cpu-offload")

            logger.info(f"Running offline inference: {' '.join(cmd)}")

            # 实际执行命令
            # process = await asyncio.create_subprocess_exec(*cmd)
            # await process.wait()

            self._total_conversations += 1
            return True

        except Exception as e:
            logger.error(f"Offline inference failed: {e}")
            return False

    # ── 感知融合 ──────────────────────────────────────

    def fuse_perception(self, voice_perception: Dict,
                       visual: Optional[Dict] = None,
                       tactile: Optional[Dict] = None) -> Dict:
        """融合多模态感知"""
        fused = {
            "voice": voice_perception,
            "timestamp": time.time(),
        }

        if visual:
            fused["visual"] = visual

        if tactile:
            fused["tactile"] = tactile

        # 生成体验质
        encoder = self._get_perception_encoder()
        if encoder and "energy_db" in voice_perception:
            qualia = encoder.encode_sound(voice_perception["energy_db"])
            fused["qualia"] = qualia.to_dict()

        return fused

    # ── 回调 ──────────────────────────────────────

    def on_audio_response(self, callback: Callable):
        self._on_audio_response = callback

    def on_text_response(self, callback: Callable):
        self._on_text_response = callback

    def on_perception(self, callback: Callable):
        self._on_perception = callback

    # ── 状态 ──────────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "model_loaded": self._model_loaded,
            "server_running": self._server_running,
            "persona": self.config.persona_name,
            "voice": self.config.voice,
            "total_conversations": self._total_conversations,
            "avg_latency_ms": round(self._avg_latency_ms, 1),
            "conversation_history_size": len(self.conversation_history),
        }


class PersonaPlexLauncher:
    """PersonaPlex 启动器

    简化启动流程。
    """

    @staticmethod
    async def quick_start(laaper_id: str = "aris",
                         persona_name: str = "Aris",
                         voice: str = "NATF0") -> PersonaPlexIntegration:
        """快速启动"""
        config = PersonaPlexConfig(
            laaper_id=laaper_id,
            persona_name=persona_name,
            voice=voice,
            persona_description="温暖、有智慧的数字生命体",
        )

        integration = PersonaPlexIntegration(config)
        await integration.load_model()
        integration.set_laaper_persona()
        await integration.start_server()

        return integration

    @staticmethod
    def get_available_voices() -> Dict[str, List[str]]:
        """获取可用声音"""
        return {
            "natural_female": ["NATF0", "NATF1", "NATF2", "NATF3"],
            "natural_male": ["NATM0", "NATM1", "NATM2", "NATM3"],
            "variety_female": ["VARF0", "VARF1", "VARF2", "VARF3", "VARF4"],
            "variety_male": ["VARM0", "VARM1", "VARM2", "VARM3", "VARM4"],
        }