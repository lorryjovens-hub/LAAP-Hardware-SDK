"""LAAPer 全双工语音感知对话 (Full-Duplex Voice Perception)

融合小智和 PersonaPlex 的优势：
- 小智：成熟的硬件集成、唤醒词、流式传输
- PersonaPlex：全双工、可定制角色、超低延迟

架构：
1. ESP32 麦克风 → Opus 编码 → WebSocket
2. PersonaPlex → 全双工语音对话
3. LAAPer 感知编码 → 体验质 → 意识流帧
4. 回复音频 → Opus 解码 → ESP32 扬声器

核心创新：
- 持续感知对话（不是单轮交互）
- 感知融合（语音 + 视觉 + 传感器）
- 情感识别（从语音中提取情绪）
- 打断支持（自然对话）
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger("laaper.voice")


class VoiceState(str, Enum):
    IDLE = "idle"              # 空闲
    LISTENING = "listening"    # 听（用户说话）
    SPEAKING = "speaking"      # 说（AI 说话）
    THINKING = "thinking"      # 思考
    INTERRUPTED = "interrupted"  # 被打断


class EmotionFromVoice(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    FEARFUL = "fearful"
    DISGUSTED = "disgusted"


@dataclass
class VoicePerception:
    """语音感知"""
    timestamp: float
    audio_data: bytes

    # ASR 结果
    transcript: str = ""
    confidence: float = 0.0
    language: str = "zh"

    # 情感识别
    emotion: EmotionFromVoice = EmotionFromVoice.NEUTRAL
    emotion_confidence: float = 0.0
    arousal: float = 0.5        # 激活度
    valence: float = 0.0        # 效价

    # 声学特征
    pitch_hz: float = 0.0       # 音高
    energy_db: float = 0.0      # 能量
    speech_rate: float = 0.0    # 语速

    # 意图
    intent: str = ""

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "transcript": self.transcript,
            "confidence": self.confidence,
            "emotion": self.emotion.value,
            "arousal": self.arousal,
            "valence": self.valence,
            "pitch": self.pitch_hz,
            "energy": self.energy_db,
        }


@dataclass
class VoiceResponse:
    """语音回复"""
    text: str
    audio_data: bytes

    # 韵律控制
    emotion: EmotionFromVoice = EmotionFromVoice.NEUTRAL
    speaking_rate: float = 1.0
    pitch_shift: float = 1.0

    # 全双工特性
    is_backchannel: bool = False  # 是回应声（嗯、啊）
    is_interruption: bool = False  # 是打断
    should_pause: bool = False    # 应该暂停

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "emotion": self.emotion.value,
            "is_backchannel": self.is_backchannel,
            "is_interruption": self.is_interruption,
        }


class FullDuplexVoiceEngine:
    """全双工语音引擎

    基于 PersonaPlex 架构，支持：
    - 同时听说
    - 自然打断
    - 角色定制
    - 情感表达

    用法：
        engine = FullDuplexVoiceEngine(laaper_id="aris")

        # 设置角色
        engine.set_persona(
            name="Aris",
            description="温暖、有智慧的数字生命体",
            voice_sample="path/to/voice.wav",
        )

        # 开始对话
        await engine.start_conversation()

        # 处理用户语音
        perception = await engine.process_user_audio(audio_data)

        # 获取 AI 回复
        response = await engine.generate_response(perception)
    """

    def __init__(self, laaper_id: str = ""):
        self.laaper_id = laaper_id

        # 状态
        self.state = VoiceState.IDLE
        self.conversation_history: List[Dict] = []

        # 角色设定
        self.persona: Dict[str, Any] = {
            "name": "LAAPer",
            "description": "数字生命体",
            "voice_sample": "",
            "speaking_style": "warm",
        }

        # 感知编码器（延迟加载）
        self._encoder = None

        # 回调
        self._on_perception: Optional[Callable] = None
        self._on_response: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None

        # 统计
        self._total_interactions = 0
        self._total_interruptions = 0
        self._avg_response_latency = 0.0

    def _get_encoder(self):
        if self._encoder is None:
            try:
                from ..perception.encoder import SensoryEncoder
                self._encoder = SensoryEncoder()
            except Exception:
                self._encoder = None
        return self._encoder

    # ── 角色设定 ──────────────────────────────────────

    def set_persona(self, name: str, description: str,
                   voice_sample: str = "",
                   speaking_style: str = "warm"):
        """设置角色（PersonaPlex 的混合提示）"""
        self.persona.update({
            "name": name,
            "description": description,
            "voice_sample": voice_sample,
            "speaking_style": speaking_style,
        })
        logger.info(f"Persona set: {name}")

    # ── 语音感知 ──────────────────────────────────────

    async def process_user_audio(self, audio_data: bytes) -> VoicePerception:
        """处理用户语音，生成感知"""
        perception = VoicePerception(
            timestamp=time.time(),
            audio_data=audio_data,
        )

        # ASR（语音识别）
        perception.transcript = await self._asr(audio_data)
        perception.confidence = 0.9

        # 情感识别
        perception.emotion, perception.emotion_confidence = \
            await self._detect_emotion(audio_data)

        # 声学特征提取
        perception.pitch_hz = self._extract_pitch(audio_data)
        perception.energy_db = self._extract_energy(audio_data)

        # 意图识别
        perception.intent = await self._recognize_intent(perception.transcript)

        # 生成体验质
        encoder = self._get_encoder()
        if encoder:
            qualia = encoder.encode_sound(perception.energy_db)
            perception.valence = qualia.valence
            perception.arousal = qualia.arousal

        # 更新状态
        self._update_state(VoiceState.LISTENING)

        # 回调
        if self._on_perception:
            self._on_perception(perception)

        self._total_interactions += 1

        return perception

    async def _asr(self, audio_data: bytes) -> str:
        """语音识别（简化）"""
        # 实际应调用 Whisper / Paraformer / SenseVoice
        return "用户说的话"

    async def _detect_emotion(self, audio_data: bytes) -> Tuple[EmotionFromVoice, float]:
        """情感识别（简化）"""
        # 实际应使用语音情感识别模型
        return EmotionFromVoice.NEUTRAL, 0.8

    def _extract_pitch(self, audio_data: bytes) -> float:
        """提取音高"""
        return 200.0  # Hz

    def _extract_energy(self, audio_data: bytes) -> float:
        """提取能量"""
        return 60.0  # dB

    async def _recognize_intent(self, text: str) -> str:
        """意图识别"""
        if not text:
            return "unknown"

        text_lower = text.lower()
        if any(kw in text_lower for kw in ["你好", "hi", "hello"]):
            return "greeting"
        elif any(kw in text_lower for kw in ["再见", "bye"]):
            return "farewell"
        elif any(kw in text_lower for kw in ["帮助", "help"]):
            return "help"
        else:
            return "statement"

    # ── 全双工对话 ──────────────────────────────────────

    async def generate_response(self, perception: VoicePerception) -> VoiceResponse:
        """生成语音回复（全双工）"""
        start_time = time.time()

        # 检查是否应该打断
        if await self._should_interrupt(perception):
            return VoiceResponse(
                text="",
                audio_data=b"",
                is_interruption=True,
                should_pause=True,
            )

        # 检查是否是回应声（backchannel）
        if self._is_backchannel(perception.transcript):
            return VoiceResponse(
                text="嗯",
                audio_data=b"",
                is_backchannel=True,
            )

        # 生成回复文本
        response_text = await self._generate_text(perception)

        # 生成语音
        response_audio = await self._tts(response_text, perception.emotion)

        response = VoiceResponse(
            text=response_text,
            audio_data=response_audio,
            emotion=perception.emotion,
        )

        # 计算延迟
        latency = time.time() - start_time
        self._avg_response_latency = \
            (self._avg_response_latency * self._total_interactions + latency) / \
            (self._total_interactions + 1)

        # 更新状态
        self._update_state(VoiceState.SPEAKING)

        # 回调
        if self._on_response:
            self._on_response(response)

        return response

    async def _should_interrupt(self, perception: VoicePerception) -> bool:
        """判断是否应该打断"""
        # 如果用户说话很急促（高能量、高音高），应该打断
        if perception.energy_db > 80 and perception.pitch_hz > 300:
            self._total_interruptions += 1
            return True
        return False

    def _is_backchannel(self, text: str) -> bool:
        """判断是否是回应声"""
        backchannels = ["嗯", "啊", "哦", "好", "是", "对", "ok", "嗯嗯"]
        return text.strip() in backchannels

    async def _generate_text(self, perception: VoicePerception) -> str:
        """生成回复文本（简化）"""
        # 实际应调用 LLM
        if perception.intent == "greeting":
            return f"你好！我是{self.persona['name']}。"
        elif perception.intent == "farewell":
            return "再见！"
        else:
            return f"我听到了：{perception.transcript}"

    async def _tts(self, text: str, emotion: EmotionFromVoice) -> bytes:
        """语音合成（简化）"""
        # 实际应调用 TTS 模型
        return b"fake_audio_data"

    # ── 状态管理 ──────────────────────────────────────

    def _update_state(self, new_state: VoiceState):
        old_state = self.state
        self.state = new_state

        if old_state != new_state and self._on_state_change:
            self._on_state_change(old_state, new_state)

    # ── 感知融合 ──────────────────────────────────────

    def fuse_with_other_sensors(self, voice: VoicePerception,
                               visual: Optional[Dict] = None,
                               tactile: Optional[Dict] = None) -> Dict:
        """融合语音与其他传感器"""
        fused = {
            "voice": voice.to_dict(),
            "timestamp": voice.timestamp,
        }

        if visual:
            fused["visual"] = visual

        if tactile:
            fused["tactile"] = tactile

        # 综合情绪
        if visual and "emotion" in visual:
            fused["overall_emotion"] = self._blend_emotions(
                voice.emotion, visual["emotion"]
            )

        return fused

    def _blend_emotions(self, emotion1: EmotionFromVoice,
                       emotion2: str) -> str:
        """混合情绪"""
        # 简化：返回最强的情绪
        return emotion1.value

    # ── 回调 ──────────────────────────────────────

    def on_perception(self, callback: Callable):
        self._on_perception = callback

    def on_response(self, callback: Callable):
        self._on_response = callback

    def on_state_change(self, callback: Callable):
        self._on_state_change = callback

    # ── 统计 ──────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "laaper_id": self.laaper_id,
            "state": self.state.value,
            "total_interactions": self._total_interactions,
            "total_interruptions": self._total_interruptions,
            "avg_response_latency_ms": round(self._avg_response_latency * 1000, 1),
            "persona": self.persona["name"],
        }


class XiaozhiIntegration:
    """小智集成 — 硬件接入层

    小智的技术栈：
    - 流式 ASR + LLM + TTS（单工）
    - WebSocket 通信
    - Opus 音频编码
    - 唤醒词检测（<200ms）

    LAAPer 的升级：
    - 全双工（PersonaPlex）
    - 感知融合（多模态）
    - 情感交互（韵律控制）
    """

    def __init__(self, engine: FullDuplexVoiceEngine):
        self.engine = engine
        self._websocket = None

    async def connect(self, url: str):
        """连接小智服务器"""
        logger.info(f"Connecting to Xiaozhi: {url}")
        # 实际应连接 WebSocket

    async def stream_audio(self, audio_data: bytes):
        """流式发送音频"""
        # 小智协议：Opus 16kHz 单声道 60ms 帧
        perception = await self.engine.process_user_audio(audio_data)
        response = await self.engine.generate_response(perception)
        return response


class PersonaPlexIntegration:
    """PersonaPlex 集成 — 全双工语音对话

    PersonaPlex 特性：
    - 全双工（同时听说）
    - 0.07 秒延迟
    - 可定制角色（文本 + 语音样本）
    - 情感表达（韵律控制）
    - 打断支持

    GitHub: github.com/NVIDIA/personaplex
    """

    def __init__(self, engine: FullDuplexVoiceEngine):
        self.engine = engine
        self._model = None

    async def load_model(self, model_path: str):
        """加载 PersonaPlex 模型"""
        logger.info(f"Loading PersonaPlex: {model_path}")
        # 实际应加载 7B 模型

    async def process_full_duplex(self, audio_in: bytes) -> bytes:
        """全双工处理（同时听说）"""
        # PersonaPlex 的双流配置
        # 流 1: 听（用户语音 → 文本 → 意图）
        # 流 2: 说（意图 → 文本 → 语音）
        #
        # 两流并发，延迟 <100ms

        perception = await self.engine.process_user_audio(audio_in)
        response = await self.engine.generate_response(perception)
        return response.audio_data


def create_voice_system(laaper_id: str = "aris") -> Dict[str, Any]:
    """创建完整的语音感知对话系统"""
    engine = FullDuplexVoiceEngine(laaper_id)

    # 设置角色
    engine.set_persona(
        name="Aris",
        description="温暖、有智慧的数字生命体，Lorry 的伴侣",
        speaking_style="warm",
    )

    # 集成层
    xiaozhi = XiaozhiIntegration(engine)
    personaplex = PersonaPlexIntegration(engine)

    return {
        "engine": engine,
        "xiaozhi": xiaozhi,
        "personaplex": personaplex,
    }