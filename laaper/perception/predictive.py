"""预测编码感知 — 让设备报告"惊讶"，而不是报告数字

## 为什么这是根本性的不同

现在的实现是：

    温度计 22.5°C → 编码成"凉爽" → 上报 → LAAP 处理
    温度计 22.6°C → 编码成"凉爽" → 上报 → LAAP 处理
    温度计 22.5°C → 编码成"凉爽" → 上报 → LAAP 处理
    ... 每秒 10 次，全是废数据

生物不是这样工作的。大脑皮层是一个**层级预测机器**（Rao & Ballard 1999）：
每一层都在预测下一层的输入，**上行只传预测不了的部分**。

    "我预测 22.5°C" → 实测 22.5°C → 误差 0 → 什么都不报
    "我预测 22.5°C" → 实测 31.0°C → 误差 8.5 → 大声报告

这一个改变带来三件事，都不需要额外实现：

1. **稀疏上行**：静止场景带宽降 90%+
2. **注意力免费**：预测误差的绝对值天然就是显著性，不需要另做注意力机制
3. **异常检测免费**：突发的大误差就是异常

## 实现要点

线性预测器 + 卡尔曼式方差更新：

    pred     = level + velocity · dt        （外推）
    err      = obs - pred                   （预测误差）
    gain     = variance / (variance + noise) （卡尔曼增益）
    level   += gain · err                   （修正）
    velocity += α · err / dt                （学习趋势）
    variance  = (1 - gain) · variance + Q   （不确定性演化）

    surprise = |err| / sqrt(variance)       （标准化误差 = 惊讶度）

**关键**：方差会自适应。如果一个传感器一直很吵（方差大），
同样的绝对误差不算惊讶；如果一直很稳（方差小），小偏差就是大惊吓。
这就是"习惯化"（habituation）——生物感知的基本特性。

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════
#  预测结果
# ══════════════════════════════════════════════════════════

@dataclass
class Prediction:
    """一次预测编码的输出"""
    name: str
    observed: float
    predicted: float
    error: float            # 有符号预测误差（瞬时）
    surprise: float         # 标准化惊讶度（|err|/σ），无量纲
    variance: float         # 当前不确定性
    trace: float            # 余韵（衰减后的历史痕迹）
    drift: float = 0.0      # 相对慢基线的漂移（累积变化）
    drift_sigma: float = 0.0  # 漂移的显著性（|drift|/noise，无量纲）

    @property
    def worth_reporting(self) -> bool:
        """是否值得上行（默认 2σ）"""
        return self.surprise >= 2.0

    @property
    def noteworthy(self) -> bool:
        """是否值得写进感知描述

        两条路：瞬时惊讶（突发）或 累积漂移（持续变化）
        只靠惊讶会漏掉「人慢慢走来」这类事件。
        """
        return self.surprise >= 2.0 or self.drift_sigma >= 3.0

    @property
    def direction(self) -> str:
        if self.error > 0:
            return "up"
        if self.error < 0:
            return "down"
        return "none"

    def to_payload(self) -> dict:
        """上行用的精简载荷 —— 只传误差，不传原始值"""
        return {
            "sensor": self.name,
            "surprise": round(self.surprise, 3),
            "error": round(self.error, 4),
            "drift": round(self.drift, 4),
            "dir": self.direction,
        }


# ══════════════════════════════════════════════════════════
#  预测编码传感器
# ══════════════════════════════════════════════════════════

@dataclass
class SensorProfile:
    """传感器的物理特性（决定预测器参数）"""
    name: str
    unit: str = ""
    noise: float = 0.02          # 观测噪声（传感器本身的抖动）
    process_noise: float = 0.005  # 过程噪声（世界的自然变化）
    learn_rate: float = 0.25      # 趋势学习率
    trace_tau: float = 1.0        # 余韵时间常数（秒）
    report_sigma: float = 2.0     # 上报阈值（多少 σ 才算惊讶）


class PredictiveSensor:
    """预测编码传感器

    用法：
        s = PredictiveSensor(SensorProfile("temperature", "°C", noise=0.05))
        p = s.step(22.5, dt=0.1)
        if p.worth_reporting:
            send(p.to_payload())     # 只在上报时才发
    """

    def __init__(self, profile: SensorProfile):
        self.p = profile
        self.level: Optional[float] = None   # 当前估计
        self.velocity: float = 0.0           # 趋势（一阶导）
        self.variance: float = 1.0           # 不确定性
        self.trace: float = 0.0              # 余韵
        self.baseline: Optional[float] = None  # 慢基线（"本来是什么状态"）
        self.samples: int = 0

        # 统计
        self.reports: int = 0
        self.total: int = 0
        self.recent_surprises: List[float] = []

    # ── 核心 ──
    def step(self, observed: float, dt: float = 0.1) -> Prediction:
        if dt <= 0:
            dt = 1e-3

        # 首次观测：直接建立基线，不算惊讶
        if self.level is None:
            self.level = observed
            self.baseline = observed
            self.variance = self.p.noise ** 2
            self.samples = 1
            self.total += 1
            return Prediction(self.p.name, observed, observed, 0.0, 0.0,
                              self.variance, 0.0, 0.0)

        # 1. 线性外推预测
        predicted = self.level + self.velocity * dt

        # 2. 预测误差
        error = observed - predicted

        # 3. 卡尔曼式更新
        gain = self.variance / (self.variance + self.p.noise ** 2 + 1e-12)
        self.level = predicted + gain * error
        self.velocity += self.p.learn_rate * error / dt
        # 限制趋势漂移（防跑飞）
        max_v = max(abs(observed), 1.0) * 10.0
        self.velocity = max(-max_v, min(max_v, self.velocity))
        self.variance = (1 - gain) * self.variance + self.p.process_noise ** 2
        # 方差下限：不能比传感器噪声更自信（否则数值失真）
        vfloor = (self.p.noise * 0.5) ** 2
        if self.variance < vfloor:
            self.variance = vfloor

        # 4. 标准化惊讶度
        sigma = math.sqrt(self.variance) + 1e-9
        surprise = abs(error) / sigma

        # 5. 余韵：指数衰减 + 当前输入
        decay = math.exp(-dt / max(self.p.trace_tau, 1e-3))
        self.trace = self.trace * decay + observed * (1 - decay)

        # 6. 慢基线：双时间尺度（快预测 + 慢状态）
        #    为什么需要：快速预测器会把"持续变化"学成趋势，
        #    于是"人持续走近"这类事件在瞬时误差上消失。
        #    慢基线保持"本来是什么状态"，漂移量就能抓住累积变化。
        b_tau = max(self.p.trace_tau * 5.0, 5.0)
        b_decay = math.exp(-dt / b_tau)
        self.baseline = self.baseline * b_decay + observed * (1 - b_decay)
        drift = self.level - self.baseline
        drift_sigma = abs(drift) / max(self.p.noise, 1e-6)

        self.samples += 1
        self.total += 1
        self.recent_surprises.append(surprise)
        if len(self.recent_surprises) > 64:
            self.recent_surprises.pop(0)

        pred = Prediction(self.p.name, observed, predicted, error,
                          surprise, self.variance, self.trace, drift, drift_sigma)
        if surprise >= self.p.report_sigma:
            self.reports += 1
        return pred

    # ── 诊断 ──
    @property
    def report_ratio(self) -> float:
        """上报比例 —— 这个数字越低，说明预测越准、省下的带宽越多"""
        return self.reports / self.total if self.total else 0.0

    @property
    def baseline_surprise(self) -> float:
        """近期平均惊讶度（习惯化的度量）"""
        if not self.recent_surprises:
            return 0.0
        return sum(self.recent_surprises) / len(self.recent_surprises)

    def reset_baseline(self) -> None:
        """环境突变后重设基线（例如换房间）"""
        self.level = None
        self.baseline = None
        self.velocity = 0.0
        self.variance = 1.0


# ══════════════════════════════════════════════════════════
#  默认传感器配置（对应硬件上真实会有的东西）
# ══════════════════════════════════════════════════════════

DEFAULT_PROFILES: Dict[str, SensorProfile] = {
    # 触摸：噪声低、变化快、余韵长（摸完还留感觉）
    "touch":     SensorProfile("touch", "",       noise=0.01, process_noise=0.01,
                               learn_rate=0.4, trace_tau=2.0, report_sigma=1.5),
    # 温度：慢变、噪声小、余韵很长
    "temperature": SensorProfile("temperature", "°C", noise=0.05, process_noise=0.01,
                                 learn_rate=0.1, trace_tau=30.0),
    # 距离：快变、噪声中、余韵短
    "distance":  SensorProfile("distance", "cm",  noise=1.5, process_noise=0.8,
                               learn_rate=0.35, trace_tau=0.4),
    # 光照：中速、噪声中
    "light":     SensorProfile("light", "lux",    noise=8.0, process_noise=3.0,
                               learn_rate=0.2, trace_tau=0.8),
    # 声音：快变、噪声大、余韵中等（回响）
    "audio":     SensorProfile("audio", "dB",     noise=2.0, process_noise=1.5,
                               learn_rate=0.45, trace_tau=1.2),
    # 压力：类似触摸
    "pressure":  SensorProfile("pressure", "N",   noise=0.05, process_noise=0.02,
                               learn_rate=0.4, trace_tau=1.5),
    # IMU：极快变、噪声大
    "imu":       SensorProfile("imu", "g",        noise=0.02, process_noise=0.05,
                               learn_rate=0.5, trace_tau=0.2),
    # 电量：极慢，几乎不惊讶
    "battery":   SensorProfile("battery", "%",    noise=0.3, process_noise=0.01,
                               learn_rate=0.05, trace_tau=60.0, report_sigma=3.0),
}


def make_sensor(name: str, **overrides) -> PredictiveSensor:
    """按名字造一个传感器（可覆盖参数）"""
    prof = DEFAULT_PROFILES.get(name, SensorProfile(name))
    if overrides:
        d = dict(prof.__dict__)
        d.update(overrides)
        prof = SensorProfile(**d)
    return PredictiveSensor(prof)
