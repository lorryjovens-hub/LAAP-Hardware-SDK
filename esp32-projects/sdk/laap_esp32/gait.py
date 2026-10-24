"""四足运动：逆运动学 + 步态生成

## 为什么四足比轮子难一个数量级

轮子：给速度就转，运动学是 2 个自由度（v, ω），PID 就够。
四足：抬腿、落足、重心转移——**每一时刻 12 个关节角都要算对**，
而且要保证支撑腿不打滑、摆动腿不绊地。

## 三层结构（和 Stanford Pupper / OpenCat 同一思路）

    ① 步态调度器 GaitScheduler
       决定「什么时候哪条腿该抬」→ 每条腿输出 (phase, stance/swing)

    ② 足端轨迹 FootTrajectory
       支撑相：足端贴地，相对机体向后平移（推着身体走）
       摆动相：足端抬起，沿椭圆/摆线从后点抬到前点

    ③ 逆运动学 LegIK
       足端位置 (x,y,z) → 三个关节角 (coxa/femur/tibia)

## 三种步态

| 步态 | 同时着地腿数 | 稳定度 | 速度 | 用途 |
|------|------------|--------|------|------|
| **Trot** | 2（对角） | 中 | 快 | 机器狗小跑，最常用 |
| **Walk** | 3 | 高 | 慢 | 稳定行走、负载、慢速巡航 |
| **Pace** | 2（同侧） | 低 | 中 | 特殊用途，容易侧翻 |

Trot 是四足机器人的"默认档"：LF+RR 一组，RF+LR 一组，对角交替，
重心投影始终落在对角支撑线上，既快又不至于翻。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════
#  单腿逆运动学
# ══════════════════════════════════════════════════════════

@dataclass
class LegConfig:
    """单腿几何参数（按你的机构量，单位 mm / 度）

    三段式：coxa（横摆） → femur（大腿） → tibia（小腿）

        coxa 沿着机体侧向伸出，决定腿的横向站距
        femur 从髋关节向下延伸
        tibia 从膝关节延伸，末端是足端
    """
    coxa: float = 40.0          # 横摆长度
    femur: float = 80.0         # 大腿
    tibia: float = 100.0        # 小腿
    # 关节安装方向（左右腿镜像时用）
    side: int = 1               # +1 右侧 / -1 左侧
    # 舵机零位偏移（标定用，度）
    offset_coxa: float = 0.0
    offset_femur: float = 0.0
    offset_tibia: float = 0.0
    # 关节限位（度）
    coxa_range: Tuple[float, float] = (-60.0, 60.0)
    femur_range: Tuple[float, float] = (-80.0, 90.0)
    tibia_range: Tuple[float, float] = (-170.0, 5.0)


class LegIK:
    """单腿逆运动学求解

    输入：足端相对髋部基座的位置 (x, y, z)
        x = 前方(+)/后方(-)
        y = 侧向（正方向由 side 决定）
        z = 高度（通常为负，向下）

    输出：(coxa_angle, femur_angle, tibia_angle) 单位度

    数学（三段式腿）：
        1) 水平投影 r = sqrt(x² + y²)
           coxa 转角 θ1 = atan2(x, y)     （绕竖直轴）
           水平剩余臂长 a = r - coxa
        2) 平面内到足端距离 D = sqrt(a² + z²)
           余弦定理求「大腿-小腿夹角」：
             θ3 = acos((L1² + L2² - D²) / (2·L1·L2))     /* 180°=伸直 */
           髋角：
             θ2 = atan2(z, a) + acos((L1² + D² - L2²) / (2·L1·D))

        3) 关节输出约定（和舵机对齐）：
             coxa  = atan2(x, y)     绕竖直轴
             femur = θ2              相对水平（负=向下）
             tibia = θ3 - 180        相对 femur 的伸直偏离（0=直，负=弯）
               这个 -180 是必须的：θ3 是内角，舵机要的是偏离量。
               写错会让足端落点偏几十毫米（本文件曾踩过）。
    """

    def __init__(self, cfg: LegConfig):
        self.cfg = cfg

    def solve(self, x: float, y: float, z: float) -> Optional[Tuple[float, float, float]]:
        """足端位置 → 三关节角（度）。不可达返回 None。"""
        L1, L2 = self.cfg.femur, self.cfg.tibia

        r = math.hypot(x, y)
        if r < 1e-6:
            r = 1e-6
        a = r - self.cfg.coxa
        if a < 0:
            a = 0.0        # 足端在横摆臂内，退化为纯上下

        D = math.hypot(a, z)

        # 可达性检查
        if D > (L1 + L2) * 0.999 or D < abs(L1 - L2) * 1.001:
            return None

        # coxa 角（绕竖直轴，从机体侧向量起）
        theta1 = math.atan2(x, y)

        # tibia（膝）角：余弦定理
        cos_knee = (L1 * L1 + L2 * L2 - D * D) / (2 * L1 * L2)
        cos_knee = max(-1.0, min(1.0, cos_knee))
        theta3 = math.acos(cos_knee)

        # femur（髋）角
        cos_hip = (L1 * L1 + D * D - L2 * L2) / (2 * L1 * D)
        cos_hip = max(-1.0, min(1.0, cos_hip))
        theta2 = math.atan2(z, a) + math.acos(cos_hip)

        # 转成度，并按舵机安装方向调整
        d1 = math.degrees(theta1) * self.cfg.side + self.cfg.offset_coxa
        d2 = math.degrees(theta2) + self.cfg.offset_femur
        # 【膝角约定】θ3 是「大腿-小腿夹角（内角）」，180° = 完全伸直。
        # 舵机要的是「偏离伸直位多少」⇒ d3 = θ3 - 180（伸直=0，弯曲为负）。
        # 之前误写成 -θ3，导致足端落点偏移最大 99mm（已用正运动学反验修正）。
        d3 = math.degrees(theta3) - 180.0 + self.cfg.offset_tibia

        # 限位
        d1 = _clamp(d1, *self.cfg.coxa_range)
        d2 = _clamp(d2, *self.cfg.femur_range)
        d3 = _clamp(d3, *self.cfg.tibia_range)
        return (d1, d2, d3)

    def neutral_pose(self, height: float = -120.0, reach: float = 60.0):
        """站立中立位：四腿撑起机体"""
        return self.solve(0.0, reach, height)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ══════════════════════════════════════════════════════════
#  步态
# ══════════════════════════════════════════════════════════

class GaitType(str, Enum):
    TROT = "trot"      # 对角：LF+RR / RF+LR（快，默认）
    WALK = "walk"      # 四拍，三腿着地（稳）
    PACE = "pace"      # 同侧：LF+LR / RF+RR（易侧翻）


# 四条腿代号与相位偏移
LEG_NAMES = ("LF", "RF", "LR", "RR")     # 左前、右前、左后、右后

# 各步态下四条腿的相位偏移（0-1 一圈）
# Trot: 对角同步  ⇒ LF,RR = 0.0；RF,LR = 0.5
# Walk: 四拍顺序  ⇒ LF 0.0 / RR 0.25 / RF 0.5 / LR 0.75
# Pace: 同侧同步  ⇒ LF,LR = 0.0；RF,RR = 0.5
GAIT_PHASE: Dict[str, Dict[str, float]] = {
    GaitType.TROT: {"LF": 0.0, "RR": 0.0, "RF": 0.5, "LR": 0.5},
    GaitType.WALK: {"LF": 0.0, "RR": 0.25, "RF": 0.5, "LR": 0.75},
    GaitType.PACE: {"LF": 0.0, "LR": 0.0, "RF": 0.5, "RR": 0.5},
}

# 各步态占空比（支撑相占一个周期的比例）
GAIT_DUTY: Dict[str, float] = {
    GaitType.TROT: 0.5,
    GaitType.WALK: 0.75,
    GaitType.PACE: 0.5,
}


@dataclass
class GaitParams:
    """步态参数"""
    step_length: float = 60.0     # 单步长度 mm
    step_height: float = 30.0     # 抬腿高度 mm
    body_height: float = 120.0    # 机体离地高度 mm（正数，内部取负 z）
    stance_reach: float = 60.0    # 腿的默认横向站距
    period_s: float = 0.5         # 步态周期（秒）


class QuadrupedGait:
    """四足步态生成器

    用法：
        gait = QuadrupedGait(GaitType.TROT, GaitParams())
        # 每 20ms 调一次（50Hz 控制循环）
        for joints in gait.step(dt=0.02, vx=50.0, vy=0.0, omega=0.0):
            # joints = {"LF": (c,f,t), ...}
    """

    def __init__(
        self,
        gait_type: GaitType = GaitType.TROT,
        params: Optional[GaitParams] = None,
        legs: Optional[Dict[str, LegConfig]] = None,
    ):
        self.gait_type = gait_type
        self.params = params or GaitParams()

        # 左右腿镜像：左腿 side=-1，右腿 side=+1
        if legs is None:
            self.legs = {
                "LF": LegConfig(side=-1), "RF": LegConfig(side=1),
                "LR": LegConfig(side=-1), "RR": LegConfig(side=1),
            }
        else:
            self.legs = legs
        self.ik = {name: LegIK(cfg) for name, cfg in self.legs.items()}

        self.phase = 0.0             # 0-1 全局相位
        self.params.period_s = max(0.08, self.params.period_s)

    # ── 主循环 ──────────────────────────────────

    def step(
        self,
        dt: float,
        vx: float = 0.0,        # 前后速度 mm/s
        vy: float = 0.0,        # 横移速度 mm/s
        omega: float = 0.0,     # 转向角速度 deg/s
    ) -> Dict[str, Optional[Tuple[float, float, float]]]:
        """推进一个控制周期，返回四腿关节角"""
        self.phase = (self.phase + dt / self.params.period_s) % 1.0

        duty = GAIT_DUTY[self.gait_type]
        offsets = GAIT_PHASE[self.gait_type]

        out: Dict[str, Optional[Tuple[float, float, float]]] = {}
        for name in LEG_NAMES:
            leg_phase = (self.phase + offsets[name]) % 1.0
            foot = self._foot_position(
                name, leg_phase, duty, vx, vy, omega,
            )
            out[name] = self.ik[name].solve(*foot)
        return out

    def _foot_position(
        self,
        name: str,
        leg_phase: float,
        duty: float,
        vx: float,
        vy: float,
        omega: float,
    ) -> Tuple[float, float, float]:
        """单腿足端相对髋部的位置

        支撑相（leg_phase < duty）：
            足端贴地，相对机体从「前」扫到「后」——身体因此前进。
        摆动相（leg_phase >= duty）：
            足端抬起，沿摆线从「后」回到「前」。
        """
        p = self.params
        base_reach = p.stance_reach
        z_ground = -p.body_height

        # 单周期内足端相对位移（由速度决定）
        dx = vx * p.period_s * duty
        dy = vy * p.period_s * duty

        # 转向：前后腿切向速度不同（简化：按腿位置加侧移）
        if abs(omega) > 1e-6:
            turn_sign = 1.0 if name.startswith("L") else -1.0
            dy += turn_sign * math.radians(omega) * p.stance_reach * 0.5 \
                  * p.period_s * duty

        if leg_phase < duty:
            # ── 支撑相：从 +half 线性扫到 -half ──
            t = leg_phase / duty              # 0→1
            x = dx * (0.5 - t)
            y = base_reach + dy * (0.5 - t)
            z = z_ground
        else:
            # ── 摆动相：抬腿回到前点（摆线：水平匀，竖直 sinusoid）──
            t = (leg_phase - duty) / (1.0 - duty)   # 0→1
            x = dx * (-0.5 + t)
            y = base_reach + dy * (-0.5 + t)
            # 正弦抬腿（起落平滑，无冲击）
            z = z_ground + p.step_height * math.sin(math.pi * t)

        return (x, y, z)

    # ── 姿态动作 ──────────────────────────────────

    def stand(self) -> Dict[str, Optional[Tuple[float, float, float]]]:
        """站立：四腿撑起，中立位"""
        return {
            n: self.ik[n].neutral_pose(
                height=-self.params.body_height,
                reach=self.params.stance_reach,
            )
            for n in LEG_NAMES
        }

    def sit(self) -> Dict[str, Optional[Tuple[float, float, float]]]:
        """坐下：后腿压低，前腿伸直（重心后移）"""
        out = {}
        for n in LEG_NAMES:
            if n.startswith("L"):   # 后腿
                out[n] = self.ik[n].solve(0.0, self.params.stance_reach,
                                          -self.params.body_height * 0.55)
            else:                   # 前腿伸展
                out[n] = self.ik[n].solve(0.0, self.params.stance_reach,
                                          -self.params.body_height * 0.95)
        return out

    def wave(self, t: float) -> Dict[str, Optional[Tuple[float, float, float]]]:
        """打招呼：右前腿抬起前后摆动（t 为时间秒）"""
        out = self.stand()
        swing = 40.0 * math.sin(t * 6.0)
        out["RF"] = self.ik["RF"].solve(
            swing, self.params.stance_reach * 0.6,
            -self.params.body_height + 90.0,
        )
        return out

    # ── 状态 ──────────────────────────────────

    def state(self) -> Dict:
        return {
            "gait": self.gait_type.value,
            "phase": round(self.phase, 3),
            "period_s": self.params.period_s,
            "duty": GAIT_DUTY[self.gait_type],
            "body_height": self.params.body_height,
        }


# ══════════════════════════════════════════════════════════
#  自检：算一条 trot 步态，看关节角是否连续合理
# ══════════════════════════════════════════════════════════

def self_test(steps: int = 25) -> Dict:
    """跑一圈 trot，检查可达性 + 关节连续性"""
    g = QuadrupedGait(GaitType.TROT, GaitParams(period_s=0.5))
    dt = 0.5 / steps
    unreachable = 0
    max_delta = 0.0
    prev = None

    for i in range(steps + 1):
        joints = g.step(dt=dt, vx=60.0)
        for name, j in joints.items():
            if j is None:
                unreachable += 1
            elif prev and prev.get(name):
                for a, b in zip(j, prev[name]):
                    max_delta = max(max_delta, abs(a - b))
        prev = joints

    return {
        "steps": steps + 1,
        "unreachable": unreachable,
        "max_joint_delta_deg": round(max_delta, 2),
        "smooth": max_delta < 40.0,
        "ok": unreachable == 0,
    }