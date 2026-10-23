"""小智音频流直连 — LAAP 直接收设备的 Opus 音频

## 架构（真正的脱离云端）

    小智硬件 (ESP32)  ──WebSocket──▶  LAAP XiaozhiAudioServer (本模块)
                                         │
                                ┌────────┴─────────┐
                                │  Opus 解码 (PyAV) │
                                │  能量 VAD         │
                                │  ASR（可插拔）     │
                                │  LAAP 大脑/电脑控制 │
                                │  TTS（edge-tts）  │
                                │  Opus 编码 (PyAV) │
                                └────────┬─────────┘
                                         │ 二进制 Opus + {"type":"tts"} 文本
                                         ↓
                                   扬声器播出

不需要 xiaozhi.me 云端。音频在 LAAP 本地进出。

## 协议（和 xiaozhi-esp32-server 兼容）

设备 → 服务器：
    {"type": "hello", "audio_params": {"format": "opus", "sample_rate": 16000}}
    {"type": "listen", "state": "detect"}    # 设备开始听
    [二进制]  Opus 编码的音频包（20ms/包 @ 16kHz）

服务器 → 设备：
    {"type": "hello", "audio_params": {...}, "session_id": "..."}
    {"type": "stt", "text": "识别出的文字"}
    {"type": "tts", "text": "要念的话"}
    [二进制]  Opus 编码的 TTS 音频

## 用法

    from laaper.hub.xiaozhi_audio_stream import XiaozhiAudioServer, AudioConfig

    server = XiaozhiAudioServer(
        port=8000,
        brain=voice_link,     # 任何有 handle(text) 的东西
        config=AudioConfig(
            asr_url="https://api.groq.com/openai/v1/audio/transcriptions",
            asr_key="...",
            asr_model="whisper-large-v3-turbo",
        ),
    )

    await server.start()
    # 设备固件 WS 地址改成 ws://<电脑IP>:8000
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("laaper.hub.audio")

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = int(SAMPLE_RATE * FRAME_MS / 1000) * 2   # 16bit = 640 bytes


# ══════════════════════════════════════════════════════════
#  Opus 编解码（PyAV libopus）
# ══════════════════════════════════════════════════════════

class OpusCodec:
    """Opus 编解码器（PyAV 封装）"""

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

        import av
        self._av = av

        # 解码器（opus → PCM）
        self.decoder = av.CodecContext.create("libopus", "r")
        self.decoder.sample_rate = sample_rate
        self.decoder.format = "s16"
        self.decoder.layout = "mono" if channels == 1 else "stereo"

        # 编码器（PCM → opus）
        self.encoder = av.CodecContext.create("libopus", "w")
        self.encoder.sample_rate = sample_rate
        self.encoder.format = "s16"
        self.encoder.layout = "mono" if channels == 1 else "stereo"
        self.encoder.bit_rate = 24000
        self.encoder.options = {
            "application": "voip",
            "frame_duration": str(FRAME_MS),
        }

        # 分包缓冲
        self._packet_buffer: List[bytes] = []

    def decode(self, opus_packet: bytes) -> Optional[bytes]:
        """Opus 包 → PCM bytes（16bit LE）"""
        try:
            import av

            packet = av.Packet(opus_packet)
            frames = self.decoder.decode(packet)

            out = b""
            for f in frames:
                out += f.to_ndarray().tobytes()
            return out or None
        except Exception as e:
            logger.debug(f"Opus 解码失败: {e}")
            return None

    def encode(self, pcm_bytes: bytes) -> List[bytes]:
        """PCM bytes → 若干 Opus 包

        每次调用新建编码器：
          · 避免复用导致的状态污染（实测 flush 后再编码会 EOF）
          · TTS 输出是突发的，每次新建成本可忽略
        """
        import av
        import numpy as np

        encoder = av.CodecContext.create("libopus", "w")
        encoder.sample_rate = self.sample_rate
        encoder.format = "s16"
        encoder.layout = "mono" if self.channels == 1 else "stereo"
        encoder.bit_rate = 24000
        encoder.options = {
            "application": "voip",
            "frame_duration": str(FRAME_MS),
        }

        frame_len = int(self.sample_rate * FRAME_MS / 1000)
        packets: List[bytes] = []

        n_frames = len(pcm_bytes) // (frame_len * 2)
        for i in range(n_frames):
            chunk = pcm_bytes[i * frame_len * 2: (i + 1) * frame_len * 2]
            if len(chunk) != frame_len * 2:
                continue

            samples = np.frombuffer(chunk, dtype=np.int16).reshape(-1, self.channels)
            frame = av.AudioFrame.from_ndarray(samples.T, format="s16")
            frame.sample_rate = self.sample_rate

            for packet in encoder.encode(frame):
                packets.append(bytes(packet))

        # 冲刷（EOFError 表示没东西了，正常）
        try:
            for packet in encoder.encode(None):
                packets.append(bytes(packet))
        except Exception:
            pass

        return packets


# ══════════════════════════════════════════════════════════
#  能量 VAD（简单可靠）
# ══════════════════════════════════════════════════════════

@dataclass
class VADConfig:
    """能量 VAD 配置"""
    speech_threshold: float = 0.015      # 语音能量阈值（RMS 归一化）
    silence_frames: int = 15             # 静音帧数达到即判定句尾（15 × 20ms = 300ms）
    pre_speech_frames: int = 5           # 语音前保留的帧（不丢开头）
    max_utterance_ms: float = 8000.0     # 单句最长 8 秒，防止无限收集
    min_speech_ms: float = 200.0         # 最短语音（防噪声误触发）
    inter_frame_timeout_ms: float = 800.0  # 帧间静默超时：设备停发静音包也强制断句


class EnergyVAD:
    """能量 VAD — 检测一句完整的语音"""

    def __init__(self, config: Optional[VADConfig] = None):
        self.config = config or VADConfig()
        self._state = "silence"
        self._speech_frames: List[bytes] = []
        self._silence_count = 0
        self._pre_speech: List[bytes] = []
        self._utterance_start = 0.0
        self._last_energy = 0.0
        self._last_feed_at = 0.0

    def reset(self):
        """复位（新一句）"""
        self._state = "silence"
        self._speech_frames = []
        self._silence_count = 0
        self._pre_speech = []
        self._utterance_start = 0.0
        self._last_feed_at = 0.0

    def check_timeout(self) -> Optional[Tuple[str, Optional[bytes]]]:
        """看门狗调用：不依赖新帧，强制检查是否该断句

        设备可能彻底停发音频（静默/断流），这时只有
        外部定时器能触发 speech_end。

        Returns:
            有就返回 ("speech_end", utterance)，没有返回 None
        """
        if self._state != "speech" or not self._last_feed_at:
            return None

        return self._check_timeout(time.time())

    def _check_timeout(self, now: float) -> Optional[Tuple[str, Optional[bytes]]]:
        """检查是否需要断句（帧间超时 / 总时长超限）"""
        if self._state != "speech":
            return None

        # 帧间静默超时
        gap_ms = (now - self._last_feed_at) * 1000
        if gap_ms > self.config.inter_frame_timeout_ms:
            utterance = b"".join(self._speech_frames)
            min_len = (self.config.min_speech_ms / 1000) * FRAME_BYTES
            self.reset()
            if len(utterance) > min_len:
                return "speech_end", utterance
            return "silence", None

        # 总时长超限
        if (now - self._utterance_start) * 1000 > self.config.max_utterance_ms:
            utterance = b"".join(self._speech_frames)
            min_len = (self.config.min_speech_ms / 1000) * FRAME_BYTES
            self.reset()
            if len(utterance) > min_len:
                return "speech_end", utterance
            return "silence", None

        return None

    @staticmethod
    def energy(pcm: bytes) -> float:
        """计算 RMS 能量（归一化 0-1）"""
        if not pcm:
            return 0.0

        n = len(pcm) // 2
        if n == 0:
            return 0.0

        try:
            samples = struct.unpack(f"<{n}h", pcm[: n * 2])
            rms = math.sqrt(sum(s * s for s in samples) / n) / 32768.0
            return rms
        except Exception:
            return 0.0

    def feed(self, pcm: bytes) -> Tuple[str, Optional[bytes]]:
        """喂一帧 PCM

        Returns:
            (事件, 数据)
            ("speech_start", None)   — 检测到语音开始
            ("collecting", None)     — 收集中
            ("speech_end", pcm)      — 一句完整语音（可送去 ASR）
            ("silence", None)        — 静音
        """
        now = time.time()

        # 帧间静默超时：设备停发静音包时也强制断句
        result = self._check_timeout(now)
        if result:
            return result

        self._last_feed_at = now

        e = self.energy(pcm)
        now = time.time()

        if self._state == "silence":
            if e >= self.config.speech_threshold:
                # 语音开始
                self._state = "speech"
                self._speech_frames = list(self._pre_speech) + [pcm]
                self._silence_count = 0
                self._utterance_start = now
                self._last_energy = e
                return "speech_start", None
            else:
                # 保留预语音缓冲
                self._pre_speech.append(pcm)
                if len(self._pre_speech) > self.config.pre_speech_frames:
                    self._pre_speech.pop(0)
                return "silence", None

        else:  # speech
            self._speech_frames.append(pcm)
            self._last_energy = e

            # 超时强制断句
            if (now - self._utterance_start) * 1000 > self.config.max_utterance_ms:
                utterance = b"".join(self._speech_frames)
                if len(utterance) > (self.config.min_speech_ms / 1000) * FRAME_BYTES:
                    self.reset()
                    return "speech_end", utterance
                self.reset()
                return "silence", None

            # 静音计数
            if e < self.config.speech_threshold:
                self._silence_count += 1
                if self._silence_count >= self.config.silence_frames:
                    utterance = b"".join(self._speech_frames)
                    if len(utterance) > (self.config.min_speech_ms / 1000) * FRAME_BYTES:
                        self.reset()
                        return "speech_end", utterance
                    self.reset()
                    return "silence", None
            else:
                self._silence_count = 0

            return "collecting", None


# ══════════════════════════════════════════════════════════
#  ASR / TTS 提供方
# ══════════════════════════════════════════════════════════

@dataclass
class AudioConfig:
    """音频直连配置"""
    # ASR（OpenAI 兼容端点）
    asr_url: str = ""
    asr_key: str = ""
    asr_model: str = "whisper-1"
    asr_language: str = "zh"

    # TTS
    tts_provider: str = "edge"     # edge / openai / none
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+0%"

    # 服务器
    port: int = 8000
    host: str = "0.0.0.0"
    device_auth: str = ""          # 可选：接受的 device-id 白名单（空 = 都收）

    # 行为
    wake_words: List[str] = field(default_factory=list)   # 唤醒词（空 = 一直听）
    auto_hello: bool = True
    max_tts_chars: int = 200

    @classmethod
    def from_env(cls) -> "AudioConfig":
        """从环境变量读取"""
        return cls(
            asr_url=os.environ.get("LAAP_ASR_URL", ""),
            asr_key=os.environ.get("LAAP_ASR_KEY", ""),
            asr_model=os.environ.get("LAAP_ASR_MODEL", "whisper-1"),
            tts_provider=os.environ.get("LAAP_TTS_PROVIDER", "edge"),
            tts_voice=os.environ.get("LAAP_TTS_VOICE", "zh-CN-XiaoxiaoNeural"),
        )


class ASRClient:
    """语音识别（OpenAI 兼容端点）"""

    def __init__(self, config: AudioConfig):
        self.config = config

    @property
    def available(self) -> bool:
        return bool(self.config.asr_url)

    async def transcribe(self, pcm_bytes: bytes) -> str:
        """PCM → WAV → 转文字"""
        if not self.available:
            return ""

        try:
            import httpx
        except ImportError:
            return ""

        wav_bytes = self._pcm_to_wav(pcm_bytes)

        files = {
            "file": ("utterance.wav", wav_bytes, "audio/wav"),
            "model": (None, self.config.asr_model),
            "language": (None, self.config.asr_language),
        }
        headers = {}
        if self.config.asr_key:
            headers["Authorization"] = f"Bearer {self.config.asr_key}"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    self.config.asr_url, headers=headers, files=files
                )
                if resp.status_code != 200:
                    logger.error(f"ASR 失败 {resp.status_code}: {resp.text[:200]}")
                    return ""
                data = resp.json()
                return data.get("text", "").strip()
        except Exception as e:
            logger.error(f"ASR 异常: {e}")
            return ""

    def _pcm_to_wav(self, pcm: bytes) -> bytes:
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        return buf.getvalue()


class LocalWhisperASR:
    """本地语音识别（faster-whisper）— 完全离线

    需要：pip install faster-whisper
    首次运行会下载模型（tiny ~75MB / base ~145MB）。
    """

    def __init__(
        self,
        model_size: str = "tiny",
        language: str = "zh",
        device: str = "cpu",
        compute_type: str = "int8",
        vad_filter: bool = True,
    ):
        self.model_size = model_size
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self._model = None
        self.available = True

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type=self.compute_type
            )
        return self._model

    async def transcribe(self, pcm_bytes: bytes) -> str:
        """PCM → 文字（在 executor 里跑，不阻塞事件循环）"""
        import io
        import wave
        import tempfile
        from pathlib import Path

        # 写临时 WAV（faster-whisper 需要文件路径或可读对象）
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        try:
            with wave.open(tmp, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(pcm_bytes)

            loop = asyncio.get_event_loop()

            def _run():
                model = self._ensure_model()
                segments, info = model.transcribe(
                    tmp,
                    language=self.language,
                    vad_filter=self.vad_filter,
                    beam_size=1,
                )
                return "".join(s.text for s in segments).strip()

            return await loop.run_in_executor(None, _run)

        except Exception as e:
            logger.error(f"本地 ASR 失败: {e}")
            return ""
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass


class TTSClient:
    """文字转语音（edge-tts 默认，OpenAI 兼容可配）"""

    def __init__(self, config: AudioConfig):
        self.config = config

    @property
    def available(self) -> bool:
        return self.config.tts_provider != "none"

    async def synthesize(self, text: str) -> Optional[bytes]:
        """文字 → PCM bytes（16k 单声道）"""
        if not self.available or not text:
            return None

        if self.config.tts_provider == "edge":
            return await self._synthesize_edge(text)
        elif self.config.tts_provider == "openai":
            return await self._synthesize_openai(text)
        return None

    async def _synthesize_edge(self, text: str) -> Optional[bytes]:
        """edge-tts → mp3 → PCM"""
        try:
            import edge_tts
            import io

            communicate = edge_tts.Communicate(
                text,
                self.config.tts_voice,
                rate=self.config.tts_rate,
            )

            mp3_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_chunks.append(chunk["data"])

            if not mp3_chunks:
                return None

            mp3_bytes = b"".join(mp3_chunks)

            # MP3 → PCM（用 PyAV 解码）
            return self._mp3_to_pcm(mp3_bytes)

        except Exception as e:
            logger.error(f"edge-tts 失败: {e}")
            return None

    def _mp3_to_pcm(self, mp3_bytes: bytes) -> Optional[bytes]:
        """MP3 → 16k PCM"""
        try:
            import av

            codec = av.CodecContext.create("mp3", "r")
            packet = av.Packet(mp3_bytes)

            out = b""
            for frame in codec.decode(packet):
                # 重采样到 16k 单声道
                arr = frame.to_ndarray()
                out += arr.tobytes()

            # 重采样（edge-tts 默认 24kHz，需转 16k）
            return self._resample_to_16k(out, 24000)

        except Exception as e:
            logger.error(f"MP3 解码失败: {e}")
            return None

    def _resample_to_16k(self, pcm: bytes, src_rate: int) -> bytes:
        """线性重采样到 16k"""
        if src_rate == SAMPLE_RATE:
            return pcm

        try:
            import av
            import numpy as np

            resampler = av.AudioResampler(
                format="s16",
                layout="mono",
                rate=SAMPLE_RATE,
            )

            frame = av.AudioFrame.from_ndarray(
                np.frombuffer(pcm, dtype=np.int16).reshape(1, -1),
                format="s16",
                layout="mono",
            )
            frame.sample_rate = src_rate

            resampled = resampler.resample(frame)

            out = b""
            for f in resampled:
                out += f.to_ndarray().tobytes()
            return out

        except Exception as e:
            logger.error(f"重采样失败: {e}")
            # 退回近似（只处理 24k→16k 的 2/3 采样）
            ratio = src_rate / SAMPLE_RATE
            n = int(len(pcm) / 2 / ratio) * 2
            step = int(ratio)
            samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
            out = struct.pack(f"<{n//2}h", *samples[::step][: n // 2])
            return out

    async def _synthesize_openai(self, text: str) -> Optional[bytes]:
        try:
            import httpx

            url = self.config.asr_url.replace("/transcriptions", "/speech")
            headers = {
                "Authorization": f"Bearer {self.config.asr_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "tts-1",
                "input": text,
                "voice": "alloy",
                "format": "opus",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return self._opus_bytes_to_pcm(resp.content)
                return None
        except Exception as e:
            logger.error(f"OpenAI TTS 失败: {e}")
            return None

    def _opus_bytes_to_pcm(self, opus_bytes: bytes) -> bytes:
        """Ogg Opus → PCM（用 PyAV）"""
        try:
            import av

            # 包一层 Ogg 头？直接从裸 Opus 解
            codec = OpusCodec()
            return codec.decode(opus_bytes) or b""
        except Exception:
            return b""


# ══════════════════════════════════════════════════════════
#  音频流服务器
# ══════════════════════════════════════════════════════════

class XiaozhiAudioServer:
    """小智音频流服务器

    LAAP 扮演小智服务器：设备直连、音频本地进出。

    用法:
        server = XiaozhiAudioServer(brain=some_agent)
        await server.start()
    """

    def __init__(
        self,
        brain: Any = None,
        config: Optional[AudioConfig] = None,
        on_text: Optional[Callable] = None,       # 识别到文字时回调
        on_reply: Optional[Callable] = None,      # 生成回复时回调
    ):
        self.config = config or AudioConfig.from_env()
        self.brain = brain                        # 有 handle(text) 的对象
        self.on_text = on_text
        self.on_reply = on_reply

        self.codec = OpusCodec()
        self.vad = EnergyVAD()
        self.asr = ASRClient(self.config)
        self.tts = TTSClient(self.config)

        self._server = None
        self._clients: Dict[str, Dict] = {}
        self._running = False

        # 统计
        self.stats = {
            "connections": 0,
            "utterances": 0,
            "asr_success": 0,
            "asr_fail": 0,
            "tts_sent": 0,
            "audio_in_bytes": 0,
            "audio_out_bytes": 0,
            "errors": 0,
        }

    @property
    def running(self) -> bool:
        return self._running

    # ── 生命周期 ──────────────────────────────────

    async def start(self) -> Dict:
        """启动服务器"""
        try:
            import websockets
        except ImportError:
            return {"success": False, "error": "需要 websockets 库"}

        # 广播唤醒词（让设备开始听）
        async def handler(ws, path=None):
            await self._handle_client(ws)

        self._server = await websockets.serve(
            handler,
            self.config.host,
            self.config.port,
            max_size=16 * 1024 * 1024,
        )

        self._running = True

        return {
            "success": True,
            "url": f"ws://{self._local_ip()}:{self.config.port}",
            "port": self.config.port,
            "asr": self.asr.available,
            "tts": self.tts.available,
            "hint": (
                "设备固件里 WS 地址改成上面的 URL 即可直连"
            ),
        }

    async def stop(self):
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for cid in list(self._clients.keys()):
            try:
                await self._clients[cid]["ws"].close()
            except Exception:
                pass
        self._clients.clear()

    def _local_ip(self) -> str:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ── 客户端连接处理 ──────────────────────────────────

    async def _handle_client(self, ws):
        """处理一个设备连接"""
        client_id = f"dev_{uuid.uuid4().hex[:8]}"
        self.stats["connections"] += 1

        # 设备信息
        headers = dict(getattr(ws, "request", None).headers or {})
        device_id = headers.get("device-id", "")

        # 白名单检查
        if self.config.device_auth and device_id != self.config.device_auth:
            logger.warning(f"拒绝未知设备: {device_id}")
            await ws.close()
            return

        client = {
            "ws": ws,
            "device_id": device_id,
            "session_id": f"audio_{uuid.uuid4().hex[:10]}",
            "connected_at": time.time(),
            "listening": False,
            "pending_text": "",
        }

        self._clients[client_id] = client

        logger.info(
            f"设备连接: {client_id} device={device_id or '(未知)'}"
        )

        # VAD 看门狗：设备彻底静默时也能断句
        watchdog = asyncio.create_task(self._vad_watchdog(client))

        try:
            async for message in ws:
                if isinstance(message, str):
                    await self._handle_text(client, message)
                else:
                    await self._handle_audio(client, message)
        except Exception as e:
            logger.debug(f"设备连接异常: {e}")
            self.stats["errors"] += 1
        finally:
            watchdog.cancel()
            self._clients.pop(client_id, None)
            logger.info(f"设备断开: {client_id}")

    async def _vad_watchdog(self, client: Dict):
        """VAD 看门狗：周期性检查静默超时，强制断句"""
        while True:
            try:
                await asyncio.sleep(0.4)

                event, utterance = self.vad.check_timeout()
                if event == "speech_end" and utterance:
                    asyncio.create_task(
                        self._process_utterance(client, utterance)
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"VAD 看门狗异常: {e}")
                await asyncio.sleep(1)

    async def _handle_text(self, client: Dict, message: str):
        """处理设备发来的文本消息"""
        try:
            msg = json.loads(message)
        except Exception:
            return

        mtype = msg.get("type", "")

        if mtype == "hello":
            # 握手：回应 welcome
            await self._send_hello_response(client, msg)

        elif mtype == "listen":
            state = msg.get("state", "")
            client["listening"] = state in ("detect", "wakeup", "listen")
            logger.debug(f"设备状态: {state}")

        elif mtype == "iot":
            # IoT 消息（按键等）
            logger.debug(f"IoT: {msg}")

        elif mtype == "abort":
            # 设备打断 TTS
            self.vad.reset()

        else:
            logger.debug(f"未知文本消息: {msg}")

    async def _send_hello_response(self, client: Dict, hello: Dict):
        """回应 hello"""
        audio_params = hello.get("audio_params", {})
        if audio_params:
            audio_params["format"] = "opus"
            audio_params["sample_rate"] = SAMPLE_RATE

        welcome = {
            "type": "hello",
            "session_id": client["session_id"],
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
            },
            "version": 2,
        }

        await client["ws"].send(json.dumps(welcome))

        # 问候语
        if self.config.auto_hello:
            await asyncio.sleep(0.2)
            await self._send_tts(
                client, "你好，我是 LAAP，我已经准备好听你说话了。"
            )

    async def _handle_audio(self, client: Dict, data: bytes):
        """处理 Opus 音频包

        关键：speech_end 后用 create_task 异步处理，
        否则 await ASR 期间会阻塞音频接收循环，后续语音全丢。
        """
        self.stats["audio_in_bytes"] += len(data)

        # 解码
        pcm = self.codec.decode(data)
        if not pcm:
            return

        # VAD
        event, utterance = self.vad.feed(pcm)

        if event == "speech_end" and utterance:
            # 异步处理，不阻塞接收循环
            asyncio.create_task(self._process_utterance(client, utterance))

    # ── 一句话处理（ASR → 大脑 → TTS）─────────────────────────────────

    async def _process_utterance(self, client: Dict, pcm: bytes):
        """处理一句完整语音"""
        self.stats["utterances"] += 1

        # 1. ASR
        if not self.asr.available:
            await self._send_tts(client, "语音识别没配置，我听到声音但听不懂。")
            return

        text = await self.asr.transcribe(pcm)

        if not text:
            self.stats["asr_fail"] += 1
            return

        self.stats["asr_success"] += 1

        logger.info(f"[设备 {client['device_id']}] 听: {text}")

        if self.on_text:
            try:
                await self.on_text(text, client["device_id"])
            except Exception:
                pass

        # 唤醒词过滤（如果配置了）
        if self.config.wake_words:
            if not any(w in text for w in self.config.wake_words):
                logger.debug(f"未命中唤醒词: {text}")
                return

        # 2. 大脑处理
        reply_text = await self._brain_handle(text)

        if not reply_text:
            reply_text = "我在，你说什么？"

        # 3. 回 TTS
        await self._send_tts(client, reply_text, stt_text=text)

    async def _brain_handle(self, text: str) -> str:
        """交给大脑（VoiceComputerAgent / MultiStep / LLM）"""
        if self.brain is None:
            return ""

        # 统一接口：brain.handle(text) 或 brain(text)
        handle = getattr(self.brain, "handle", None)

        if handle:
            if asyncio.iscoroutinefunction(handle):
                result = await handle(text)
            else:
                result = handle(text)

            # VoiceActionResult 或字符串
            if isinstance(result, str):
                return result
            if hasattr(result, "reply"):
                return result.reply
            return str(result)

        # 可调用对象
        if callable(self.brain):
            result = self.brain(text)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, str):
                return result
            if hasattr(result, "reply"):
                return result.reply
            return str(result)

        return ""

    # ── 发送 TTS ──────────────────────────────────

    async def _send_tts(
        self,
        client: Dict,
        text: str,
        stt_text: str = "",
    ):
        """合成并发送 TTS（文本 + Opus 音频）"""
        text = text.strip()[: self.config.max_tts_chars]
        if not text:
            return

        if stt_text and self.on_reply:
            try:
                await self.on_reply(text, stt_text)
            except Exception:
                pass

        # 1. 先发文本（设备用它显示/判断）
        tts_msg = {
            "type": "tts",
            "text": text,
            "session_id": client["session_id"],
        }
        await client["ws"].send(json.dumps(tts_msg))

        # 2. 合成音频
        pcm = await self.tts.synthesize(text)

        if not pcm:
            logger.warning(f"TTS 合成失败: {text[:30]}")
            return

        # 3. Opus 编码并发送
        packets = self.codec.encode(pcm)

        for pkt in packets:
            await client["ws"].send(pkt)
            self.stats["audio_out_bytes"] += len(pkt)

        self.stats["tts_sent"] += 1

        # 4. 结束标记
        end_msg = {
            "type": "tts",
            "text": text,
            "session_id": client["session_id"],
            "state": "stop",
        }
        await client["ws"].send(json.dumps(end_msg))

        logger.info(f"[设备 {client['device_id']}] 说: {text[:40]}")

    # ── 状态 ──────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "clients": {
                cid: {
                    "device_id": c["device_id"],
                    "session": c["session_id"],
                    "listening": c["listening"],
                }
                for cid, c in self._clients.items()
            },
            "asr": self.asr.available,
            "tts": self.tts.available,
            "voice": self.config.tts_voice,
            "port": self.config.port,
            "stats": self.stats,
        }

    async def broadcast_tts(self, text: str):
        """向所有设备广播一句话"""
        for cid in list(self._clients.keys()):
            await self._send_tts(self._clients[cid], text)


# ══════════════════════════════════════════════════════════
#  Opus 回环自测
# ══════════════════════════════════════════════════════════

def opus_roundtrip_test() -> Dict:
    """自测：PCM → Opus → PCM 能不能回环"""
    import numpy as np

    # 1 秒正弦波
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    pcm = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)
    pcm_bytes = pcm.tobytes()

    codec = OpusCodec()
    packets = codec.encode(pcm_bytes)

    decoded = b""
    for pkt in packets:
        d = codec.decode(pkt)
        if d:
            decoded += d

    return {
        "input_bytes": len(pcm_bytes),
        "opus_packets": len(packets),
        "decoded_bytes": len(decoded),
        "lossless_ratio": round(len(decoded) / max(1, len(pcm_bytes)), 3),
        "ok": len(decoded) > len(pcm_bytes) * 0.8,
    }


def get_audio_status() -> Dict:
    """音频直连环境状态"""
    deps = {}
    for m in ("av", "edge_tts", "numpy"):
        try:
            __import__(m)
            deps[m] = True
        except ImportError:
            deps[m] = False

    try:
        rt = opus_roundtrip_test()
    except Exception as e:
        rt = {"ok": False, "error": str(e)}

    return {
        "dependencies": deps,
        "opus_roundtrip": rt,
        "asr_configured": bool(
            os.environ.get("LAAP_ASR_URL") or os.environ.get("LAAP_ASR_KEY")
        ),
        "tts_provider": os.environ.get("LAAP_TTS_PROVIDER", "edge"),
        "ready": all(deps.values()) and rt.get("ok", False),
        "hint": (
            "音频直连就绪"
            if all(deps.values())
            else "缺少依赖: " + ", ".join(k for k, v in deps.items() if not v)
        ),
    }