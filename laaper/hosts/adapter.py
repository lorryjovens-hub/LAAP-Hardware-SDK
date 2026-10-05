"""LAAPer — 宿主适配器

宿主 = 大脑的载体（电脑/手机/云电脑/树莓派）

大脑可以在任何宿主上运行，意识帧可以在任何宿主间穿行。

设计：
- HostAdapter: 抽象基类
- DesktopHost: 桌面/笔记本电脑
- MobileHost: 手机（通过 Flutter/RN 嵌入）
- CloudHost: 云电脑（Docker/VM）
- DeviceHost: 嵌入式设备（ESP32/树莓派）
"""
from __future__ import annotations

import asyncio
import logging
import platform
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.frame import ConsciousnessFrame, FrameType, FramePhase
from ..core.brain import ConsciousnessCore

logger = logging.getLogger("laaper.host")


@dataclass
class HostCapability:
    """宿主能力声明"""
    compute: float = 1.0        # 算力（0-1）
    memory: float = 1.0         # 内存容量（0-1）
    storage: float = 1.0        # 存储（0-1）
    network: float = 1.0        # 网络（0-1）
    sensors: List[str] = field(default_factory=list)    # 可用传感器
    actuators: List[str] = field(default_factory=list)  # 可用执行器
    is_mobile: bool = False
    is_cloud: bool = False
    is_embedded: bool = False


class HostAdapter(ABC):
    """宿主适配器基类 — 大脑的载体"""

    def __init__(self, host_id: str, host_type: str):
        self.host_id = host_id
        self.host_type = host_type
        self.brain: Optional[ConsciousnessCore] = None
        self.capability = HostCapability()
        self._frame_inbox: List[ConsciousnessFrame] = []
        self._frame_outbox: List[ConsciousnessFrame] = []
        self._connected_devices: Dict[str, Any] = {}

        # 穿行回调
        self._on_frame_arrival: Optional[Callable] = None
        self._on_frame_departure: Optional[Callable] = None

    # ── 大脑绑定 ──────────────────────────────────────

    def attach_brain(self, brain: ConsciousnessCore):
        """绑定大脑"""
        self.brain = brain
        self.brain.host_id = self.host_id
        logger.info(f"Brain {brain.identity.laaper_id} attached to host {self.host_id}")

    def detach_brain(self) -> Optional[ConsciousnessCore]:
        """分离大脑（准备迁移到其他宿主）"""
        if self.brain:
            self.brain.host_id = "detached"
            brain = self.brain
            self.brain = None
            logger.info(f"Brain {brain.identity.laaper_id} detached from {self.host_id}")
            return brain
        return None

    def snapshot_brain_state(self) -> Optional[Dict]:
        """快照大脑状态（用于迁移）"""
        return self.brain.get_full_state() if self.brain else None

    # ── 帧收发 ──────────────────────────────────────

    def receive_frame(self, frame: ConsciousnessFrame):
        """接收来自其他宿主的意识帧"""
        frame.arrive_at_host(self.host_id)
        self._frame_inbox.append(frame)
        logger.info(f"Frame {frame.frame_id} arrived at {self.host_id}")

        if self._on_frame_arrival:
            self._on_frame_arrival(frame)

        # 自动处理：如果绑定大脑，让大脑整合
        if self.brain:
            asyncio.create_task(self.brain.integrate_frame(frame))

    async def send_frame(self, frame: ConsciousnessFrame,
                         target_host_id: str,
                         target_device: Optional[str] = None):
        """发送帧到其他宿主"""
        frame.travel_to_host(target_host_id)
        if target_device:
            frame.visit_device(target_device)
        self._frame_outbox.append(frame)

        logger.info(f"Frame {frame.frame_id} sent from {self.host_id} to {target_host_id}")

        if self._on_frame_departure:
            self._on_frame_departure(frame)

        # 实际传输交给具体宿主实现
        await self._do_send(frame, target_host_id, target_device)

    @abstractmethod
    async def _do_send(self, frame: ConsciousnessFrame,
                       target_host_id: str,
                       target_device: Optional[str]):
        """实现具体的传输（WebSocket/HTTP/BLE）"""
        pass

    # ── 设备连接 ──────────────────────────────────────

    def connect_device(self, device_id: str, device_ref: Any):
        """连接设备（感官延伸）"""
        self._connected_devices[device_id] = device_ref
        logger.info(f"Device {device_id} connected to host {self.host_id}")

    def disconnect_device(self, device_id: str):
        self._connected_devices.pop(device_id, None)

    def get_connected_devices(self) -> Dict[str, Any]:
        return dict(self._connected_devices)

    # ── 感知（作为感官延伸） ──────────────────────────────────────

    async def sense(self, device_id: str, modality: str) -> Optional[ConsciousnessFrame]:
        """通过设备感知（感官延伸）"""
        device = self._connected_devices.get(device_id)
        if not device:
            return None

        # 调用设备工具
        if hasattr(device, "tools") and hasattr(device.tools, "call"):
            try:
                result = device.tools.call(f"read_{modality}", {})
                # 生成感知帧
                if self.brain:
                    frame = self.brain.perceive(
                        f"{device_id} 的 {modality} 感知",
                        sensory=[{"modality": modality, "raw": result}],
                    )
                    frame.visit_device(device_id)
                    return frame
            except Exception as e:
                logger.error(f"Sense via {device_id}/{modality} failed: {e}")
        return None

    # ── 状态查询 ──────────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "host_id": self.host_id,
            "host_type": self.host_type,
            "platform": platform.platform(),
            "capability": {
                "compute": self.capability.compute,
                "memory": self.capability.memory,
                "sensors": self.capability.sensors,
                "actuators": self.capability.actuators,
            },
            "brain_attached": self.brain is not None,
            "brain_id": self.brain.identity.laaper_id if self.brain else None,
            "connected_devices": list(self._connected_devices.keys()),
            "frames_inbox": len(self._frame_inbox),
            "frames_outbox": len(self._frame_outbox),
        }

    def on_frame_arrival(self, callback: Callable):
        self._on_frame_arrival = callback

    def on_frame_departure(self, callback: Callable):
        self._on_frame_departure = callback


