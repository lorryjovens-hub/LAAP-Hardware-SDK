"""LBP/1.0 节点层 — 模块自描述（BMD: Body Module Descriptor）

## 和 USB Descriptor 的根本差别

USB descriptor 描述的是「接口」：端点数量、传输类型、功率需求。
它不关心这个设备在物理世界是什么形状。

LBP 的 BMD 描述的是「身体部件」：**几个自由度、连杆多长、质心在哪、
最大力矩多少、接口朝向如何**。

这个差别决定了一件事：**装配后的整体运动学可以自动推导出来**，
而不是人工配置。这是「变形金刚」在软件层面成立的前提。

## 关键字段

| 字段 | 为什么必需 |
|------|-----------|
| `joints[].axis/link` | 自动 FK/IK |
| `mass_kg` + `com_offset` | 自动算装配质心 → 平衡判断 |
| `ports[].normal` | 自动推拓扑 + 挂载坐标系 |
| `power_peak_mw` | 决定母线电容/线径 |
| `serial` | 身份锚定（同一个意识换身体后仍认得） |

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple

Vec3 = Tuple[float, float, float]


# ══════════════════════════════════════════════════════════
#  枚举
# ══════════════════════════════════════════════════════════

class ModuleClass(IntEnum):
    """模块大类"""
    ACTUATOR = 0x01     # 执行器（关节、电机）
    SENSOR = 0x02       # 传感器
    COMPUTE = 0x03      # 算力（大脑）
    POWER = 0x04        # 电源
    STRUCTURE = 0x05    # 结构件
    WHEEL = 0x06        # 轮式


class ModuleRole(IntEnum):
    """模块在身体里的角色"""
    SPINE = 0x01        # 躯干
    LIMB = 0x02         # 肢体（腿/臂，本身含关节）
    JOINT = 0x03        # 单关节
    END_EFFECTOR = 0x04 # 末端（足/手/夹爪）
    EYE = 0x05          # 眼（摄像头）
    EAR = 0x06          # 耳（麦克风）
    SKIN = 0x07         # 皮肤（触觉）
    BRAIN = 0x08        # 脑（主控）
    WHEEL = 0x09        # 轮
    VOICE = 0x0A        # 扬声器


class Capability(IntEnum):
    """能力位"""
    LOCOMOTION = 1 << 0     # 能移动
    MANIPULATION = 1 << 1   # 能抓取/操作
    VISION = 1 << 2         # 有视觉
    AUDITION = 1 << 3       # 有听觉
    SPEECH = 1 << 4         # 能发声
    TACTILE = 1 << 5        # 有触觉
    BALANCE = 1 << 6        # 能主动平衡
    CLIMB = 1 << 7          # 能爬
    ROLL = 1 << 8           # 能滚动（轮式）


class BusProfile(IntEnum):
    CAN = 1         # CAN FD 5Mbps 差分
    ETH = 2         # 以太网 100M/1G
    SPI = 3         # 板内 SPI


# ══════════════════════════════════════════════════════════
#  关节
# ══════════════════════════════════════════════════════════

@dataclass
class JointSpec:
    """一个旋转关节

    约定：局部坐标系 X前 Y左 Z上（世界坐标），模块挂载后由 port frame 变换。

    FK 变换链：
        T_child = T_parent · Translate(offset) · Rot(axis, q) · Translate(link)
    """
    name: str
    axis: Vec3                      # 旋转轴（单位向量，关节局部系）
    min_rad: float                  # 限位下限
    max_rad: float                  # 限位上限
    max_vel_rad_s: float = 10.0
    max_torque_nm: float = 2.0
    offset: Vec3 = (0.0, 0.0, 0.0)  # 上一连杆末端 → 关节转动中心
    link: Vec3 = (0.0, 0.0, 0.0)    # 关节转动中心 → 下一连杆末端（旋转后）

    @property
    def range_rad(self) -> float:
        return self.max_rad - self.min_rad

    def clamp(self, q: float) -> float:
        return max(self.min_rad, min(self.max_rad, q))


@dataclass
class Port:
    """一个机械对接端口"""
    pos_id: int                     # 位置编码 0-7（3 根 ID 引脚）
    normal: Vec3                    # 朝外方向（模块局部系，单位向量）
    offset: Vec3                    # 端口位置（模块局部系）
    label: str = ""                 # 人类可读，如 "front_left"

    def __str__(self) -> str:
        return f"port{self.pos_id}({self.label})" if self.label else f"port{self.pos_id}"


# ══════════════════════════════════════════════════════════
#  模块描述符
# ══════════════════════════════════════════════════════════

@dataclass
class ModuleDescriptor:
    """BMD — 模块自描述

    上电后模块通过 ENUM_ACK 上报这个结构（CAN 上分片传输）。
    """
    name: str
    cls: ModuleClass
    role: ModuleRole

    # 身份
    vendor_id: int = 0x1AAB         # LAAP 自己的 VID
    product_id: int = 0
    serial: int = 0

    # 运动学
    joints: List[JointSpec] = field(default_factory=list)

    # 拓扑
    ports: List[Port] = field(default_factory=list)

    # 物理
    mass_kg: float = 0.1
    com_offset: Vec3 = (0.0, 0.0, 0.0)     # 质心（模块局部系）
    payload_kg: float = 0.0                 # 末端负载能力
    reach_m: float = 0.0                    # 工作半径

    # 电气
    bus_profile: BusProfile = BusProfile.CAN
    bus_addr: int = 0                       # 0 = 未分配
    power_mw: int = 500                     # 稳态功耗
    power_peak_mw: int = 2000               # 峰值功耗（腿落地冲击可达 5-10×）

    # 能力
    capabilities: List[Capability] = field(default_factory=list)

    # 时间
    hw_timestamp: bool = True

    @property
    def dof(self) -> int:
        return len(self.joints)

    @property
    def has_compute(self) -> bool:
        return self.cls in (ModuleClass.COMPUTE, ModuleClass.POWER)

    def has_cap(self, cap: Capability) -> bool:
        return cap in self.capabilities

    def find_port(self, pos_id: int) -> Optional[Port]:
        for p in self.ports:
            if p.pos_id == pos_id:
                return p
        return None

    # ── 序列化（CAN 分片上限 64B，实际会用 FRAG 多帧）──
    def to_dict(self) -> dict:
        return {
            "magic": "LBMD",
            "ver": "1.0",
            "name": self.name,
            "cls": int(self.cls),
            "role": int(self.role),
            "vid": self.vendor_id,
            "pid": self.product_id,
            "serial": self.serial,
            "dof": self.dof,
            "joints": [
                {"n": j.name, "ax": j.axis, "lo": j.min_rad, "hi": j.max_rad,
                 "vel": j.max_vel_rad_s, "tq": j.max_torque_nm,
                 "off": j.offset, "lnk": j.link}
                for j in self.joints
            ],
            "ports": [
                {"id": p.pos_id, "n": p.normal, "off": p.offset, "l": p.label}
                for p in self.ports
            ],
            "mass": self.mass_kg,
            "com": self.com_offset,
            "payload": self.payload_kg,
            "reach": self.reach_m,
            "bus": int(self.bus_profile),
            "addr": self.bus_addr,
            "pw": self.power_mw,
            "pw_pk": self.power_peak_mw,
            "caps": [int(c) for c in self.capabilities],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, d: dict) -> "ModuleDescriptor":
        return cls(
            name=d["name"],
            cls=ModuleClass(d["cls"]),
            role=ModuleRole(d["role"]),
            vendor_id=d.get("vid", 0x1AAB),
            product_id=d.get("pid", 0),
            serial=d.get("serial", 0),
            joints=[
                JointSpec(j["n"], tuple(j["ax"]), j["lo"], j["hi"],
                          j.get("vel", 10.0), j.get("tq", 2.0),
                          tuple(j.get("off", (0, 0, 0))),
                          tuple(j["lnk"]))
                for j in d.get("joints", [])
            ],
            ports=[
                Port(p["id"], tuple(p["n"]), tuple(p["off"]), p.get("l", ""))
                for p in d.get("ports", [])
            ],
            mass_kg=d.get("mass", 0.1),
            com_offset=tuple(d.get("com", (0, 0, 0))),
            payload_kg=d.get("payload", 0.0),
            reach_m=d.get("reach", 0.0),
            bus_profile=BusProfile(d.get("bus", 1)),
            bus_addr=d.get("addr", 0),
            power_mw=d.get("pw", 500),
            power_peak_mw=d.get("pw_pk", 2000),
            capabilities=[Capability(c) for c in d.get("caps", [])],
        )

    def __str__(self) -> str:
        caps = ",".join(c.name for c in self.capabilities) or "-"
        return (f"BMD[{self.name}] {self.cls.name}/{self.role.name} "
                f"{self.dof}DOF {self.mass_kg}kg ports={len(self.ports)} caps={caps}")


# ══════════════════════════════════════════════════════════
#  标准模块库（这些数值对应真实能买到的件）
# ══════════════════════════════════════════════════════════

def deg(d: float) -> float:
    import math
    return math.radians(d)


def make_power_core(mass_kg: float = 0.45) -> ModuleDescriptor:
    """躯干 + 电源 + 主控一体模块

    物理：120×80×40mm 铝壳，内含 48V→12V/5V/3.3V DC-DC、
          ESP32-S3 主控、CAN 收发器、100BASE-TX PHY

    6 个端口：
      port0-3 底面四角 → 腿（朝下）
      port4-5 左右两侧 → 臂（朝外）
    """
    return ModuleDescriptor(
        name="power_core",
        cls=ModuleClass.POWER,
        role=ModuleRole.SPINE,
        product_id=0x0001,
        mass_kg=mass_kg,
        com_offset=(0.0, 0.0, 0.0),
        power_mw=800,
        power_peak_mw=2500,
        bus_profile=BusProfile.CAN,
        capabilities=[Capability.BALANCE],
        ports=[
            # 底面四角，朝下
            Port(0, (0, 0, -1), (+0.06, +0.08, -0.03), "front_left"),
            Port(1, (0, 0, -1), (+0.06, -0.08, -0.03), "front_right"),
            Port(2, (0, 0, -1), (-0.06, +0.08, -0.03), "rear_left"),
            Port(3, (0, 0, -1), (-0.06, -0.08, -0.03), "rear_right"),
            # 左右两侧，朝外
            Port(4, (0, +1, 0), (0.0, +0.10, +0.02), "left_side"),
            Port(5, (0, -1, 0), (0.0, -0.10, +0.02), "right_side"),
        ],
    )


def make_leg_3dof(mass_kg: float = 0.28) -> ModuleDescriptor:
    """3 自由度腿：髋外展 + 髋屈伸 + 膝屈伸

    物理：3× 微型无刷 + 行星减速，连杆 90mm + 100mm，
          末端橡胶足（直径 30mm）

    局部系 +Z 朝外（挂载在底面时 = 世界向下）
    零位时足端位于 (0, 0, 0.21)
    """
    return ModuleDescriptor(
        name="leg_3dof",
        cls=ModuleClass.ACTUATOR,
        role=ModuleRole.LIMB,
        product_id=0x0010,
        mass_kg=mass_kg,
        com_offset=(0.0, 0.0, 0.09),
        reach_m=0.19,
        power_mw=900,
        power_peak_mw=9000,          # 落地冲击可达 10×
        capabilities=[],
        joints=[
            # 髋外展：绕局部 X（= 世界前向），带动整腿左右摆
            JointSpec("hip_abduct", (1, 0, 0), deg(-30), deg(30),
                      max_vel_rad_s=6.0, max_torque_nm=8.0,
                      offset=(0, 0, 0.02), link=(0, 0, 0.02)),
            # 髋屈伸：绕局部 Y（= 世界右向）
            JointSpec("hip_pitch", (0, 1, 0), deg(-45), deg(90),
                      max_vel_rad_s=12.0, max_torque_nm=12.0,
                      offset=(0, 0, 0), link=(0, 0, 0.09)),
            # 膝：与髋同轴方向
            JointSpec("knee", (0, 1, 0), deg(-150), deg(0),
                      max_vel_rad_s=14.0, max_torque_nm=9.0,
                      offset=(0, 0, 0), link=(0, 0, 0.10)),
        ],
        ports=[
            # 末端可以再接足垫/轮（角色转换）
            Port(0, (0, 0, 1), (0, 0, 0.21), "foot_mount"),
        ],
    )


def make_arm_4dof(mass_kg: float = 0.42) -> ModuleDescriptor:
    """4 自由度臂：肩偏航 + 肩俯仰 + 肘 + 腕滚

    局部系 +Z 朝外（挂在侧面时 = 世界向左/右）
    零位末端位于 (0, 0, 0.27)
    """
    return ModuleDescriptor(
        name="arm_4dof",
        cls=ModuleClass.ACTUATOR,
        role=ModuleRole.LIMB,
        product_id=0x0020,
        mass_kg=mass_kg,
        com_offset=(0.0, 0.0, 0.13),
        payload_kg=1.2,
        reach_m=0.27,
        power_mw=1100,
        power_peak_mw=6000,
        capabilities=[Capability.MANIPULATION],
        joints=[
            JointSpec("shoulder_yaw", (0, 0, 1), deg(-90), deg(90),
                      max_vel_rad_s=6.0, max_torque_nm=6.0,
                      offset=(0, 0, 0.03), link=(0, 0, 0.02)),
            JointSpec("shoulder_pitch", (1, 0, 0), deg(-90), deg(90),
                      max_vel_rad_s=8.0, max_torque_nm=8.0,
                      offset=(0, 0, 0), link=(0, 0, 0.10)),
            JointSpec("elbow", (1, 0, 0), deg(-140), deg(0),
                      max_vel_rad_s=10.0, max_torque_nm=5.0,
                      offset=(0, 0, 0), link=(0, 0, 0.09)),
            JointSpec("wrist_roll", (0, 0, 1), deg(-180), deg(180),
                      max_vel_rad_s=15.0, max_torque_nm=1.5,
                      offset=(0, 0, 0), link=(0, 0, 0.03)),
        ],
        ports=[
            Port(0, (0, 0, 1), (0, 0, 0.27), "hand_mount"),
        ],
    )


def make_wheel_module(mass_kg: float = 0.16) -> ModuleDescriptor:
    """驱动轮：1 自由度

    物理：N20 减速电机 + 65mm 橡胶轮
    局部 +Z 朝下（挂载在底面时轮子着地）
    """
    return ModuleDescriptor(
        name="wheel_m2",
        cls=ModuleClass.WHEEL,
        role=ModuleRole.WHEEL,
        product_id=0x0030,
        mass_kg=mass_kg,
        com_offset=(0, 0, 0.03),
        power_mw=400,
        power_peak_mw=3000,
        capabilities=[Capability.LOCOMOTION, Capability.ROLL],
        joints=[
            # 轮绕局部 Y 旋转（滚动）
            JointSpec("roll", (0, 1, 0), deg(-100000), deg(100000),
                      max_vel_rad_s=60.0, max_torque_nm=1.2,
                      offset=(0, 0, 0.0325), link=(0, 0, 0)),
        ],
        ports=[],
    )


def make_camera_head(mass_kg: float = 0.14) -> ModuleDescriptor:
    """2 自由度云台摄像头"""
    return ModuleDescriptor(
        name="head_2dof",
        cls=ModuleClass.SENSOR,
        role=ModuleRole.EYE,
        product_id=0x0040,
        mass_kg=mass_kg,
        com_offset=(0, 0, 0.04),
        power_mw=350,
        power_peak_mw=600,
        capabilities=[Capability.VISION],
        joints=[
            JointSpec("pan", (0, 0, 1), deg(-90), deg(90),
                      max_vel_rad_s=6.0, max_torque_nm=1.0,
                      offset=(0, 0, 0.02), link=(0, 0, 0.02)),
            JointSpec("tilt", (1, 0, 0), deg(-30), deg(60),
                      max_vel_rad_s=6.0, max_torque_nm=1.0,
                      offset=(0, 0, 0), link=(0, 0, 0.03)),
        ],
        ports=[
            Port(0, (0, 0, 1), (0, 0, 0.07), "lens"),
        ],
    )


def make_speaker_module(mass_kg: float = 0.08) -> ModuleDescriptor:
    """扬声器模块（嘴）"""
    return ModuleDescriptor(
        name="speaker",
        cls=ModuleClass.SENSOR,
        role=ModuleRole.VOICE,
        product_id=0x0050,
        mass_kg=mass_kg,
        power_mw=200,
        power_peak_mw=2000,
        capabilities=[Capability.SPEECH],
    )


def make_gripper_module(mass_kg: float = 0.10) -> ModuleDescriptor:
    """夹爪末端（手）"""
    return ModuleDescriptor(
        name="gripper_2f",
        cls=ModuleClass.ACTUATOR,
        role=ModuleRole.END_EFFECTOR,
        product_id=0x0060,
        mass_kg=mass_kg,
        payload_kg=1.0,
        power_mw=250,
        power_peak_mw=1200,
        capabilities=[Capability.MANIPULATION],
        joints=[
            JointSpec("jaw", (0, 1, 0), deg(0), deg(60),
                      max_vel_rad_s=20.0, max_torque_nm=1.0,
                      offset=(0, 0, 0.02), link=(0, 0, 0.02)),
        ],
    )


# 标准模块库
MODULE_LIBRARY = {
    "power_core": make_power_core,
    "leg_3dof": make_leg_3dof,
    "arm_4dof": make_arm_4dof,
    "wheel_m2": make_wheel_module,
    "head_2dof": make_camera_head,
    "speaker": make_speaker_module,
    "gripper": make_gripper_module,
}


def make_module(name: str, **kwargs) -> ModuleDescriptor:
    """从库中造一个模块（可覆盖默认参数）"""
    fn = MODULE_LIBRARY.get(name)
    if not fn:
        raise KeyError(f"未知模块: {name}（可用: {list(MODULE_LIBRARY)}）")
    return fn(**kwargs)