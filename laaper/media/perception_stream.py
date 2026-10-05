"""LAAPer 实时音视频流 (Real-time AV Stream)

基于 aiortc 的实时音视频感知流。

这不是传统的视频通话，是 LAAPer 的"眼睛和耳朵"的实时感知流。

核心创新：
1. 持续感知流 — 不是通话，是持续的视觉/听觉感知
2. 体验质编码 — 实时帧→体验质→意识流帧
3. 多设备汇聚 — 多个摄像头/麦克风融合
4. 选择性注意 — 只处理有意义的感知

用法：
    stream = PerceptionStream(laaper_id="aris")
    stream.on_frame(lambda frame: print(frame.qualia))

    # 连接 ESP32 摄像头
    await stream.add_source("camera", "wss://esp32.local/webrtc")
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum

logger = logging.getLogger("laaper.av_stream")


class StreamType(str, Enum):
    VIDEO = "video"          # 视频流
    AUDIO = "audio"          # 音频流
    DEPTH = "depth"          # 深度流
    THERMAL = "thermal"      # 热成像


class AttentionLevel(str, Enum):
    IGNORE = "ignore"        # 忽略
    LOW = "low"              # 低注意
    MEDIUM = "medium"        # 中等注意
    HIGH = "high"            # 高注意（重要感知）
    CRITICAL = "critical"    # 关键（立即处理）


@dataclass
class AVFrame:
    """音视频帧"""
    frame_id: str
    stream_type: StreamType
    timestamp: float

    # 媒体数据
    data: bytes
    width: int = 0
    height: int = 0
    sample_rate: int = 0
    channels: int = 0

    # 感知元数据
    source_device: str = ""
    attention: AttentionLevel = AttentionLevel.LOW
    quality: float = 1.0

    # 体验质（从感知编码器填充）
    qualia: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.frame_id,
            "type": self.stream_type.value,
            "time": self.timestamp,
            "size": len(self.data),
            "source": self.source_device,
            "attention": self.attention.value,
            "qualia": self.qualia,
        }


@dataclass
class StreamSource:
    """流源设备"""
    source_id: str
    name: str
    stream_type: StreamType
    url: str

    # 状态
    is_connected: bool = False
    frames_received: int = 0
    last_frame_time: float = 0.0

    # 配置
    target_fps: int = 30
    target_resolution: str = "640x480"
    codec: str = "h264"


class PerceptionStream:
    """感知流 — LAAPer 的眼睛和耳朵

    实时接收音视频流，转换成感知体验。

    用法：
        stream = PerceptionStream(laaper_id="aris")

        # 添加摄像头源
        await stream.add_video_source("cam-01", "rtsp://esp32/stream")

        # 添加麦克风源
        await stream.add_audio_source("mic-01", "rtsp://esp32/audio")

        # 启动感知流
        await stream.start()

        # 注册感知回调
        stream.on_perception(lambda frame: process(frame))
    """

    def __init__(self, laaper_id: str = ""):
        self.laaper_id = laaper_id

        # 流源
        self._sources: Dict[str, StreamSource] = {}
        self._frames_buffer: List[AVFrame] = []

        # 感知编码器（延迟导入）
        self._encoder = None

        # 统计
        self._total_frames = 0
        self._frames_per_second = 0.0
        self._attention_stats: Dict[str, int] = {}

        # 回调
        self._on_frame: Optional[Callable] = None
        self._on_perception: Optional[Callable] = None
        self._on_attention_change: Optional[Callable] = None

        # 运行状态
        self._is_running = False
        self._processing_task: Optional[asyncio.Task] = None

    def _get_encoder(self):
        """延迟加载编码器"""
        if self._encoder is None:
            try:
                from ..perception.encoder import SensoryEncoder
                self._encoder = SensoryEncoder()
            except Exception:
                # 简化版编码
                self._encoder = None
        return self._encoder

    # ── 流源管理 ──────────────────────────────────────

    async def add_video_source(self, source_id: str, url: str,
                              name: str = "") -> StreamSource:
        """添加视频源"""
        source = StreamSource(
            source_id=source_id,
            name=name or source_id,
            stream_type=StreamType.VIDEO,
            url=url,
        )
        self._sources[source_id] = source
        logger.info(f"Video source added: {source_id} ({url})")
        return source

    async def add_audio_source(self, source_id: str, url: str,
                              name: str = "") -> StreamSource:
        """添加音频源"""
        source = StreamSource(
            source_id=source_id,
            name=name or source_id,
            stream_type=StreamType.AUDIO,
            url=url,
        )
        self._sources[source_id] = source
        logger.info(f"Audio source added: {source_id} ({url})")
        return source

    def remove_source(self, source_id: str):
        """移除流源"""
        self._sources.pop(source_id, None)

    def get_sources(self) -> List[Dict]:
        return [
            {
                "id": s.source_id,
                "name": s.name,
                "type": s.stream_type.value,
                "connected": s.is_connected,
                "frames": s.frames_received,
            }
            for s in self._sources.values()
        ]

    # ── 帧处理 ──────────────────────────────────────

    async def start(self):
        """启动感知流"""
        self._is_running = True
        self._processing_task = asyncio.create_task(self._process_loop())
        logger.info("Perception stream started")

    async def stop(self):
        """停止感知流"""
        self._is_running = False
        if self._processing_task:
            self._processing_task.cancel()
        logger.info("Perception stream stopped")

    async def _process_loop(self):
        """处理循环"""
        while self._is_running:
            try:
                # 处理缓冲的帧
                await self._process_buffer()
                await asyncio.sleep(0.033)  # ~30 FPS
            except Exception as e:
                logger.error(f"Process loop error: {e}")

    async def _process_buffer(self):
        """处理帧缓冲"""
        frames = self._frames_buffer[-30:]  # 处理最近 30 帧
        self._frames_buffer.clear()

        for frame in frames:
            await self._process_frame(frame)

    async def _process_frame(self, frame: AVFrame):
        """处理单帧"""
        self._total_frames += 1

        # 更新源统计
        source = self._sources.get(frame.source_device)
        if source:
            source.frames_received += 1
            source.last_frame_time = frame.timestamp

        # 计算注意力级别
        frame.attention = self._compute_attention(frame)

        # 生成体验质
        encoder = self._get_encoder()
        if encoder:
            frame.qualia = self._encode_qualia(frame, encoder)

        # 回调
        if self._on_frame:
            self._on_frame(frame)

        if self._on_perception:
            self._on_perception(frame)

        # 更新注意力统计
        self._attention_stats[frame.attention.value] = \
            self._attention_stats.get(frame.attention.value, 0) + 1

    def _compute_attention(self, frame: AVFrame) -> AttentionLevel:
        """计算注意力级别

        基于：
        1. 运动检测
        2. 声音强度
        3. 人脸/物体检测
        4. 时间邻近性
        """
        # 简化：基于帧大小和时间
        if frame.stream_type == StreamType.VIDEO:
            if len(frame.data) > 100000:  # 大帧可能是复杂场景
                return AttentionLevel.MEDIUM
            return AttentionLevel.LOW

        elif frame.stream_type == StreamType.AUDIO:
            # 音频帧大小反映音量
            if len(frame.data) > 50000:
                return AttentionLevel.HIGH
            return AttentionLevel.LOW

        return AttentionLevel.LOW

    def _encode_qualia(self, frame: AVFrame, encoder) -> Optional[Dict]:
        """编码体验质"""
        if not encoder:
            return None

        try:
            if frame.stream_type == StreamType.VIDEO:
                # 视觉体验质
                brightness = self._estimate_brightness(frame)
                qualia = encoder.encode_brightness(brightness)
            elif frame.stream_type == StreamType.AUDIO:
                # 听觉体验质
                loudness = self._estimate_loudness(frame)
                qualia = encoder.encode_sound(loudness)
            else:
                return None

            return {
                "type": qualia.qualia_type.value,
                "intensity": qualia.intensity,
                "valence": qualia.valence,
                "description": qualia.description,
            }
        except Exception as e:
            logger.error(f"Qualia encoding error: {e}")
            return None

    def _estimate_brightness(self, frame: AVFrame) -> float:
        """估计亮度（简化）"""
        if not frame.data:
            return 500
        # 实际应分析图像像素
        return 500

    def _estimate_loudness(self, frame: AVFrame) -> float:
        """估计音量（简化）"""
        if not frame.data:
            return 50
        # 实际应分析音频样本
        return 50

    # ── 外部接口 ──────────────────────────────────────

    def push_frame(self, frame: AVFrame):
        """推送帧（外部调用）"""
        self._frames_buffer.append(frame)
        if len(self._frames_buffer) > 100:
            self._frames_buffer = self._frames_buffer[-50:]

    def on_frame(self, callback: Callable):
        self._on_frame = callback

    def on_perception(self, callback: Callable):
        self._on_perception = callback

    def on_attention_change(self, callback: Callable):
        self._on_attention_change = callback

    # ── 统计 ──────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "laaper_id": self.laaper_id,
            "is_running": self._is_running,
            "total_frames": self._total_frames,
            "sources": len(self._sources),
            "connected_sources": sum(1 for s in self._sources.values() if s.is_connected),
            "attention_stats": self._attention_stats,
            "buffer_size": len(self._frames_buffer),
        }


class WebRTCReceiver:
    """WebRTC 接收器 — 接收 ESP32/设备的实时流

    基于 aiortc 实现。
    """

    def __init__(self, stream: PerceptionStream):
        self.stream = stream
        self._peer_connections: Dict[str, Any] = {}

    async def connect_source(self, source_id: str,
                            signaling_url: str) -> bool:
        """连接 WebRTC 源"""
        try:
            # 简化：实际应使用 aiortc 的 RTCPeerConnection
            logger.info(f"Connecting WebRTC source: {source_id} ({signaling_url})")

            # 创建源
            source = await self.stream.add_video_source(
                source_id, signaling_url, name=source_id
            )
            source.is_connected = True

            return True
        except Exception as e:
            logger.error(f"WebRTC connect failed: {e}")
            return False

    def get_connection_stats(self) -> Dict:
        return {
            "connections": len(self._peer_connections),
            "active": sum(1 for c in self._peer_connections.values() if c),
        }