"""运动抽象层 — 一个接口，三类身体

LAAP 的指令层只说「前进/转向/坐下/打招呼」，不需要知道
对面是轮子、四条腿还是云台。

    MotionController（抽象）
      ├─ DifferentialDrive   差速底盘（机器车）
      ├─ QuadrupedGait       四足步态（机械狗）——见 gait.py
      └─ PanTiltController   云台/头部（桌面宠物、桌面机器人）
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


@dataclass
class RobotSpec:
    """机器人规格（决定运动学参数）"""
    kind: str = "car"                  # car / dog / pet / arm
    name: str = "LAAP Robot"

    # 底盘
    wheel_radius_mm: float = 35.0
    wheel_base_mm: float = 180.0       # 两轮间距（差速）
    max_speed_mm_s: float = 400.0
    max_yaw_deg_s: float = 120.0

    # 云台（宠物/桌面机器人）
    pan_range: Tuple[float, float] = (-90.0, 90.0)
    tilt_range: Tuple[float, float] = (-30.0, 60.0)

    # 舵机映射：关节名 → (通道号, 零位偏移, 方向)
    servo_map: Dict[str, Tuple[int, float, int]] = field(default_factory=dict)


class MotionController(ABC):
    """运动控制抽象基类

    所有机器人实现同一套动词：
        move(vx, vy, omega)   速度控制（mm/s, mm/s, deg/s）
        pose(name)            命名姿态（stand/sit/wave/home）
        stop()                急停
        state()               当前运动状态
        tick(dt)              控制周期推进（返回待下发的舵机/电机指令）
    """

    def __init__(self, spec: RobotSpec):
        self.spec = spec
        self._vx = 0.0
        self._vy = 0.0
        self._omega = 0.0

    @abstractmethod
    def move(self, vx: float = 0.0, vy: float = 0.0, omega: float = 0.0) -> None:
        """设定速度指令"""

    @abstractmethod
    def pose(self, name: str) -> bool:
        """切换命名姿态，成功返回 True"""

    @abstractmethod
    def tick(self, dt: float) -> Dict:
        """推进一个控制周期，返回硬件指令"""

    def stop(self) -> None:
        self._vx = self._vy = self._omega = 0.0

    def state(self) -> Dict:
        return {
            "kind": self.spec.kind,
            "vx": round(self._vx, 1),
            "vy": round(self._vy, 1),
            "omega": round(self._omega, 1),
        }


# ══════════════════════════════════════════════════════════
#  ① 差速底盘（机器车）
# ══════════════════════════════════════════════════════════

class DifferentialDrive(MotionController):
    """两轮差速驱动 + 编码器闭环

    ## 运动学（简单但够用）

        v_left  = vx - omega * (wheel_base/2)
        v_right = vx + omega * (wheel_base/2)

    每个轮子的角速度：
        ω_wheel = v_wheel / wheel_radius

    ## 为什么还需要 PID

    开环直接给 PWM，实际速度受电池电压、地面摩擦、负载影响，
    跑直线会偏。所以标准做法（micro-ROS 差速车都是这套）：

        目标速度 → PID → PWM → 电机
                    ↑
                编码器实测（每 20ms 算一次速度）

    本类输出「目标轮速」，PID 在固件侧闭环（见 firmware）。
    """

    def __init__(self, spec: Optional[RobotSpec] = None):
        super().__init__(spec or RobotSpec(kind="car"))

    def move(self, vx: float = 0.0, vy: float = 0.0, omega: float = 0.0) -> None:
        # 差速底盘没有横移能力，vy 忽略
        mx = self.spec.max_speed_mm_s
        my = self.spec.max_yaw_deg_s
        self._vx = max(-mx, min(mx, vx))
        self._vy = 0.0
        self._omega = max(-my, min(my, omega))

    def pose(self, name: str) -> bool:
        # 车没有姿态，只有停车
        if name in ("stop", "home", "stand"):
            self.stop()
            return True
        return False

    def tick(self, dt: float) -> Dict:
        half = self.spec.wheel_base_mm / 2.0
        # omega(deg/s) → rad/s
        w_rad = math.radians(self._omega)
        v_left = self._vx - w_rad * half
        v_right = self._vx + w_rad * half

        r = self.spec.wheel_radius_mm
        wl = v_left / r            # rad/s
        wr = v_right / r

        return {
            "type": "differential",
            "target_left_mm_s": round(v_left, 1),
            "target_right_mm_s": round(v_right, 1),
            # 固件侧 PID 拿这个当 setpoint
            "target_left_rad_s": round(wl, 3),
            "target_right_rad_s": round(wr, 3),
        }

    def odometry(self, dt: float, left_mm_s: float, right_mm_s: float,
                 pose: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """里程计：由编码器实测速度积分出位姿 (x, y, theta_deg)"""
        x, y, th = pose
        v = (left_mm_s + right_mm_s) / 2.0
        w = (right_mm_s - left_mm_s) / self.spec.wheel_base_mm   # rad/s
        th_rad = math.radians(th) + w * dt
        x += v * math.cos(th_rad) * dt
        y += v * math.sin(th_rad) * dt
        return (x, y, math.degrees(th_rad) % 360.0)


# ══════════════════════════════════════════════════════════
#  ② 云台（桌面宠物 / 桌面机器人的头）
# ══════════════════════════════════════════════════════════

class PanTiltController(MotionController):
    """双轴云台：左右（pan）+ 上下（tilt）

    桌面机器人的「注意力」就靠它表达：
        说话看着你 → pan/tilt 转向人脸
        思考 → 微微偏头
        开心 → 快速小幅摆动
        睡觉 → 低头

    这些是「生命感」的来源，比屏幕动画更有说服力。
    """

    def __init__(self, spec: Optional[RobotSpec] = None):
        super().__init__(spec or RobotSpec(kind="pet"))
        self.pan = 0.0
        self.tilt = 0.0
        self._target_pan = 0.0
        self._target_tilt = 0.0
        self._smoothing = 0.25        # 一阶低通系数（越小越柔）

    def move(self, vx: float = 0.0, vy: float = 0.0, omega: float = 0.0) -> None:
        # 对云台而言：vx→tilt 速度，vy→pan 速度，omega→快速回中
        self._target_tilt += vx * 0.02
        self._target_pan += vy * 0.02
        if abs(omega) > 0.01:
            self._target_pan = 0.0
            self._target_tilt = 0.0
        self.look_at_angles(self._target_pan, self._target_tilt)

    def look_at_angles(self, pan: float, tilt: float) -> None:
        lo, hi = self.spec.pan_range
        self._target_pan = max(lo, min(hi, pan))
        lo, hi = self.spec.tilt_range
        self._target_tilt = max(lo, min(hi, tilt))

    def look_at(self, dx: float, dy: float, distance: float = 500.0) -> None:
        """看向一个人/物体：给相对坐标（mm），自动算角度"""
        pan = math.degrees(math.atan2(dx, max(1.0, distance)))
        tilt = math.degrees(math.atan2(-dy, max(1.0, distance)))
        self.look_at_angles(pan, tilt)

    def pose(self, name: str) -> bool:
        presets = {
            "home": (0.0, 0.0),
            "look_up": (0.0, 25.0),
            "look_down": (0.0, -25.0),
            "think": (15.0, 12.0),
            "sleep": (0.0, -28.0),
            "nod": (0.0, 0.0),
        }
        if name not in presets:
            return False
        pan, tilt = presets[name]
        self.look_at_angles(pan, tilt)
        return True

    def tick(self, dt: float) -> Dict:
        # 一阶低通，让动作不生硬（生命感的关键）
        a = self._smoothing
        self.pan += (self._target_pan - self.pan) * a
        self.tilt += (self._target_tilt - self.tilt) * a
        return {
            "type": "pantilt",
            "pan_deg": round(self.pan, 1),
            "tilt_deg": round(self.tilt, 1),
        }

    def state(self) -> Dict:
        d = super().state()
        d.update({"pan": round(self.pan, 1), "tilt": round(self.tilt, 1)})
        return d


# ══════════════════════════════════════════════════════════
#  ③ 四足（包装 gait.py，统一到 MotionController 接口）
# ══════════════════════════════════════════════════════════

class QuadrupedMotion(MotionController):
    """四足运动控制器（统一接口版）

    把 QuadrupedGait 的动作包成 move()/pose()/tick()。
    """

    def __init__(self, spec: Optional[RobotSpec] = None,
                 gait_type=None, params=None):
        super().__init__(spec or RobotSpec(kind="dog"))
        from laap_esp32.gait import QuadrupedGait, GaitType, GaitParams
        self.gait = QuadrupedGait(
            gait_type or GaitType.TROT,
            params or GaitParams(),
        )
        self._pending_pose: Optional[str] = None
        self._pose_t = 0.0

    def move(self, vx: float = 0.0, vy: float = 0.0, omega: float = 0.0) -> None:
        mx = self.spec.max_speed_mm_s
        self._vx = max(-mx, min(mx, vx))
        self._vy = max(-mx, min(mx, vy))
        self._omega = max(-self.spec.max_yaw_deg_s,
                          min(self.spec.max_yaw_deg_s, omega))
        self._pending_pose = None      # 移动取消姿态

    def pose(self, name: str) -> bool:
        if name in ("stand", "sit", "home"):
            self._pending_pose = name
            self._pose_t = 0.0
            self.stop()
            return True
        if name == "wave":
            self._pending_pose = "wave"
            self._pose_t = 0.0
            return True
        return False

    def tick(self, dt: float) -> Dict:
        self._pose_t += dt

        if self._pending_pose == "stand" or self._pending_pose == "home":
            joints = self.gait.stand()
        elif self._pending_pose == "sit":
            joints = self.gait.sit()
        elif self._pending_pose == "wave":
            joints = self.gait.wave(self._pose_t)
            if self._pose_t > 2.0:      # 挥手 2 秒后回站立
                self._pending_pose = None
        else:
            joints = self.gait.step(
                dt=dt, vx=self._vx, vy=self._vy, omega=self._omega,
            )

        return {
            "type": "quadruped",
            "gait": self.gait.gait_type.value,
            "phase": round(self.gait.phase, 3),
            "joints": {k: (None if v is None else
                           [round(a, 1) for a in v])
                       for k, v in joints.items()},
        }

    def state(self) -> Dict:
        d = super().state()
        d.update(self.gait.state())
        return d


# ══════════════════════════════════════════════════════════
#  工厂
# ══════════════════════════════════════════════════════════

def make_controller(kind: str, spec: Optional[RobotSpec] = None) -> MotionController:
    """按类型创建运动控制器"""
    k = kind.lower()
    if k in ("car", "wheel", "tank"):
        return DifferentialDrive(spec)
    if k in ("dog", "quadruped", "4leg"):
        return QuadrupedMotion(spec)
    if k in ("pet", "desktop", "pantilt", "head"):
        return PanTiltController(spec)
    raise ValueError(f"未知机器人类型: {kind}")