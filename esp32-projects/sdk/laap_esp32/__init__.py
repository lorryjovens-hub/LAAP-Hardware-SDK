"""LAAP ESP32 项目库 — 统一 SDK 入口

    from laap_esp32 import (
        LDPProtocol,          # 统一接入协议（LAAP Device Protocol）
        DifferentialDrive,    # 差速底盘（机器车）
        QuadrupedGait,        # 四足步态（机械狗）
        PanTiltController,    # 云台（桌面机器人/宠物）
        LegIK,                # 单腿逆运动学
    )

设计原则：一个运动抽象，三类身体。LAAP 的指令层不需要知道
对面是轮子还是十二条腿。
"""

__version__ = "0.1.0"

from laap_esp32.protocol import (
    LDPProtocol,
    LDPMessage,
    MessageKind,
    MotionCommand,
)
from laap_esp32.motion import (
    MotionController,
    DifferentialDrive,
    PanTiltController,
    RobotSpec,
)
from laap_esp32.gait import (
    LegIK,
    LegConfig,
    QuadrupedGait,
    GaitType,
    GaitParams,
)

__all__ = [
    "LDPProtocol",
    "LDPMessage",
    "MessageKind",
    "MotionCommand",
    "MotionController",
    "DifferentialDrive",
    "PanTiltController",
    "RobotSpec",
    "LegIK",
    "LegConfig",
    "QuadrupedGait",
    "GaitType",
    "GaitParams",
]