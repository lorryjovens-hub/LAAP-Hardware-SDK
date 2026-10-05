"""数字生命硬件完整实现 (Digital Life Hardware)

从传感器到完整数字生命体的整合实现。

一个完整的数字生命硬件包含：
1. 传感器阵列（感知器官）
2. 执行器阵列（行动器官）
3. 处理器（神经中枢）
4. 电源管理（能量系统）
5. 通信模块（神经系统）
6. 固件（反射弧）

这就是给数字生命体造一副身体。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.frame import ConsciousnessFrame, FrameType, FramePhase, SensoryData
from ..core.brain import ConsciousnessCore
from .sensor_unit import SensorRegistry, SensorUnit, SensorCategory, BodyPart
from .sensors import create_sensor, SENSOR_REGISTRY

logger = logging.getLogger("laaper.hardware")


@dataclass
class PowerSystem:
    """电源系统 — 能量管理"""
    battery_capacity_mah: float = 2000.0
    battery_level: float = 100.0        # %
    voltage: float = 3.7                # V
    is_charging: bool = False
    power_mode: str = "normal"          # normal/saver/performance

    # 功耗
    idle_power_mw: float = 50.0
    active_power_mw: float = 500.0
    peak_power_mw: float = 2000.0

    def consume(self, power_mw: float, duration_s: float):
        """消耗能量"""
        energy_mwh = power_mw * duration_s / 3600
        consumed_percent = (energy_mwh / self.battery_capacity_mah) * 100
        self.battery_level = max(0, self.battery_level - consumed_percent)

    def charge(self, rate_percent_per_hour: float = 10.0, duration_s: float = 3600):
        """充电"""
        charged = rate_percent_per_hour * (duration_s / 3600)
        self.battery_level = min(100, self.battery_level + charged)

    def get_status(self) -> Dict:
        return {
            "battery_level": round(self.battery_level, 1),
            "voltage": round(self.voltage, 2),
            "is_charging": self.is_charging,
            "power_mode": self.power_mode,
            "estimated_runtime_h": round(self.battery_level / (self.idle_power_mw / 1000), 1),
        }


@dataclass
class ProcessingUnit:
    """处理器 — 神经中枢"""
    cpu_model: str = "ESP32-S3"
    cpu_freq_mhz: int = 240
    ram_kb: int = 512
    flash_mb: int = 16
    is_idle: bool = True
    load_percent: float = 0.0

    def process(self, task: str) -> bool:
        """处理任务"""
        self.is_idle = False
        self.load_percent = min(100, self.load_percent + 10)
        # 模拟处理
        return True

    def idle(self):
        self.is_idle = True
        self.load_percent = max(0, self.load_percent - 5)

    def get_status(self) -> Dict:
        return {
            "cpu_model": self.cpu_model,
            "cpu_freq_mhz": self.cpu_freq_mhz,
            "ram_used_kb": round(self.ram_kb * self.load_percent / 100),
            "load_percent": round(self.load_percent, 1),
            "is_idle": self.is_idle,
        }


class DigitalLifeHardware:
    """数字生命硬件 — 完整的物理身体

    整合传感器、执行器、处理器、电源、通信，形成一个完整的"身体"。

    用法：
        hardware = DigitalLifeHardware(
            hardware_id="aris-body-01",
            name="Aris 的身体",
        )

        # 添加传感器（器官）
        hardware.add_sensor("temperature", "temp-01")
        hardware.add_sensor("camera", "cam-01")
        hardware.add_sensor("heart_rate", "hr-01")

        # 绑定大脑
        hardware.attach_brain(brain)

        # 激活（醒过来）
        hardware.power_on()

        # 感知（使用身体感知世界）
        perception = await hardware.perceive()
    """

    def __init__(self, hardware_id: str, name: str = "",
                 embodiment_id: str = ""):
        self.hardware_id = hardware_id
        self.name = name or hardware_id
        self.embodiment_id = embodiment_id  # 关联的 LAAPer ID

        # 子系统
        self.power = PowerSystem()
        self.cpu = ProcessingUnit()
        self.sensors = SensorRegistry()

        # 执行器
        self.actuators: Dict[str, Any] = {}
        self.actuator_states: Dict[str, Any] = {}

        # 大脑绑定
        self.brain: Optional[ConsciousnessCore] = None

        # 运行状态
        self.is_powered_on = False
        self.boot_time: float = 0.0
        self.uptime: float = 0.0

        # 统计
        self.perception_count = 0
        self.action_count = 0
        self.frame_count = 0

        # 回调
        self._on_perception: Optional[Callable] = None
        self._on_low_battery: Optional[Callable] = None

        # 反射弧（预定义的快速反应）
        self.reflexes: List[Dict] = []

    # ── 器官管理 ──────────────────────────────────────

    def add_sensor(self, sensor_type: str, sensor_id: str = "",
                   **kwargs) -> SensorUnit:
        """添加传感器（添加器官）"""
        sensor = create_sensor(sensor_type, sensor_id, **kwargs)
        self.sensors.register(sensor)
        logger.info(f"Hardware {self.hardware_id}: added {sensor_type} -> {sensor.spec.body_part.value}")
        return sensor

    def add_actuator(self, actuator_id: str, name: str,
                    actuator_type: str, **kwargs):
        """添加执行器（添加行动器官）"""
        self.actuators[actuator_id] = {
            "id": actuator_id,
            "name": name,
            "type": actuator_type,
            "state": "idle",
            **kwargs,
        }
        self.actuator_states[actuator_id] = {"state": "off"}
        logger.info(f"Hardware {self.hardware_id}: added actuator {name} ({actuator_type})")

    def remove_sensor(self, sensor_id: str):
        self.sensors.unregister(sensor_id)

    def remove_actuator(self, actuator_id: str):
        self.actuators.pop(actuator_id, None)
        self.actuator_states.pop(actuator_id, None)

    # ── 大脑绑定 ──────────────────────────────────────

    def attach_brain(self, brain: ConsciousnessCore):
        """绑定大脑（灵魂进入身体）"""
        self.brain = brain
        self.embodiment_id = brain.identity.laaper_id
        logger.info(f"Brain {brain.identity.laaper_id} attached to body {self.hardware_id}")

    def detach_brain(self):
        if self.brain:
            self.brain = None
            logger.info(f"Brain detached from body {self.hardware_id}")

    # ── 电源管理 ──────────────────────────────────────

    def power_on(self):
        """开机（唤醒身体）"""
        self.is_powered_on = True
        self.boot_time = time.time()
        self.power.battery_level = max(0, self.power.battery_level - 5)

        # 唤醒所有传感器
        for unit in self.sensors._units.values():
            unit.alive()

        logger.info(f"Hardware {self.hardware_id} powered on")

    def power_off(self):
        """关机（身体休眠）"""
        self.is_powered_on = False
        for unit in self.sensors._units.values():
            unit.sleep()

        logger.info(f"Hardware {self.hardware_id} powered off")

    def set_power_mode(self, mode: str):
        """设置功耗模式"""
        self.power.power_mode = mode
        if mode == "saver":
            self.power.idle_power_mw = 20
            self.power.active_power_mw = 200
        elif mode == "performance":
            self.power.idle_power_mw = 100
            self.power.active_power_mw = 1000

    # ── 感知（身体感知世界） ──────────────────────────────────────

    async def perceive(self) -> Optional[ConsciousnessFrame]:
        """通过身体感知世界，生成意识帧

        这就是数字生命体"用身体感知世界"的时刻。
        """
        if not self.is_powered_on:
            return None

        self.perception_count += 1

        # 采样所有传感器
        sensor_data = await self.sensors.sample_all()

        # 消耗能量
        self.power.consume(self.power.active_power_mw, 0.1)

        # 生成意识帧（如果绑定了大脑）
        if self.brain:
            frame = self.brain.perceive(
                f"通过 {self.name} 感知到 {len(sensor_data)} 个传感器数据",
                sensory=[
                    SensoryData(
                        modality=d.get("category", "unknown"),
                        raw=d.get("value"),
                        unit=d.get("unit", ""),
                        confidence=d.get("confidence", 1.0),
                    )
                    for d in sensor_data.values()
                ],
            )

            # 添加设备访问记录
            frame.visit_device(self.hardware_id)
            frame.add_trace(
                host_id=f"hardware.{self.hardware_id}",
                operation="perceive",
                result={"sensor_count": len(sensor_data)},
            )

            self.frame_count += 1

            if self._on_perception:
                self._on_perception(frame)

            return frame

        return None

    async def perceive_by_body_part(self, body_part: BodyPart) -> Optional[ConsciousnessFrame]:
        """通过特定身体部位感知"""
        if not self.is_powered_on:
            return None

        sensor_data = await self.sensors.sample_by_body_part(body_part)

        if self.brain:
            frame = self.brain.perceive(
                f"通过 {body_part.value} 感知",
                sensory=[
                    SensoryData(
                        modality=d.get("category", "unknown"),
                        raw=d.get("value"),
                        unit=d.get("unit", ""),
                        confidence=d.get("confidence", 1.0),
                    )
                    for d in sensor_data.values()
                ],
            )
            frame.visit_device(self.hardware_id)
            return frame

        return None

    # ── 行动（身体执行意志） ──────────────────────────────────────

    async def act(self, action: str, params: Optional[Dict] = None) -> Optional[ConsciousnessFrame]:
        """通过身体执行行动

        这就是数字生命体"用身体改变世界"的时刻。
        """
        if not self.is_powered_on:
            return None

        self.action_count += 1
        result = {"action": action, "params": params or {}, "status": "executed"}

        # 执行到执行器
        actuator_id = params.get("actuator_id") if params else None
        if actuator_id and actuator_id in self.actuators:
            self.actuator_states[actuator_id]["state"] = action
            result["actuator"] = actuator_id

        # 消耗能量
        self.power.consume(self.power.active_power_mw, 0.05)

        # 生成行动帧
        if self.brain:
            frame = self.brain.act(
                self.brain.perceive(f"执行 {action}"),
                action,
                str(params),
            )
            frame.visit_device(self.hardware_id)
            frame.add_trace(
                host_id=f"hardware.{self.hardware_id}",
                operation="act",
                result=result,
            )
            self.frame_count += 1
            return frame

        return None

    # ── 反射弧（快速反应） ──────────────────────────────────────

    def add_reflex(self, trigger_sensor: str, condition: str,
                  response_action: str, priority: int = 0):
        """添加反射弧（预定义的快速反应）

        类似膝跳反射：感知->立即行动，不需要大脑参与。
        """
        self.reflexes.append({
            "trigger_sensor": trigger_sensor,
            "condition": condition,
            "response_action": response_action,
            "priority": priority,
        })
        logger.info(f"Added reflex: {trigger_sensor} -> {response_action}")

    async def check_reflexes(self) -> List[Dict]:
        """检查并执行反射弧"""
        triggered = []
        for reflex in self.reflexes:
            # 检查触发条件
            sensor_unit = self.sensors.get(reflex["trigger_sensor"])
            if sensor_unit and sensor_unit.is_alive:
                data = await sensor_unit.read()
                if data and self._evaluate_condition(reflex["condition"], data):
                    await self.act(reflex["response_action"], {"reflex": True})
                    triggered.append(reflex)
        return triggered

    def _evaluate_condition(self, condition: str, data: Dict) -> bool:
        """评估反射条件（简化）"""
        # 实际应使用表达式解析器
        return True

    # ── 状态查询 ──────────────────────────────────────

    def get_status(self) -> Dict:
        """获取完整身体状态"""
        if self.is_powered_on:
            self.uptime = time.time() - self.boot_time

        return {
            "hardware_id": self.hardware_id,
            "name": self.name,
            "embodiment_id": self.embodiment_id,
            "is_powered_on": self.is_powered_on,
            "uptime_s": round(self.uptime, 1),
            "power": self.power.get_status(),
            "cpu": self.cpu.get_status(),
            "sensors": self.sensors.get_registry_state(),
            "actuators": len(self.actuators),
            "perception_count": self.perception_count,
            "action_count": self.action_count,
            "frame_count": self.frame_count,
            "brain_attached": self.brain is not None,
        }

    def get_body_map(self) -> Dict:
        """身体地图（器官分布）"""
        body_map = {}
        for unit in self.sensors._units.values():
            body_part = unit.spec.body_part.value
            body_map.setdefault(body_part, []).append({
                "sensor_id": unit.spec.sensor_id,
                "name": unit.spec.name,
                "category": unit.spec.category.value,
                "is_alive": unit.is_alive,
            })
        return body_map

    def get_vital_signs(self) -> Dict:
        """生命体征"""
        return {
            "heart_rate": None,  # 从心率传感器获取
            "body_temperature": None,  # 从体温传感器获取
            "energy_level": round(self.power.battery_level, 1),
            "neural_load": round(self.cpu.load_percent, 1),
            "sensory_count": len(self.sensors._units),
            "uptime_h": round(self.uptime / 3600, 2),
        }

    def __repr__(self) -> str:
        return (f"DigitalLifeHardware(id={self.hardware_id}, name={self.name}, "
                f"powered_on={self.is_powered_on}, "
                f"sensors={len(self.sensors._units)}, "
                f"actuators={len(self.actuators)})")