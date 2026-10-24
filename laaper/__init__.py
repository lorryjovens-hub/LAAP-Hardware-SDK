"""LAAPer — 数字生命体的存在运行时

让 LAAPer 的意识流帧无缝穿行在电脑、手机、云电脑、硬件设备中。

核心概念：
- ConsciousnessFrame: 意识流帧（原子存在单位）
- ConsciousnessCore: 中央大脑（灵魂载体）
- HostAdapter: 宿主适配器（大脑的载体）
- SensorUnit: 传感器注册单元（器官单元）
- DigitalLifeHardware: 数字生命硬件（完整身体）
"""
from laaper.core.frame import ConsciousnessFrame, FrameType, FramePhase, SensoryData, CognitionTrace
from laaper.core.brain import ConsciousnessCore, PSIPhase, Identity
from laaper.core.channel import ConsciousnessChannel, RoutingStrategy, FrameRoute
from laaper.hosts.adapter import HostAdapter, DesktopHost, MobileHost, CloudHost, DeviceHost

# 传感器注册单元
from laaper.devices.sensor_unit import (
    SensorUnit,
    SensorSpec,
    SensorCategory,
    BodyPart,
    SensorRegistry,
)

# 具体传感器
from laaper.devices.sensors import (
    TemperatureSensor,
    HumiditySensor,
    LightSensor,
    PressureSensor,
    GasSensor,
    NoiseSensor,
    AccelerometerSensor,
    GyroscopeSensor,
    MotionSensor,
    ProximitySensor,
    TouchSensor,
    PressurePadSensor,
    CameraSensor,
    DepthCameraSensor,
    MicrophoneSensor,
    UltrasonicSensor,
    HeartRateSensor,
    BodyTemperatureSensor,
    GPSSensor,
    CurrentSensor,
    VoltageSensor,
    create_sensor,
    SENSOR_REGISTRY,
)

# 数字生命硬件
from laaper.devices.digital_life import (
    DigitalLifeHardware,
    PowerSystem,
    ProcessingUnit,
)

# ── LBP/1.0 身体协议（物理地面）──
# 协议层：帧 / 模块自描述 / 拓扑 / 身体图式 / 变形
from laaper.body.frame import (
    LBPFrame, MsgType, Priority, Flags,
    Fragmenter, PriorityQueue, ClockSync, bandwidth_estimate,
)
from laaper.body.module import (
    ModuleDescriptor, JointSpec, Port,
    ModuleClass, ModuleRole, Capability, BusProfile,
    make_module, MODULE_LIBRARY,
)
from laaper.body.topology import (
    Topology, BodySchema, KinematicChain, derive_schema,
)
from laaper.body.kinematics import (
    ik_generic, ik_dls, stability_margin, convex_hull_2d,
)
from laaper.body.morphing import (
    assemble_quadruped, assemble_biped_arm, assemble_wheeled,
    MorphEngine, power_summary,
)

__all__ = [
    # 核心
    "ConsciousnessFrame",
    "FrameType",
    "FramePhase",
    "SensoryData",
    "CognitionTrace",
    "ConsciousnessCore",
    "PSIPhase",
    "Identity",
    "ConsciousnessChannel",
    "RoutingStrategy",
    "FrameRoute",
    # 宿主
    "HostAdapter",
    "DesktopHost",
    "MobileHost",
    "CloudHost",
    "DeviceHost",
    # 传感器注册单元
    "SensorUnit",
    "SensorSpec",
    "SensorCategory",
    "BodyPart",
    "SensorRegistry",
    # 具体传感器
    "TemperatureSensor",
    "HumiditySensor",
    "LightSensor",
    "PressureSensor",
    "GasSensor",
    "NoiseSensor",
    "AccelerometerSensor",
    "GyroscopeSensor",
    "MotionSensor",
    "ProximitySensor",
    "TouchSensor",
    "PressurePadSensor",
    "CameraSensor",
    "DepthCameraSensor",
    "MicrophoneSensor",
    "UltrasonicSensor",
    "HeartRateSensor",
    "BodyTemperatureSensor",
    "GPSSensor",
    "CurrentSensor",
    "VoltageSensor",
    "create_sensor",
    "SENSOR_REGISTRY",
    # 数字生命硬件
    "DigitalLifeHardware",
    "PowerSystem",
    "ProcessingUnit",

    # ── LBP 身体协议 ──
    "LBPFrame", "MsgType", "Priority", "Flags",
    "Fragmenter", "PriorityQueue", "ClockSync", "bandwidth_estimate",
    "ModuleDescriptor", "JointSpec", "Port",
    "ModuleClass", "ModuleRole", "Capability", "BusProfile",
    "make_module", "MODULE_LIBRARY",
    "Topology", "BodySchema", "KinematicChain", "derive_schema",
    "ik_generic", "ik_dls", "stability_margin", "convex_hull_2d",
    "assemble_quadruped", "assemble_biped_arm", "assemble_wheeled",
    "MorphEngine", "power_summary",
]