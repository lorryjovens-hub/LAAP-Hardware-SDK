"""LAAP Neural Field Protocol — 神经场协议 (V0.3)

大胆创新：设备之间不是点对点消息，是共享感知场。

核心思想：
1. 每个设备都有一个"感知场"（Neural Field），向所有设备广播
2. 事件像涟漪扩散，设备可以"感知"到远处的活动
3. 认知融合：多个设备的感知可以融合成更高级的理解
4. 预测场：基于历史模式预测未来的事件

这不是消息总线，是一个共享的"意识空间"。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum

logger = logging.getLogger("laap_hardware.neural_field")


class FieldEventType(str, Enum):
    """场事件类型"""
    PERCEPTION = "perception"      # 感知事件
    ACTION = "action"              # 行动事件
    EMOTION = "emotion"            # 情绪事件
    COGNITION = "cognition"        # 认知事件
    PREDICTION = "prediction"      # 预测事件
    EMERGENCE = "emergence"        # 涌现事件


@dataclass
class FieldEvent:
    """场事件"""
    event_id: str
    event_type: FieldEventType
    source_device: str
    timestamp: float
    data: Dict[str, Any]
    intensity: float = 1.0  # 场强 0-1
    propagation_speed: float = 1.0  # 扩散速度
    ttl: float = 3600.0  # 生存时间（秒）
    tags: List[str] = field(default_factory=list)


@dataclass
class NeuralField:
    """神经场 — 设备的感知空间"""
    device_id: str
    field_radius: float = 100.0  # 感知半径
    sensitivity: float = 0.5  # 敏感度
    active_events: List[FieldEvent] = field(default_factory=list)
    history: List[FieldEvent] = field(default_factory=list)

    def emit(self, event: FieldEvent):
        """发射事件到场上"""
        self.active_events.append(event)
        self.history.append(event)
        # 保持历史长度
        if len(self.history) > 1000:
            self.history = self.history[-500:]

    def perceive(self, event: FieldEvent) -> float:
        """感知到的事件强度（根据距离/时间衰减）"""
        if event.source_device == self.device_id:
            return 0.0  # 自己的事件

        # 时间衰减
        age = time.time() - event.timestamp
        time_decay = math.exp(-age / 3600)  # 1小时衰减到 37%

        # 强度衰减
        return event.intensity * time_decay * self.sensitivity


class NeuralFieldProtocol:
    """神经场协议

    管理多个设备的神经场，实现共享感知。

    用法：
        protocol = NeuralFieldProtocol()
        protocol.register_device("device-1")
        protocol.register_device("device-2")

        # 设备发射事件
        protocol.emit_event("device-1", FieldEventType.PERCEPTION, {"temp": 22})

        # 所有设备都能感知到
        events = protocol.perceive_field("device-2")
    """

    def __init__(self):
        self._fields: Dict[str, NeuralField] = {}
        self._global_history: List[FieldEvent] = []
        self._event_counter = 0
        self._subscriptions: Dict[str, Set[FieldEventType]] = {}

    def register_device(self, device_id: str,
                       field_radius: float = 100.0,
                       sensitivity: float = 0.5):
        """注册设备到神经场"""
        self._fields[device_id] = NeuralField(
            device_id=device_id,
            field_radius=field_radius,
            sensitivity=sensitivity,
        )
        logger.info(f"Device {device_id} joined neural field")

    def emit_event(self, source_device: str,
                   event_type: FieldEventType,
                   data: Dict[str, Any],
                   intensity: float = 1.0,
                   tags: Optional[List[str]] = None) -> FieldEvent:
        """发射事件到神经场"""
        self._event_counter += 1
        event = FieldEvent(
            event_id=f"evt_{self._event_counter}",
            event_type=event_type,
            source_device=source_device,
            timestamp=time.time(),
            data=data,
            intensity=intensity,
            tags=tags or [],
        )

        # 添加到所有设备的场
        for field in self._fields.values():
            field.emit(event)

        self._global_history.append(event)
        if len(self._global_history) > 5000:
            self._global_history = self._global_history[-2500:]

        logger.debug(f"Event emitted: {event.event_id} from {source_device}")
        return event

    def perceive_field(self, device_id: str,
                       event_types: Optional[Set[FieldEventType]] = None,
                       min_intensity: float = 0.1,
                       max_age: float = 3600) -> List[Dict]:
        """设备感知神经场"""
        field = self._fields.get(device_id)
        if not field:
            return []

        perceived = []
        for event in field.active_events:
            # 过滤类型
            if event_types and event.event_type not in event_types:
                continue

            # 计算感知强度
            intensity = field.perceive(event)
            if intensity < min_intensity:
                continue

            # 过滤时间
            if time.time() - event.timestamp > max_age:
                continue

            perceived.append({
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "source_device": event.source_device,
                "data": event.data,
                "intensity": round(intensity, 3),
                "age_seconds": round(time.time() - event.timestamp, 1),
                "tags": event.tags,
            })

        # 按强度排序
        perceived.sort(key=lambda x: x["intensity"], reverse=True)
        return perceived

    def fuse_cognition(self, device_ids: List[str],
                       event_type: FieldEventType) -> Dict:
        """认知融合：综合多个设备的感知"""
        all_perceptions = []
        for device_id in device_ids:
            events = self.perceive_field(device_id, {event_type})
            all_perceptions.extend(events)

        if not all_perceptions:
            return {"fused": False, "reason": "no perceptions"}

        # 计算加权平均
        total_weight = sum(p["intensity"] for p in all_perceptions)
        if total_weight == 0:
            return {"fused": False, "reason": "zero intensity"}

        # 融合数据
        fused_data = {}
        for p in all_perceptions:
            weight = p["intensity"] / total_weight
            for key, value in p["data"].items():
                if key not in fused_data:
                    fused_data[key] = 0
                if isinstance(value, (int, float)):
                    fused_data[key] += value * weight

        return {
            "fused": True,
            "event_type": event_type.value,
            "source_devices": device_ids,
            "fused_data": fused_data,
            "confidence": round(min(1.0, total_weight), 2),
            "perception_count": len(all_perceptions),
        }

    def predict_next(self, device_id: str,
                    event_type: FieldEventType,
                    horizon_seconds: float = 300) -> Dict:
        """预测场中下一个事件"""
        events = self.perceive_field(device_id, {event_type})

        if len(events) < 3:
            return {"predicted": False, "reason": "insufficient data"}

        # 计算事件间隔
        timestamps = [e["age_seconds"] for e in events[:10]]
        intervals = [timestamps[i] - timestamps[i+1] for i in range(len(timestamps)-1)]
        avg_interval = sum(intervals) / len(intervals) if intervals else 300

        # 预测下次事件时间
        predicted_time = time.time() + avg_interval

        return {
            "predicted": True,
            "event_type": event_type.value,
            "predicted_in_seconds": round(avg_interval, 1),
            "predicted_at": predicted_time,
            "confidence": round(min(1.0, len(events) / 10), 2),
            "based_on_events": len(events),
        }

    def get_field_state(self) -> Dict:
        """获取神经场全局状态"""
        return {
            "total_devices": len(self._fields),
            "total_events": len(self._global_history),
            "active_fields": [
                {
                    "device_id": f.device_id,
                    "active_events": len(f.active_events),
                    "history_size": len(f.history),
                }
                for f in self._fields.values()
            ],
            "recent_events": [
                {
                    "id": e.event_id,
                    "type": e.event_type.value,
                    "source": e.source_device,
                    "age": round(time.time() - e.timestamp, 1),
                }
                for e in self._global_history[-10:]
            ],
        }