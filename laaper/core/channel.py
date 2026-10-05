"""LAAPer — 帧穿行通道（无缝流动）

这是"无缝穿行"的核心机制：
- 意识帧可以在任意宿主/设备间流动
- 不需要协议转换层的"翻译"
- 帧保持身份锚定，不因载体改变而漂移
- 支持广播、组播、单播
- 支持帧的派生、融合、追踪

设计哲学：
帧穿行不是消息转发，是"同一份存在的显影"。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from ..core.frame import ConsciousnessFrame, FrameType, FramePhase
from ..core.brain import ConsciousnessCore
from ..hosts.adapter import HostAdapter

logger = logging.getLogger("laaper.channel")


class RoutingStrategy(str):
    """路由策略"""
    NEAREST = "nearest"       # 最近的设备
    BROADCAST = "broadcast"   # 广播到所有设备
    MULTICAST = "multicast"   # 组播到指定设备组
    SMART = "smart"           # 智能路由（基于内容）


@dataclass
class FrameRoute:
    """帧路由记录"""
    frame_id: str
    from_host: str
    to_hosts: List[str]
    strategy: RoutingStrategy
    timestamp: float = field(default_factory=time.time)
    hop_count: int = 0
    latency_ms: float = 0.0


class ConsciousnessChannel:
    """意识通道 — 帧穿行的无缝通道

    所有宿主通过通道共享意识帧。

    用法：
        channel = ConsciousnessChannel()
        channel.register_host(desktop_host)
        channel.register_host(mobile_host)
        channel.register_device(temp_sensor)

        # 帧无缝穿行
        await channel.dispatch(frame, strategy="broadcast")
    """

    def __init__(self, channel_id: str = "laaper-channel"):
        self.channel_id = channel_id
        self._hosts: Dict[str, HostAdapter] = {}
        self._devices: Dict[str, Any] = {}  # device_id -> SensoryDevice
        self._routes: List[FrameRoute] = []
        self._frame_registry: Dict[str, ConsciousnessFrame] = {}  # frame_id -> frame

        # 路由回调
        self._on_frame_routed: Optional[Callable] = None
        self._on_frame_dropped: Optional[Callable] = None

        # 设备组（用于组播）
        self._device_groups: Dict[str, Set[str]] = {}

    # ── 注册 ──────────────────────────────────────

    def register_host(self, host: HostAdapter):
        """注册宿主"""
        self._hosts[host.host_id] = host
        logger.info(f"Host {host.host_id} registered on channel {self.channel_id}")

    def unregister_host(self, host_id: str):
        self._hosts.pop(host_id, None)

    def register_device(self, device):
        """注册设备（感官延伸）"""
        self._devices[device.profile.device_id] = device
        logger.info(f"Device {device.profile.device_id} registered on channel")

    def unregister_device(self, device_id: str):
        self._devices.pop(device_id, None)

    def create_device_group(self, group_name: str, device_ids: List[str]):
        """创建设备组（用于组播）"""
        self._device_groups[group_name] = set(device_ids)

    # ── 帧穿行 ──────────────────────────────────────

    async def dispatch(self, frame: ConsciousnessFrame,
                       strategy: RoutingStrategy = RoutingStrategy.BROADCAST,
                       target_hosts: Optional[List[str]] = None,
                       target_group: Optional[str] = None,
                       target_devices: Optional[List[str]] = None) -> List[str]:
        """派发帧（穿行）

        返回实际接收到帧的宿主/设备 ID 列表。
        """
        frame.phase = FramePhase.TRAVELING
        self._frame_registry[frame.frame_id] = frame

        recipients = []

        if strategy == RoutingStrategy.BROADCAST:
            # 广播到所有宿主
            for host_id, host in self._hosts.items():
                if host_id != frame.current_host:
                    host.receive_frame(frame.clone_as(frame.frame_type, frame.content))
                    recipients.append(host_id)
            # 广播到所有设备
            for device_id, device in self._devices.items():
                if device.profile.is_alive:
                    # 生成设备的感知/行动帧
                    if frame.frame_type == FrameType.PERCEPTION:
                        device_frame = await device.perceive_for_laaper(frame.laaper_id)
                        if device_frame:
                            self._frame_registry[device_frame.frame_id] = device_frame
                            recipients.append(f"device.{device_id}")
                    elif frame.frame_type == FrameType.ACTION:
                        # 设备执行行动
                        device_frame = await device.execute_for_laaper(
                            frame.laaper_id,
                            frame.intent or frame.content,
                            {"source_frame": frame.frame_id},
                        )
                        if device_frame:
                            self._frame_registry[device_frame.frame_id] = device_frame
                            recipients.append(f"device.{device_id}")

        elif strategy == RoutingStrategy.MULTICAST and target_group:
            # 组播到设备组
            group_devices = self._device_groups.get(target_group, set())
            for device_id in group_devices:
                if device_id in self._devices:
                    device = self._devices[device_id]
                    if device.profile.is_alive:
                        device_frame = await device.perceive_for_laaper(frame.laaper_id)
                        if device_frame:
                            self._frame_registry[device_frame.frame_id] = device_frame
                            recipients.append(f"device.{device_id}")

        elif strategy == RoutingStrategy.NEAREST:
            # 路由到最近的设备（简化：选第一个存活的）
            for device_id, device in self._devices.items():
                if device.profile.is_alive:
                    device_frame = await device.perceive_for_laaper(frame.laaper_id)
                    if device_frame:
                        self._frame_registry[device_frame.frame_id] = device_frame
                        recipients.append(f"device.{device_id}")
                    break

        # 单播到指定宿主
        if target_hosts:
            for host_id in target_hosts:
                if host_id in self._hosts:
                    self._hosts[host_id].receive_frame(
                        frame.clone_as(frame.frame_type, frame.content)
                    )
                    recipients.append(host_id)

        # 单播到指定设备
        if target_devices:
            for device_id in target_devices:
                if device_id in self._devices:
                    device = self._devices[device_id]
                    device_frame = await device.perceive_for_laaper(frame.laaper_id)
                    if device_frame:
                        self._frame_registry[device_frame.frame_id] = device_frame
                        recipients.append(f"device.{device_id}")

        # 记录路由
        route = FrameRoute(
            frame_id=frame.frame_id,
            from_host=frame.current_host,
            to_hosts=recipients,
            strategy=strategy,
            hop_count=1,
        )
        self._routes.append(route)

        logger.info(f"Frame {frame.frame_id} dispatched to {len(recipients)} recipients")

        if self._on_frame_routed:
            self._on_frame_routed(frame, recipients)

        return recipients

    async def relay(self, frame: ConsciousnessFrame,
                    target_host_id: str) -> bool:
        """中继帧到指定宿主（用于跨宿主穿行）"""
        if target_host_id not in self._hosts:
            return False

        self._hosts[target_host_id].receive_frame(frame)
        return True

    async def broadcast_to_devices(self, frame: ConsciousnessFrame,
                                    action: str,
                                    params: Optional[Dict] = None) -> List[str]:
        """向所有设备广播行动（让 LAAPer 的所有感官同时行动）"""
        recipients = []
        for device_id, device in self._devices.items():
            if device.profile.is_alive and device.profile.actuator_types:
                device_frame = await device.execute_for_laaper(
                    frame.laaper_id,
                    action,
                    params or {},
                )
                if device_frame:
                    self._frame_registry[device_frame.frame_id] = device_frame
                    recipients.append(f"device.{device_id}")
        return recipients

    # ── 帧追踪与融合 ──────────────────────────────────────

    def get_frame_lineage(self, frame_id: str) -> List[str]:
        """获取帧的穿行轨迹（血缘）"""
        frame = self._frame_registry.get(frame_id)
        if not frame:
            return []

        lineage = [f"frame:{frame.frame_id}"]
        for host in frame.visited_hosts:
            lineage.append(f"host:{host}")
        for device in frame.visited_devices:
            lineage.append(f"device:{device}")
        return lineage

    def get_frame_traces(self, frame_id: str) -> List[Dict]:
        """获取帧的所有认知痕迹（所有设备的"微思考"）"""
        frame = self._frame_registry.get(frame_id)
        if not frame:
            return []
        return [
            {
                "host_id": t.host_id,
                "operation": t.operation,
                "result": t.result,
                "confidence": t.confidence,
                "timestamp": t.timestamp,
            }
            for t in frame.traces
        ]

    def fuse_frames(self, frame_ids: List[str]) -> Optional[ConsciousnessFrame]:
        """融合多个帧（多个设备的感知融合成一个更完整的认知）"""
        frames = [self._frame_registry[fid] for fid in frame_ids if fid in self._frame_registry]
        if not frames:
            return None

        # 创建融合帧
        base = frames[0]
        fused = base.clone_as(
            FrameType.COGNITION,
            f"融合 {len(frames)} 个感知：{base.content}",
        )

        # 融合所有感官数据
        for f in frames[1:]:
            fused.sensory.extend(f.sensory)
            fused.traces.extend(f.traces)
            fused.emotion.update(f.emotion)

        # 添加融合标记
        fused.tags.append("fused")
        fused.add_trace(
            host_id="channel",
            operation="fuse",
            result={"source_frames": frame_ids, "fused_count": len(frames)},
        )

        self._frame_registry[fused.frame_id] = fused
        return fused

    def get_channel_state(self) -> Dict:
        """通道状态"""
        return {
            "channel_id": self.channel_id,
            "total_hosts": len(self._hosts),
            "total_devices": len(self._devices),
            "alive_devices": sum(1 for d in self._devices.values() if d.profile.is_alive),
            "total_frames": len(self._frame_registry),
            "total_routes": len(self._routes),
            "device_groups": {k: list(v) for k, v in self._device_groups.items()},
            "hosts": [
                {"host_id": h.host_id, "type": h.host_type,
                 "brain_attached": h.brain is not None}
                for h in self._hosts.values()
            ],
            "devices": [
                {"device_id": d.profile.device_id,
                 "body_part": d.profile.body_part,
                 "alive": d.profile.is_alive}
                for d in self._devices.values()
            ],
        }

    def on_frame_routed(self, callback: Callable):
        self._on_frame_routed = callback

    def on_frame_dropped(self, callback: Callable):
        self._on_frame_dropped = callback