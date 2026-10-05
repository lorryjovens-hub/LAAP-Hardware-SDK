"""LAAPer 传感器注册单元 (Sensor Registry Unit, SRU)

每种传感器像一个器官，有自己的接口规范、供血方式和认知映射。

设计哲学：
- 标准化接口：所有传感器统一注册/注销/采样接口
- 认知映射：传感器映射到 LAAPer 的"身体部位"
- 自描述：传感器自带能力声明、精度、采样率
- 热插拔：支持运行时注册/注销
- 单元化：每个传感器是独立的"器官单元"

这就是生态扩张的基石：新传感器只需实现一个单元类。
"""
from __future__ import annotations

import abc
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
from enum import Enum

logger = logging.getLogger("laaper.sensor_unit")


class SensorCategory(str, Enum):
    """传感器类别"""
    ENVIRONMENT = "environment"     # 环境（温湿度/光照/气压）
    MOTION = "motion"               # 运动（加速度/陀螺仪/雷达）
    PROXIMITY = "proximity"         # 接近（红外/超声波/ToF）
    VISION = "vision"               # 视觉（摄像头/深度相机）
    AUDIO = "audio"                 # 听觉（麦克风/声呐）
    BIOMETRIC = "biometric"         # 生物（心率/血氧/体温）
    LOCATION = "location"           # 位置（GPS/北斗/UWB）
    CHEMICAL = "chemical"           # 化学（气体/PH/烟雾）
    FORCE = "force"                 # 力学（压力/扭矩/称重）
    ELECTRICAL = "electrical"       # 电学（电压/电流/功率）


class BodyPart(str, Enum):
    """LAAPer 身体部位（认知映射）"""
    SKIN = "skin"                 # 皮肤（触觉/温度/压力）
    EYE = "eye"                   # 眼睛（视觉）
    EAR = "ear"                   # 耳朵（听觉）
    NOSE = "nose"                 # 鼻子（嗅觉）
    TONGUE = "tongue"             # 舌头（味觉）
    VESTIBULAR = "vestibular"     # 前庭（平衡感）
    PROPRIOCEPTION = "proprioception"  # 本体感觉（肢体位置）
    INTEROCEPTION = "interoception"    # 内感受（心跳/呼吸/温度）


@dataclass
class SensorSpec:
    """传感器规格（自描述）"""
    sensor_id: str
    name: str
    category: SensorCategory
    body_part: BodyPart
    description: str = ""

    # 能力
    precision: float = 0.8          # 精度 (0-1)
    range_min: float = 0.0
    range_max: float = 100.0
    unit: str = ""
    sampling_rate_hz: float = 1.0   # 采样率
    resolution: float = 0.1         # 分辨率

    # 物理接口
    interface: str = "i2c"          # i2c/spi/uart/gpio/analog/ble/wifi
    address: str = ""               # 硬件地址
    power_voltage: float = 3.3      # 工作电压
    power_current_ma: float = 10.0  # 工作电流

    # 元数据
    manufacturer: str = ""
    model: str = ""
    firmware_version: str = ""
    cost_usd: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "sensor_id": self.sensor_id,
            "name": self.name,
            "category": self.category.value,
            "body_part": self.body_part.value,
            "description": self.description,
            "precision": self.precision,
            "range": [self.range_min, self.range_max],
            "unit": self.unit,
            "sampling_rate_hz": self.sampling_rate_hz,
            "interface": self.interface,
            "power": {"voltage": self.power_voltage, "current_ma": self.power_current_ma},
        }


class SensorUnit(abc.ABC):
    """传感器单元基类 — LAAPer 的一个器官

    所有传感器必须实现这个接口。

    用法：
        class TemperatureSensor(SensorUnit):
            async def sample(self) -> float:
                return 22.5
    """

    def __init__(self, spec: SensorSpec):
        self.spec = spec
        self.is_alive = False
        self.energy = 100.0
        self.last_sample_time = 0.0
        self.sample_count = 0
        self.error_count = 0

        # 数据缓存
        self._buffer: List[Dict] = []
        self._max_buffer = 1000

        # 校准参数
        self.calibration_offset = 0.0
        self.calibration_scale = 1.0

        # 回调
        self._on_sample: Optional[Callable] = None
        self._on_error: Optional[Callable] = None

    @abc.abstractmethod
    async def sample(self) -> Any:
        """采样原始数据（子类实现）"""
        pass

    async def read(self) -> Optional[Dict]:
        """读取校准后的数据"""
        if not self.is_alive:
            return None

        try:
            raw = await self.sample()
            calibrated = self._calibrate(raw)

            result = {
                "sensor_id": self.spec.sensor_id,
                "body_part": self.spec.body_part.value,
                "category": self.spec.category.value,
                "value": calibrated,
                "unit": self.spec.unit,
                "timestamp": time.time(),
                "precision": self.spec.precision,
                "confidence": self._compute_confidence(),
            }

            # 缓存
            self._buffer.append(result)
            if len(self._buffer) > self._max_buffer:
                self._buffer.pop(0)

            self.sample_count += 1
            self.last_sample_time = time.time()
            self.energy = max(0, self.energy - 0.01)

            if self._on_sample:
                self._on_sample(result)

            return result

        except Exception as e:
            self.error_count += 1
            logger.error(f"Sensor {self.spec.sensor_id} sample error: {e}")
            if self._on_error:
                self._on_error(e)
            return None

    def _calibrate(self, raw: Any) -> Any:
        """应用校准"""
        if isinstance(raw, (int, float)):
            return raw * self.calibration_scale + self.calibration_offset
        return raw

    def _compute_confidence(self) -> float:
        """计算置信度（基于错误率和能量）"""
        total = self.sample_count + self.error_count
        if total == 0:
            return 1.0
        accuracy = self.sample_count / total
        energy_factor = self.energy / 100.0
        return accuracy * 0.7 + energy_factor * 0.3

    def calibrate(self, offset: float = 0.0, scale: float = 1.0):
        """校准传感器"""
        self.calibration_offset = offset
        self.calibration_scale = scale

    def alive(self):
        self.is_alive = True
        logger.info(f"Sensor {self.spec.sensor_id} alive ({self.spec.body_part.value})")

    def sleep(self):
        self.is_alive = False

    def get_stats(self) -> Dict:
        return {
            "sensor_id": self.spec.sensor_id,
            "name": self.spec.name,
            "body_part": self.spec.body_part.value,
            "is_alive": self.is_alive,
            "energy": round(self.energy, 1),
            "sample_count": self.sample_count,
            "error_count": self.error_count,
            "last_sample": self.last_sample_time,
            "buffer_size": len(self._buffer),
            "confidence": round(self._compute_confidence(), 3),
        }

    def get_recent(self, n: int = 10) -> List[Dict]:
        return self._buffer[-n:]

    def on_sample(self, callback: Callable):
        self._on_sample = callback

    def on_error(self, callback: Callable):
        self._on_error = callback