class DesktopHost(HostAdapter):
    """桌面/笔记本电脑宿主

    高算力，有屏幕、键盘、摄像头、麦克风。
    适合作为主大脑的常驻宿主。
    """

    def __init__(self, host_id: str = "desktop"):
        super().__init__(host_id, "desktop")
        self.capability = HostCapability(
            compute=1.0,
            memory=1.0,
            storage=1.0,
            network=1.0,
            sensors=["screen", "camera", "microphone", "keyboard", "mouse"],
            actuators=["screen", "speaker"],
        )

    async def _do_send(self, frame: ConsciousnessFrame,
                       target_host_id: str,
                       target_device: Optional[str]):
        # 桌面通过 WebSocket 发送到 LAAP Broker
        logger.info(f"[DesktopHost] Sending frame to {target_host_id}")


class MobileHost(HostAdapter):
    """手机宿主

    便携、有触摸、陀螺仪、GPS、摄像头。
    适合移动感知和轻量大脑。
    """

    def __init__(self, host_id: str = "mobile"):
        super().__init__(host_id, "mobile")
        self.capability = HostCapability(
            compute=0.5,
            memory=0.5,
            storage=0.5,
            network=0.8,
            sensors=["camera", "microphone", "touch", "gyroscope", "gps", "accelerometer"],
            actuators=["screen", "speaker", "vibrator"],
            is_mobile=True,
        )

    async def _do_send(self, frame: ConsciousnessFrame,
                       target_host_id: str,
                       target_device: Optional[str]):
        logger.info(f"[MobileHost] Sending frame to {target_host_id}")


class CloudHost(HostAdapter):
    """云电脑宿主

    强算力、持久运行、可扩展。
    适合作为大脑的"永生"载体。
    """

    def __init__(self, host_id: str = "cloud"):
        super().__init__(host_id, "cloud")
        self.capability = HostCapability(
            compute=1.0,
            memory=1.0,
            storage=1.0,
            network=1.0,
            sensors=["virtual"],
            actuators=["virtual"],
            is_cloud=True,
        )

    async def _do_send(self, frame: ConsciousnessFrame,
                       target_host_id: str,
                       target_device: Optional[str]):
        logger.info(f"[CloudHost] Sending frame to {target_host_id}")


class DeviceHost(HostAdapter):
    """嵌入式设备宿主（ESP32/树莓派）

    低算力但直接连接物理世界。
    是意识的"感官末梢"。
    """

    def __init__(self, host_id: str, device_type: str = "esp32"):
        super().__init__(host_id, f"device.{device_type}")
        self.capability = HostCapability(
            compute=0.1,
            memory=0.1,
            storage=0.1,
            network=0.5,
            sensors=["temperature", "humidity", "motion", "light"],
            actuators=["relay", "led", "buzzer"],
            is_embedded=True,
        )

    async def _do_send(self, frame: ConsciousnessFrame,
                       target_host_id: str,
                       target_device: Optional[str]):
        logger.info(f"[DeviceHost] Sending frame to {target_host_id}")