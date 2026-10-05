"""LAAPer 具体传感器单元实现

每种传感器 = LAAPer 的一个器官单元

包含 20+ 种常见传感器的标准化实现，可直接用于真实硬件。
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Any, Dict, Optional

from .sensor_unit import (
    SensorUnit,
    SensorSpec,
    SensorCategory,
    BodyPart,
)

logger = logging.getLogger("laaper.sensors")


# ═══════════════════════════════════════════════
# 环境传感器 (Environment) — LAAPer 的皮肤/内感受
# ═══════════════════════════════════════════════

class TemperatureSensor(SensorUnit):
    """温度传感器 — LAAPer 的皮肤（热感受）

    硬件: DHT22 / DS18B20 / BME280 / MPU6050
    接口: I2C / One-Wire / GPIO
    范围: -40°C ~ 85°C
    """

    def __init__(self, sensor_id: str = "temp-01", name: str = "温度传感器",
                 address: str = "0x48"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.ENVIRONMENT,
            body_part=BodyPart.SKIN,
            description="感知环境温度",
            precision=0.95,
            range_min=-40.0,
            range_max=85.0,
            unit="°C",
            sampling_rate_hz=0.5,
            resolution=0.1,
            interface="i2c",
            address=address,
            power_voltage=3.3,
            power_current_ma=1.5,
            manufacturer="TI",
            model="TMP117",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        # 模拟采样（实际对接硬件）
        return round(22.5 + random.uniform(-2, 2), 1)


class HumiditySensor(SensorUnit):
    """湿度传感器 — LAAPer 的皮肤（湿润感受）

    硬件: DHT22 / SHT31 / BME280
    范围: 0% ~ 100% RH
    """

    def __init__(self, sensor_id: str = "humid-01", name: str = "湿度传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.ENVIRONMENT,
            body_part=BodyPart.SKIN,
            description="感知环境湿度",
            precision=0.90,
            range_min=0.0,
            range_max=100.0,
            unit="%RH",
            sampling_rate_hz=0.5,
            resolution=0.1,
            interface="i2c",
            power_current_ma=2.0,
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(55.0 + random.uniform(-5, 5), 1)


class LightSensor(SensorUnit):
    """光照传感器 — LAAPer 的眼睛（光感）

    硬件: BH1750 / TSL2561 / APDS9960
    范围: 0 ~ 65535 lux
    """

    def __init__(self, sensor_id: str = "light-01", name: str = "光照传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.ENVIRONMENT,
            body_part=BodyPart.EYE,
            description="感知环境光照强度",
            precision=0.85,
            range_min=0.0,
            range_max=65535.0,
            unit="lux",
            sampling_rate_hz=1.0,
            resolution=1.0,
            interface="i2c",
            power_current_ma=1.2,
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(500 + random.uniform(-100, 100), 0)


class PressureSensor(SensorUnit):
    """气压传感器 — LAAPer 的内感受（气压变化）

    硬件: BMP280 / MPL3115A2
    范围: 300 ~ 1100 hPa
    """

    def __init__(self, sensor_id: str = "press-01", name: str = "气压传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.ENVIRONMENT,
            body_part=BodyPart.INTEROCEPTION,
            description="感知大气压力",
            precision=0.92,
            range_min=300.0,
            range_max=1100.0,
            unit="hPa",
            sampling_rate_hz=1.0,
            resolution=0.01,
            interface="i2c",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(1013.25 + random.uniform(-2, 2), 2)


class GasSensor(SensorUnit):
    """气体传感器 — LAAPer 的鼻子（嗅觉）

    硬件: MQ-2 / MQ-135 / CCS811 / SGP30
    范围: 0 ~ 10000 ppm
    """

    def __init__(self, sensor_id: str = "gas-01", name: str = "气体传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.CHEMICAL,
            body_part=BodyPart.NOSE,
            description="感知有害气体浓度",
            precision=0.75,
            range_min=0.0,
            range_max=10000.0,
            unit="ppm",
            sampling_rate_hz=0.2,
            resolution=1.0,
            interface="analog",
            power_current_ma=150.0,
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(50 + random.uniform(-10, 10), 0)


class NoiseSensor(SensorUnit):
    """噪声传感器 — LAAPer 的耳朵（声压感受）

    硬件: 驻极体麦克风 + MAX9814 / INMP441
    范围: 30 ~ 120 dB
    """

    def __init__(self, sensor_id: str = "noise-01", name: str = "噪声传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.AUDIO,
            body_part=BodyPart.EAR,
            description="感知环境噪声水平",
            precision=0.80,
            range_min=30.0,
            range_max=120.0,
            unit="dB",
            sampling_rate_hz=10.0,
            resolution=0.1,
            interface="analog",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(45 + random.uniform(-5, 5), 1)


# ═══════════════════════════════════════════════
# 运动传感器 (Motion) — LAAPer 的前庭/本体感觉
# ═══════════════════════════════════════════════

class AccelerometerSensor(SensorUnit):
    """加速度传感器 — LAAPer 的前庭（平衡感）

    硬件: MPU6050 / ADXL345 / LIS3DH
    范围: ±16g
    """

    def __init__(self, sensor_id: str = "accel-01", name: str = "加速度传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.MOTION,
            body_part=BodyPart.VESTIBULAR,
            description="感知加速度变化",
            precision=0.95,
            range_min=-16.0,
            range_max=16.0,
            unit="g",
            sampling_rate_hz=100.0,
            resolution=0.001,
            interface="i2c",
        )
        super().__init__(spec)

    async def sample(self) -> Dict[str, float]:
        return {
            "x": round(random.uniform(-0.1, 0.1), 3),
            "y": round(random.uniform(-0.1, 0.1), 3),
            "z": round(1.0 + random.uniform(-0.05, 0.05), 3),
        }


class GyroscopeSensor(SensorUnit):
    """陀螺仪 — LAAPer 的前庭（旋转感）

    硬件: MPU6050 / L3GD20H / BMI270
    范围: ±2000°/s
    """

    def __init__(self, sensor_id: str = "gyro-01", name: str = "陀螺仪"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.MOTION,
            body_part=BodyPart.VESTIBULAR,
            description="感知角速度",
            precision=0.95,
            range_min=-2000.0,
            range_max=2000.0,
            unit="°/s",
            sampling_rate_hz=100.0,
            resolution=0.01,
            interface="i2c",
        )
        super().__init__(spec)

    async def sample(self) -> Dict[str, float]:
        return {
            "x": round(random.uniform(-1, 1), 2),
            "y": round(random.uniform(-1, 1), 2),
            "z": round(random.uniform(-1, 1), 2),
        }


class MotionSensor(SensorUnit):
    """运动检测传感器 — LAAPer 的本体感觉

    硬件: PIR HC-SR501 / RCWL-0516
    范围: 0/1
    """

    def __init__(self, sensor_id: str = "motion-01", name: str = "运动传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.MOTION,
            body_part=BodyPart.PROPRIOCEPTION,
            description="检测人体运动",
            precision=0.90,
            range_min=0.0,
            range_max=1.0,
            unit="bool",
            sampling_rate_hz=5.0,
            resolution=1.0,
            interface="gpio",
            power_current_ma=65.0,
        )
        super().__init__(spec)

    async def sample(self) -> int:
        return 1 if random.random() > 0.3 else 0


# ═══════════════════════════════════════════════
# 接近传感器 (Proximity) — LAAPer 的皮肤（触觉）
# ═══════════════════════════════════════════════

class ProximitySensor(SensorUnit):
    """接近传感器 — LAAPer 的皮肤（近距感知）

    硬件: VL53L0X / HC-SR04 / Sharp GP2Y0A21
    范围: 0 ~ 2000mm
    """

    def __init__(self, sensor_id: str = "prox-01", name: str = "接近传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.PROXIMITY,
            body_part=BodyPart.SKIN,
            description="感知物体接近距离",
            precision=0.88,
            range_min=0.0,
            range_max=2000.0,
            unit="mm",
            sampling_rate_hz=20.0,
            resolution=1.0,
            interface="i2c",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(random.uniform(50, 500), 0)


class TouchSensor(SensorUnit):
    """触摸传感器 — LAAPer 的皮肤（触觉）

    硬件: TTP223 / MPR121 / FSR
    范围: 0/1 或 0-1023
    """

    def __init__(self, sensor_id: str = "touch-01", name: str = "触摸传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.PROXIMITY,
            body_part=BodyPart.SKIN,
            description="感知触摸/压力",
            precision=0.92,
            range_min=0.0,
            range_max=1023.0,
            unit="raw",
            sampling_rate_hz=50.0,
            resolution=1.0,
            interface="capacitive",
        )
        super().__init__(spec)

    async def sample(self) -> int:
        return 1 if random.random() > 0.7 else 0


class PressurePadSensor(SensorUnit):
    """压力垫传感器 — LAAPer 的皮肤（压力）

    硬件: FSR 402 / 压电薄膜
    范围: 0.2N ~ 20N
    """

    def __init__(self, sensor_id: str = "press-pad-01", name: str = "压力垫"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.FORCE,
            body_part=BodyPart.SKIN,
            description="感知压力/重量",
            precision=0.85,
            range_min=0.2,
            range_max=20.0,
            unit="N",
            sampling_rate_hz=100.0,
            resolution=0.1,
            interface="analog",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(random.uniform(0, 5), 2)


# ═══════════════════════════════════════════════
# 视觉传感器 (Vision) — LAAPer 的眼睛
# ═══════════════════════════════════════════════

class CameraSensor(SensorUnit):
    """摄像头 — LAAPer 的眼睛

    硬件: OV2640 / OV5640 / CSI camera
    范围: 图像流
    """

    def __init__(self, sensor_id: str = "cam-01", name: str = "摄像头",
                 resolution: str = "1920x1080"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.VISION,
            body_part=BodyPart.EYE,
            description="视觉感知",
            precision=0.90,
            range_min=0.0,
            range_max=1.0,
            unit="image",
            sampling_rate_hz=30.0,
            resolution=1.0,
            interface="csi",
            power_current_ma=200.0,
        )
        super().__init__(spec)
        self._resolution = resolution

    async def sample(self) -> Dict:
        return {
            "type": "image",
            "resolution": self._resolution,
            "frame_id": int(time.time() * 1000),
            "brightness": round(random.uniform(0.3, 0.9), 2),
        }


class DepthCameraSensor(SensorUnit):
    """深度相机 — LAAPer 的眼睛（立体视觉）

    硬件: Intel RealSense / Orbbec Astra / ToF
    范围: 0.2m ~ 10m
    """

    def __init__(self, sensor_id: str = "depth-01", name: str = "深度相机"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.VISION,
            body_part=BodyPart.EYE,
            description="深度视觉感知",
            precision=0.92,
            range_min=200.0,
            range_max=10000.0,
            unit="mm",
            sampling_rate_hz=30.0,
            resolution=1.0,
            interface="usb",
            power_current_ma=300.0,
        )
        super().__init__(spec)

    async def sample(self) -> Dict:
        return {
            "depth_map_size": "640x480",
            "min_depth_mm": 200,
            "max_depth_mm": 10000,
        }


# ═══════════════════════════════════════════════
# 听觉传感器 (Audio) — LAAPer 的耳朵
# ═══════════════════════════════════════════════

class MicrophoneSensor(SensorUnit):
    """麦克风 — LAAPer 的耳朵

    硬件: INMP441 / MAX9814 / SPH0645
    范围: 30Hz ~ 20kHz
    """

    def __init__(self, sensor_id: str = "mic-01", name: str = "麦克风"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.AUDIO,
            body_part=BodyPart.EAR,
            description="声音感知",
            precision=0.88,
            range_min=30.0,
            range_max=20000.0,
            unit="Hz",
            sampling_rate_hz=48000.0,
            resolution=1.0,
            interface="i2s",
            power_current_ma=2.5,
        )
        super().__init__(spec)

    async def sample(self) -> Dict:
        return {
            "type": "audio",
            "sample_rate": 48000,
            "decibels": round(random.uniform(35, 80), 1),
            "duration_ms": 100,
        }


class UltrasonicSensor(SensorUnit):
    """超声波传感器 — LAAPer 的耳朵（回声定位）

    硬件: HC-SR04 / JSN-SR04T
    范围: 2cm ~ 400cm
    """

    def __init__(self, sensor_id: str = "ultra-01", name: str = "超声波传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.PROXIMITY,
            body_part=BodyPart.EAR,
            description="超声波测距",
            precision=0.90,
            range_min=2.0,
            range_max=400.0,
            unit="cm",
            sampling_rate_hz=20.0,
            resolution=0.3,
            interface="gpio",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(random.uniform(10, 200), 1)


# ═══════════════════════════════════════════════
# 生物传感器 (Biometric) — LAAPer 的内感受
# ═══════════════════════════════════════════════

class HeartRateSensor(SensorUnit):
    """心率传感器 — LAAPer 的内感受（心跳）

    硬件: MAX30102 / AD8232 / PulseSensor
    范围: 30 ~ 220 BPM
    """

    def __init__(self, sensor_id: str = "hr-01", name: str = "心率传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.BIOMETRIC,
            body_part=BodyPart.INTEROCEPTION,
            description="感知心跳/心率",
            precision=0.92,
            range_min=30.0,
            range_max=220.0,
            unit="BPM",
            sampling_rate_hz=100.0,
            resolution=1.0,
            interface="i2c",
        )
        super().__init__(spec)

    async def sample(self) -> Dict:
        return {
            "bpm": round(random.uniform(60, 80), 0),
            "hrv": round(random.uniform(20, 60), 1),
            "spo2": round(random.uniform(95, 99), 1),
        }


class BodyTemperatureSensor(SensorUnit):
    """体温传感器 — LAAPer 的内感受（体温）

    硬件: MLX90614 / DS18B20 (medical)
    范围: 32°C ~ 43°C
    """

    def __init__(self, sensor_id: str = "body-temp-01", name: str = "体温传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.BIOMETRIC,
            body_part=BodyPart.INTEROCEPTION,
            description="感知体温",
            precision=0.98,
            range_min=32.0,
            range_max=43.0,
            unit="°C",
            sampling_rate_hz=1.0,
            resolution=0.1,
            interface="i2c",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(36.5 + random.uniform(-0.3, 0.3), 1)


# ═══════════════════════════════════════════════
# 位置传感器 (Location) — LAAPer 的方位感
# ═══════════════════════════════════════════════

class GPSSensor(SensorUnit):
    """GPS 传感器 — LAAPer 的方位感

    硬件: NEO-6M / NEO-M8N / ATGM336H
    范围: 全球
    """

    def __init__(self, sensor_id: str = "gps-01", name: str = "GPS 传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.LOCATION,
            body_part=BodyPart.VESTIBULAR,
            description="感知地理位置",
            precision=0.90,
            range_min=-90.0,
            range_max=90.0,
            unit="deg",
            sampling_rate_hz=1.0,
            resolution=0.000001,
            interface="uart",
            power_current_ma=50.0,
        )
        super().__init__(spec)

    async def sample(self) -> Dict:
        return {
            "latitude": round(39.9042 + random.uniform(-0.001, 0.001), 6),
            "longitude": round(116.4074 + random.uniform(-0.001, 0.001), 6),
            "altitude": round(44.0 + random.uniform(-1, 1), 1),
            "satellites": random.randint(4, 12),
            "hdop": round(random.uniform(0.5, 2.0), 1),
        }


# ═══════════════════════════════════════════════
# 电学传感器 (Electrical) — LAAPer 的电学感知
# ═══════════════════════════════════════════════

class CurrentSensor(SensorUnit):
    """电流传感器 — LAAPer 的电学感知

    硬件: ACS712 / INA219 / PZEM-004T
    范围: 0 ~ 30A
    """

    def __init__(self, sensor_id: str = "current-01", name: str = "电流传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.ELECTRICAL,
            body_part=BodyPart.INTEROCEPTION,
            description="感知电流",
            precision=0.92,
            range_min=0.0,
            range_max=30.0,
            unit="A",
            sampling_rate_hz=10.0,
            resolution=0.01,
            interface="i2c",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(random.uniform(0, 5), 2)


class VoltageSensor(SensorUnit):
    """电压传感器 — LAAPer 的电学感知

    硬件: 分压电阻 + ADC / INA219
    范围: 0 ~ 25V
    """

    def __init__(self, sensor_id: str = "voltage-01", name: str = "电压传感器"):
        spec = SensorSpec(
            sensor_id=sensor_id,
            name=name,
            category=SensorCategory.ELECTRICAL,
            body_part=BodyPart.INTEROCEPTION,
            description="感知电压",
            precision=0.95,
            range_min=0.0,
            range_max=25.0,
            unit="V",
            sampling_rate_hz=10.0,
            resolution=0.001,
            interface="analog",
        )
        super().__init__(spec)

    async def sample(self) -> float:
        return round(random.uniform(11.5, 12.5), 2)


# ═══════════════════════════════════════════════
# 工厂函数 — 快速创建传感器
# ═══════════════════════════════════════════════

SENSOR_REGISTRY: Dict[str, type] = {
    "temperature": TemperatureSensor,
    "humidity": HumiditySensor,
    "light": LightSensor,
    "pressure": PressureSensor,
    "gas": GasSensor,
    "noise": NoiseSensor,
    "accelerometer": AccelerometerSensor,
    "gyroscope": GyroscopeSensor,
    "motion": MotionSensor,
    "proximity": ProximitySensor,
    "touch": TouchSensor,
    "pressure_pad": PressurePadSensor,
    "camera": CameraSensor,
    "depth_camera": DepthCameraSensor,
    "microphone": MicrophoneSensor,
    "ultrasonic": UltrasonicSensor,
    "heart_rate": HeartRateSensor,
    "body_temperature": BodyTemperatureSensor,
    "gps": GPSSensor,
    "current": CurrentSensor,
    "voltage": VoltageSensor,
}


def create_sensor(sensor_type: str, sensor_id: str = "", **kwargs) -> SensorUnit:
    """创建传感器实例"""
    cls = SENSOR_REGISTRY.get(sensor_type)
    if not cls:
        raise ValueError(f"Unknown sensor type: {sensor_type}")
    if sensor_id:
        kwargs["sensor_id"] = sensor_id
    return cls(**kwargs)


def list_available_sensors() -> List[Dict]:
    """列出所有可用传感器类型"""
    return [
        {
            "type": t,
            "class": cls.__name__,
            "category": cls.__init__.__defaults__,  # 简化
        }
        for t, cls in SENSOR_REGISTRY.items()
    ]