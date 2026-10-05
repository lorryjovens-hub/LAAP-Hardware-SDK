"""LAAP-EB 感知融合 (LAAP-EB Perception Bridge)

把 LAAPer 的感知系统接入 LAAP-EB（具身大脑）。

LAAP-EB 有：
- perception_base.py — 感知基类
- actuation.py — 执行
- MuJoCo 仿真 — 物理世界

LAAPer 有：
- 感官编码器 — 物理量→体验质
- 跨模态融合 — 多感官→统一认知
- 意识流帧 — 统一存在单位

这个模块是两者的桥梁。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.frame import ConsciousnessFrame, FrameType, SensoryData
from ..perception.encoder import SensoryEncoder, Qualia, QualiaType, SensoryModality
from ..perception.fusion import CrossModalFusion, FusedPerception

logger = logging.getLogger("laaper.eb_bridge")


@dataclass
class EBPerception:
    """LAAP-EB 感知数据"""
    sensor_type: str
    raw_value: Any
    timestamp: float
    body_part: str = ""

    # EB 特有
    mujoco_id: Optional[int] = None  # MuJoCo 对象 ID
    joint_id: Optional[int] = None   # 关节 ID
    actuator_id: Optional[int] = None  # 执行器 ID


class EBBridge:
    """LAAP-EB 感知桥

    连接 LAAPer 的感知系统和 LAAP-EB 的具身智能。

    用法：
        bridge = EBBridge(laaper_id="aris")

        # EB 传来感知
        bridge.receive_eb_perception("temperature", 22.5, body_part="skin")

        # 转换成 LAAPer 意识帧
        frame = bridge.to_consciousness_frame()

        # LAAPer 决策后，发给 EB
        action = bridge.to_eb_action("turn_on", {"actuator": "fan"})
    """

    def __init__(self, laaper_id: str = ""):
        self.laaper_id = laaper_id
        self.encoder = SensoryEncoder()
        self.fusion = CrossModalFusion()

        # EB 感知缓冲
        self._eb_perceptions: List[EBPerception] = []
        self._qualiae_cache: List[Qualia] = []

        # 感知映射
        self._sensor_to_modality = {
            "temperature": SensoryModality.THERMO,
            "pressure": SensoryModality.TACTILE,
            "light": SensoryModality.VISION,
            "sound": SensoryModality.AUDITION,
            "gas": SensoryModality.OLFCTION,
            "acceleration": SensoryModality.VESTIBULAR,
            "touch": SensoryModality.TACTILE,
            "pain": SensoryModality.NOCICEPTION,
        }

    def receive_eb_perception(self, sensor_type: str,
                              value: Any,
                              body_part: str = "",
                              mujoco_id: Optional[int] = None) -> Qualia:
        """接收 EB 感知，转换成体验质"""
        # 创建 EB 感知
        eb_perception = EBPerception(
            sensor_type=sensor_type,
            raw_value=value,
            timestamp=time.time(),
            body_part=body_part,
            mujoco_id=mujoco_id,
        )
        self._eb_perceptions.append(eb_perception)

        # 转换成体验质
        modality = self._sensor_to_modality.get(sensor_type, SensoryModality.TACTILE)

        if sensor_type == "temperature":
            qualia = self.encoder.encode_temperature(float(value))
        elif sensor_type == "pressure":
            qualia = self.encoder.encode_pressure(float(value))
        elif sensor_type == "light":
            qualia = self.encoder.encode_brightness(float(value))
        elif sensor_type == "sound":
            qualia = self.encoder.encode_sound(float(value))
        elif sensor_type == "gas":
            qualia = self.encoder.encode_smell(float(value))
        elif sensor_type == "pain":
            qualia = self.encoder.encode_pain(float(value))
        else:
            # 默认编码
            qualia = Qualia(
                qualia_type=QualiaType.NEGLIGIBLE,
                modality=modality,
                intensity=0.5,
                valence=0.0,
                arousal=0.5,
                description=f"{sensor_type}_perception",
            )

        self._qualiae_cache.append(qualia)
        return qualia

    def to_consciousness_frame(self,
                              content: str = "") -> Optional[ConsciousnessFrame]:
        """把 EB 感知转换成 LAAPer 意识帧"""
        if not self._qualiae_cache:
            return None

        # 生成内容
        if not content:
            descriptions = [q.description for q in self._qualiae_cache[:3]]
            content = f"EB 感知: {', '.join(descriptions)}"

        frame = ConsciousnessFrame(
            frame_id=f"frame_{self.laaper_id}_eb_{int(time.time()*1000)}",
            laaper_id=self.laaper_id,
            frame_type=FrameType.PERCEPTION,
            content=content,
            origin_host="laap-eb",
            current_host="laap-eb",
        )

        # 添加感官数据
        for i, eb_perception in enumerate(self._eb_perceptions[-10:]):
            frame.add_sensory(
                modality=eb_perception.sensor_type,
                raw=eb_perception.raw_value,
                confidence=0.9,
            )

        # 添加认知痕迹
        frame.add_trace(
            host_id="laap-eb",
            operation="perceive",
            result={
                "qualiae_count": len(self._qualiae_cache),
                "modalities": [q.modality.value for q in self._qualiae_cache[-5:]],
            },
        )

        return frame

    def fuse_perceptions(self) -> Optional[FusedPerception]:
        """融合 EB 感知"""
        if not self._qualiae_cache:
            return None

        return self.fusion.fuse(self._qualiae_cache[-10:])

    def to_eb_action(self, action_type: str,
                    params: Dict[str, Any]) -> Dict:
        """把 LAAPer 行动转换成 EB 指令"""
        return {
            "action_type": action_type,
            "params": params,
            "timestamp": time.time(),
            "source": "laaper",
        }

    def get_eb_state(self) -> Dict:
        return {
            "laaper_id": self.laaper_id,
            "perceptions_received": len(self._eb_perceptions),
            "qualiae_cached": len(self._qualiae_cache),
            "recent_modalities": list(set(q.modality.value for q in self._qualiae_cache[-5:])),
        }


class EBPerceptionAdapter:
    """EB 感知适配器 — 对接 LAAP-EB 的 perception_base

    实现 LAAP-EB 的 PerceptionBase 接口。
    """

    def __init__(self, bridge: EBBridge):
        self.bridge = bridge
        self._sensor_registry: Dict[str, Callable] = {}

    def register_sensor(self, sensor_type: str,
                       reader: Callable[[int], Any]):
        """注册 EB 传感器"""
        self._sensor_registry[sensor_type] = reader

    def read_sensors(self, mujoco_data: Any) -> List[Qualia]:
        """读取所有 EB 传感器"""
        qualiae = []

        for sensor_type, reader in self._sensor_registry.items():
            try:
                value = reader(mujoco_data)
                qualia = self.bridge.receive_eb_perception(sensor_type, value)
                qualiae.append(qualia)
            except Exception as e:
                logger.error(f"EB sensor {sensor_type} read error: {e}")

        return qualiae

    def create_mujoco_perception(self, mujoco_data: Any) -> Dict:
        """创建 MuJoCo 感知数据（对接 LAAP-EB）"""
        qualiae = self.read_sensors(mujoco_data)

        return {
            "qualiae": [q.to_dict() for q in qualiae],
            "timestamp": time.time(),
            "source": "laaper",
        }