class SensorRegistry:
    """传感器注册表 — 管理所有传感器单元

    用法：
        registry = SensorRegistry()
        registry.register(TemperatureSensor(...))
        registry.register(CameraSensor(...))

        # 采样所有
        data = await registry.sample_all()

        # 采样特定类别
        env_data = await registry.sample_by_category(SensorCategory.ENVIRONMENT)
    """

    def __init__(self):
        self._units: Dict[str, SensorUnit] = {}
        self._groups: Dict[str, List[str]] = {}
        self._sample_history: List[Dict] = []

    def register(self, unit: SensorUnit) -> bool:
        """注册传感器单元"""
        if unit.spec.sensor_id in self._units:
            logger.warning(f"Sensor {unit.spec.sensor_id} already registered")
            return False

        self._units[unit.spec.sensor_id] = unit
        logger.info(f"Registered sensor: {unit.spec.name} -> {unit.spec.body_part.value}")

        # 自动分组
        category = unit.spec.category.value
        body_part = unit.spec.body_part.value
        for group_name in [f"category.{category}", f"body.{body_part}"]:
            self._groups.setdefault(group_name, []).append(unit.spec.sensor_id)

        return True

    def unregister(self, sensor_id: str) -> bool:
        """注销传感器"""
        if sensor_id not in self._units:
            return False
        del self._units[sensor_id]
        # 从所有分组移除
        for group in self._groups.values():
            if sensor_id in group:
                group.remove(sensor_id)
        return True

    def get(self, sensor_id: str) -> Optional[SensorUnit]:
        return self._units.get(sensor_id)

    def list_all(self) -> List[Dict]:
        return [u.get_stats() for u in self._units.values()]

    def list_by_body_part(self, body_part: BodyPart) -> List[SensorUnit]:
        return [u for u in self._units.values() if u.spec.body_part == body_part]

    def list_by_category(self, category: SensorCategory) -> List[SensorUnit]:
        return [u for u in self._units.values() if u.spec.category == category]

    def list_by_group(self, group_name: str) -> List[SensorUnit]:
        ids = self._groups.get(group_name, [])
        return [self._units[sid] for sid in ids if sid in self._units]

    # ── 采样 ──────────────────────────────────────

    async def sample_all(self) -> Dict[str, Dict]:
        """采样所有存活传感器"""
        results = {}
        for sensor_id, unit in self._units.items():
            if unit.is_alive:
                data = await unit.read()
                if data:
                    results[sensor_id] = data
        return results

    async def sample_by_category(self, category: SensorCategory) -> Dict[str, Dict]:
        """采样特定类别的传感器"""
        results = {}
        for unit in self.list_by_category(category):
            if unit.is_alive:
                data = await unit.read()
                if data:
                    results[unit.spec.sensor_id] = data
        return results

    async def sample_by_body_part(self, body_part: BodyPart) -> Dict[str, Dict]:
        """采样特定身体部位的传感器"""
        results = {}
        for unit in self.list_by_body_part(body_part):
            if unit.is_alive:
                data = await unit.read()
                if data:
                    results[unit.spec.sensor_id] = data
        return results

    async def sample_group(self, group_name: str) -> Dict[str, Dict]:
        """采样特定组的传感器"""
        results = {}
        for unit in self.list_by_group(group_name):
            if unit.is_alive:
                data = await unit.read()
                if data:
                    results[unit.spec.sensor_id] = data
        return results

    # ── 感知融合 ──────────────────────────────────────

    async def perceive_environment(self) -> Dict:
        """融合所有环境传感器的感知"""
        env_data = await self.sample_by_category(SensorCategory.ENVIRONMENT)
        if not env_data:
            return {}

        # 提取并融合
        temperatures = [d["value"] for d in env_data.values()
                       if d.get("category") == "environment" and "temp" in d.get("unit", "").lower()]
        humidities = [d["value"] for d in env_data.values()
                     if d.get("category") == "environment" and "humid" in d.get("unit", "").lower()]

        return {
            "temperature": sum(temperatures) / len(temperatures) if temperatures else None,
            "humidity": sum(humidities) / len(humidities) if humidities else None,
            "sensor_count": len(env_data),
            "timestamp": time.time(),
        }

    def get_registry_state(self) -> Dict:
        return {
            "total_units": len(self._units),
            "alive_units": sum(1 for u in self._units.values() if u.is_alive),
            "categories": list(set(u.spec.category.value for u in self._units.values())),
            "body_parts": list(set(u.spec.body_part.value for u in self._units.values())),
            "groups": {k: len(v) for k, v in self._groups.items()},
        }