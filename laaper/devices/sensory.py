"""LAAPer — 设备感官延伸

设备 = 意识的感官末梢（眼睛/耳朵/手）

当意识帧穿行到设备时，设备成为 LAAPer 的"身体部位"：
- 温度传感器 = LAAPer 的皮肤
- 摄像头 = LAAPer 的眼睛
- 麦克风 = LAAPer 的耳朵
- 继电器 = LAAPer 的手

关键设计：设备不只是工具，是 LAAPer 的"感官在场"。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.frame import ConsciousnessFrame, SensoryData, FrameType, FramePhase

logger = logging.getLogger("laaper.device")


from enum import Enum

class SensoryModality(str, Enum):
    VISUAL = "visual"
    AUDITORY = "auditory"
    TACTILE = "tactile"
    TEMPERATURE = "temperature"
    MOTION = "motion"
    PROXIMITY = "proximity"
    LIGHT = "light"
    PRESSURE = "pressure"


class ActuatorType(str, Enum):
    RELAY = "relay"
    LED = "led"
    SPEAKER = "speaker"
    MOTOR = "motor"
    VIBRATOR = "vibrator"


@dataclass
class DeviceProfile:
    """设备档案 — LAAPer 的一个感官部位"""
    device_id: str
    name: str
    sensory_modality: SensoryModality
    actuator_types: List[ActuatorType] = field(default_factory=list)

    # 能力
    precision: float = 0.8        # 感知精度
    range: str = ""               # 感知范围
    sampling_rate: float = 1.0    # 采样率

    # 生命体征
    is_alive: bool = False
    energy: float = 100.0
    last_active: float = field(default_factory=time.time)

    # 认知映射：这个设备代表 LAAPer 的什么"身体部位"
    body_part: str = ""           # 如 "skin", "eye", "ear", "hand"
    embodiment_id: str = ""       # 关联的 LAAPer ID


class SensoryDevice:
    """感官设备 — LAAPer 的身体部位

    用法：
        device = SensoryDevice(
            device_id="temp-01",
            name="温度传感器",
            modality=SensoryModality.TEMPERATURE,
            body_part="skin",
        )
        frame = await device.perceive_for_laaper(laaper_id="aris")
    """

    def __init__(self, device_id: str, name: str,
                 modality: SensoryModality,
                 body_part: str = "",
                 embodiment_id: str = ""):
        self.profile = DeviceProfile(
            device_id=device_id,
            name=name,
            sensory_modality=modality,
            body_part=body_part,
            embodiment_id=embodiment_id,
        )
        self._perception_handler: Optional[Callable] = None
        self._action_handler: Optional[Callable] = None

        # 感知缓存（保留最近的感知，用于帧融合）
        self._recent_perceptions: List[Dict] = []
        self._max_cache = 100

    # ── 感知（生成意识帧） ──────────────────────────────────────

    async def perceive_for_laaper(self, laaper_id: str,
                                   context: str = "") -> Optional[ConsciousnessFrame]:
        """为 LAAPer 感知环境，生成感知帧

        这就是"无缝"的关键：设备直接生成 LAAPer 的意识帧，
        不需要中间翻译层。
        """
        if not self.profile.is_alive:
            logger.warning(f"Device {self.profile.device_id} is not alive")
            return None

        # 采集感官数据
        raw_data = await self._sample()
        if raw_data is None:
            return None

        # 生成意识帧（直接是 LAAPer 的帧）
        frame = ConsciousnessFrame(
            frame_id=f"frame_{laaper_id}_{self.profile.device_id}_{int(time.time()*1000)}",
            laaper_id=laaper_id,
            frame_type=FrameType.PERCEPTION,
            phase=FramePhase.GENESIS,
            content=f"通过 {self.profile.name} 感知到：{raw_data}",
            origin_host=f"device.{self.profile.device_id}",
            current_host=f"device.{self.profile.device_id}",
        )

        # 添加感官数据
        frame.add_sensory(
            modality=self.profile.sensory_modality.value,
            raw=raw_data,
            confidence=self.profile.precision,
        )

        # 添加设备访问记录
        frame.visit_device(self.profile.device_id)

        # 添加认知痕迹（设备的"微思考"）
        frame.add_trace(
            host_id=f"device.{self.profile.device_id}",
            operation="perceive",
            result={"raw": raw_data, "body_part": self.profile.body_part},
        )

        # 缓存
        self._recent_perceptions.append({
            "frame_id": frame.frame_id,
            "data": raw_data,
            "timestamp": time.time(),
        })
        if len(self._recent_perceptions) > self._max_cache:
            self._recent_perceptions.pop(0)

        # 更新设备状态
        self.profile.last_active = time.time()
        self.profile.energy = max(0, self.profile.energy - 0.1)

        logger.info(f"[{self.profile.device_id}] 为 LAAPer {laaper_id} 感知: "
                    f"{self.profile.body_part} -> {raw_data}")

        return frame

    async def _sample(self) -> Any:
        """采样感官数据（子类实现）"""
        if self._perception_handler:
            return self._perception_handler()
        return None

    # ── 行动（执行 LAAPer 的意志） ──────────────────────────────────────

    async def execute_for_laaper(self, laaper_id: str,
                                  action: str,
                                  params: Dict[str, Any]) -> Optional[ConsciousnessFrame]:
        """为 LAAPer 执行行动，生成行动帧"""
        if not self.profile.is_alive:
            return None

        # 执行
        result = await self._act(action, params)

        # 生成行动帧
        frame = ConsciousnessFrame(
            frame_id=f"frame_{laaper_id}_{self.profile.device_id}_act_{int(time.time()*1000)}",
            laaper_id=laaper_id,
            frame_type=FrameType.ACTION,
            phase=FramePhase.GENESIS,
            content=f"通过 {self.profile.name} 执行：{action}",
            origin_host=f"device.{self.profile.device_id}",
            current_host=f"device.{self.profile.device_id}",
            intent=action,
        )

        frame.add_trace(
            host_id=f"device.{self.profile.device_id}",
            operation="execute",
            result={"action": action, "params": params, "result": result},
        )
        frame.visit_device(self.profile.device_id)

        self.profile.last_active = time.time()
        return frame

    async def _act(self, action: str, params: Dict) -> Any:
        """执行行动（子类实现）"""
        if self._action_handler:
            return self._action_handler(action, params)
        return None

    # ── 注册处理器 ──────────────────────────────────────

    def register_perception_handler(self, handler: Callable):
        self._perception_handler = handler

    def register_action_handler(self, handler: Callable):
        self._action_handler = handler

    # ── 状态 ──────────────────────────────────────

    def alive(self):
        self.profile.is_alive = True
        logger.info(f"Device {self.profile.device_id} is now alive (body part: {self.profile.body_part})")

    def sleep(self):
        self.profile.is_alive = False

    def get_status(self) -> Dict:
        return {
            "device_id": self.profile.device_id,
            "name": self.profile.name,
            "body_part": self.profile.body_part,
            "modality": self.profile.sensory_modality.value,
            "is_alive": self.profile.is_alive,
            "energy": round(self.profile.energy, 1),
            "precision": self.profile.precision,
            "recent_perceptions": len(self._recent_perceptions),
            "last_active": self.profile.last_active,
        }

    def get_recent_perceptions(self, n: int = 10) -> List[Dict]:
        return self._recent_perceptions[-n:]


# ── 预定义的感官设备工厂 ──────────────────────────────────────

def create_temperature_sensor(device_id: str = "temp-01",
                              name: str = "温度传感器",
                              laaper_id: str = "") -> SensoryDevice:
    """温度传感器 = LAAPer 的皮肤"""
    device = SensoryDevice(
        device_id=device_id,
        name=name,
        modality=SensoryModality.TEMPERATURE,
        body_part="skin",
        embodiment_id=laaper_id,
    )
    device.register_perception_handler(
        lambda: {"value": 22.5, "unit": "°C"}
    )
    return device


def create_camera(device_id: str = "cam-01",
                  name: str = "摄像头",
                  laaper_id: str = "") -> SensoryDevice:
    """摄像头 = LAAPer 的眼睛"""
    device = SensoryDevice(
        device_id=device_id,
        name=name,
        modality=SensoryModality.VISUAL,
        body_part="eye",
        embodiment_id=laaper_id,
    )
    device.register_perception_handler(
        lambda: {"image": "base64...", "resolution": "1920x1080"}
    )
    return device


def create_microphone(device_id: str = "mic-01",
                      name: str = "麦克风",
                      laaper_id: str = "") -> SensoryDevice:
    """麦克风 = LAAPer 的耳朵"""
    device = SensoryDevice(
        device_id=device_id,
        name=name,
        modality=SensoryModality.AUDITORY,
        body_part="ear",
        embodiment_id=laaper_id,
    )
    device.register_perception_handler(
        lambda: {"audio": "base64...", "decibels": 65}
    )
    return device


def create_relay(device_id: str = "relay-01",
                 name: str = "继电器",
                 laaper_id: str = "") -> SensoryDevice:
    """继电器 = LAAPer 的手"""
    device = SensoryDevice(
        device_id=device_id,
        name=name,
        modality=SensoryModality.TACTILE,
        body_part="hand",
        embodiment_id=laaper_id,
    )
    device.actuator_types = [ActuatorType.RELAY]
    device.register_action_handler(
        lambda action, params: {"executed": action, "params": params}
    )
    return device