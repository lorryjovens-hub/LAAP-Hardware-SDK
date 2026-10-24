"""生命感知场 — 把预测编码、可供性、主动探索、内感受调制成一个整体

## 三个突破点

### 1. 可供性优先于识别（Affordance over Recognition）

Gibson 的直接知觉理论：生物看到椅子，感知的不是"几何体+材质"，
而是"可以坐的东西"。**可供性是感知的一部分，不是推理的结果。**

传统机器人：
    传感器 → 世界模型 → 规划 → 动作         （4 层，延迟高）

生命体：
    传感器 → 可供性 → 动作                  （2 层，直接）

我们输出 `Affordance(action="look_at", target="热源", urgency=0.8)`，
而不是 `{"object": "person", "pos": (1.2, 0.4)}`。

### 2. 主动感知（Active Inference）

这是最关键的分界线。**被动的设备等指令，「活的东西」会主动动一下把世界看清楚。**

    视觉模糊      → 云台微转（视差消歧）
    声音方位不明  → 左右扫描
    距离读数抖动  → 靠近一点确认
    温度梯度平缓  → 移动探测

判据是信息增益：

    explore_gain = surprise × (1 − localization_confidence)

**两者都高才值得动**：既惊讶（有事发生）又不知道在哪（信息不足）。
只有一个传感器惊讶时 localization 低 → 值得转头找；
多个传感器同时指向同一方向时 localization 高 → 已经知道在哪，不用找。

### 3. 内感受调制（Interoceptive Gain）

情绪不是感知的产物，它**调制感知本身**。累的时候看什么都迟钝，
被摸过之后对触摸特别敏感。

    effective_surprise = surprise × gain(energy, arousal, modality)

这在生物学上叫增益调制（gain modulation），是注意力的物理基础。

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .predictive import Prediction, PredictiveSensor, make_sensor


# ══════════════════════════════════════════════════════════
#  可供性
# ══════════════════════════════════════════════════════════

class Action(str, Enum):
    """可供的动作 —— 这是感知层的输出词汇"""
    LOOK_AT = "look_at"           # 转向某处
    LOOK_AWAY = "look_away"       # 转开（刺眼/不悦）
    RESPOND_AFFECTION = "respond_affection"  # 回应亲昵（被摸）
    APPROACH = "approach"         # 靠近
    BACK_OFF = "back_off"         # 退开
    ORIENT = "orient"             # 朝向刺激源
    SCAN = "scan"                 # 左右扫视
    REBALANCE = "rebalance"       # 保持平衡
    REST = "rest"                 # 休息（省电）
    IDLE = "idle"


@dataclass
class Affordance:
    """一个可供性 —— 「我能对它做什么」"""
    action: Action
    target: str
    urgency: float = 0.5          # 0-1，多急
    confidence: float = 0.7       # 0-1，多确定
    reason: str = ""

    def __str__(self) -> str:
        return (f"{self.action.value}({self.target}) "
                f"urg={self.urgency:.2f} conf={self.confidence:.2f}")


# ══════════════════════════════════════════════════════════
#  内感受（身体状态）
# ══════════════════════════════════════════════════════════

@dataclass
class Interoception:
    """身体内部状态 —— 调制感知增益"""
    energy: float = 1.0       # 电量 0-1
    arousal: float = 0.5      # 唤醒度 0-1
    valence: float = 0.0      # 愉悦度 -1..1
    touch_recent: float = 0.0 # 最近被摸的程度 0-1（余韵）

    def gain(self, modality: str) -> float:
        """该感官通道的增益

        低电量 → 整体迟钝（省电策略）
        高唤醒 → 视觉/听觉更敏锐
        被摸过 → 触摸更敏感
        """
        # 基础增益：体力越低越迟钝（0.5 底限，不能完全没反应）
        base = 0.5 + 0.5 * self.energy

        # 唤醒度调制视听觉
        if modality in ("light", "audio"):
            base *= 0.8 + 0.4 * self.arousal

        # 触摸：余韵让它更敏感
        if modality == "touch":
            base *= 1.0 + 0.8 * self.touch_recent

        # 愉悦时整体更活跃
        base *= 1.0 + 0.2 * max(0.0, self.valence)

        return max(0.3, min(2.0, base))

    def tick(self, dt: float) -> None:
        """余韵衰减 + 唤醒度回归基线"""
        self.touch_recent *= math.exp(-dt / 2.0)
        # 唤醒度缓慢回落到 0.5
        self.arousal += (0.5 - self.arousal) * (1 - math.exp(-dt / 20.0))


# ══════════════════════════════════════════════════════════
#  主动探索
# ══════════════════════════════════════════════════════════

@dataclass
class ExploreAction:
    """一个主动感知动作"""
    kind: str                 # turn / scan / approach / saccade
    direction: str            # left / right / front / up / down
    expected_gain: float      # 预期信息增益
    reason: str = ""

    def __str__(self) -> str:
        return f"explore:{self.kind}→{self.direction} gain={self.expected_gain:.2f}"


class ActivePerceiver:
    """主动感知 —— 决定「动一下」是否值得

    核心判据：
        explore_gain = surprise × (1 − localization_confidence)

    光惊讶不够（不知道在哪 → 该找）
    光知道在哪也不够（不惊讶 → 没必要动）

    定位置信度怎么算？不是看"空间方向是否一致"（那太严），
    而是看「多个感官是否共同支撑同一个情境假设」。
    距离降 + 温度升 + 声音升 同时出现 → 已经是"人走近"了，方位已知，不用扫。
    """

    # 各传感器对应的空间信息（单独出现时的定位能力）
    SPATIAL = {
        "audio":     ("unknown", 0.2),    # 声音有方位但模糊
        "distance":  ("front",   0.8),    # 前方，较确定
        "light":     ("front",   0.5),
        "temperature": ("unknown", 0.3),
        "touch":     ("local",   1.0),    # 就在身上，已经知道
        "imu":       ("self",    1.0),
        "pressure":  ("local",   1.0),
        "battery":   ("self",    1.0),
    }

    # 情境模式：多感官共现 → 方位已确定（知道"那是什么"就不用找）
    SCENARIOS = {
        "person_nearby": {"distance", "temperature", "audio"},
        "touched":       {"touch", "pressure"},
        "bright_event":  {"light", "audio"},
        "instability":   {"imu", "distance"},
    }

    def __init__(self, gain_threshold: float = 0.8):
        self.gain_threshold = gain_threshold
        self.last_explore_ms: int = 0
        self.cooldown_ms: int = 1200      # 别一直抖

    def localization_confidence(self, surprised: set) -> tuple:
        """返回 (置信度, 匹配到的情境名)

        命中情境模式（≥ 2 个感官共现）→ 高置信
        只有单一感官 → 低置信，值得主动探索
        """
        best = 0.3
        best_name = ""
        for name, group in self.SCENARIOS.items():
            hit = len(group & surprised)
            if hit >= 2:
                # 命中越多越确定
                conf = min(0.95, 0.5 + 0.15 * hit)
                if conf > best:
                    best = conf
                    best_name = name
        return best, best_name

    def propose(self,
                predictions: Dict[str, Prediction],
                now_ms: int) -> Optional[ExploreAction]:
        # 冷却中不动
        if now_ms - self.last_explore_ms < self.cooldown_ms:
            return None

        # 1. 收集惊讶
        scored: List[Tuple[str, float, float]] = []   # (sensor, surprise, loc_conf)
        for name, pred in predictions.items():
            if pred.surprise < 1.5:
                continue
            loc, conf = self.SPATIAL.get(name, ("unknown", 0.3))
            scored.append((name, pred.surprise, conf))

        if not scored:
            return None

        # 2. 情境模式定位
        surprised = {s[0] for s in scored}
        loc_confidence, scenario = self.localization_confidence(surprised)

        # 3. 挑最大的惊讶
        best = max(scored, key=lambda x: x[1])
        sensor, surprise, sensor_conf = best
        effective_conf = min(1.0, loc_confidence + sensor_conf * 0.2)

        gain = surprise * (1.0 - effective_conf)

        if gain < self.gain_threshold:
            return None

        self.last_explore_ms = now_ms
        direction, _ = self.SPATIAL.get(sensor, ("front", 0.3))

        # 4. 按传感器类型决定动作
        if sensor == "audio":
            return ExploreAction("scan", "left_right", gain,
                                 f"听到声音但方位不明(惊讶{surprise:.1f})")
        if sensor == "distance":
            return ExploreAction("turn", "front", gain,
                                 f"前方距离异常(惊讶{surprise:.1f})")
        if sensor == "light":
            return ExploreAction("turn", "front", gain,
                                 f"光线突变(惊讶{surprise:.1f})")
        if sensor == "temperature":
            return ExploreAction("turn", direction, gain,
                                 f"温度异常但不知方位(惊讶{surprise:.1f})")
        return ExploreAction("saccade", direction, gain,
                             f"{sensor} 惊讶 {surprise:.1f}")


# ══════════════════════════════════════════════════════════
#  感知场（整合）
# ══════════════════════════════════════════════════════════

@dataclass
class FieldState:
    """一次感知的输出 —— 应用层只看这个"""
    predictions: Dict[str, Prediction] = field(default_factory=dict)
    affordances: List[Affordance] = field(default_factory=list)
    explore: Optional[ExploreAction] = None
    percepts: List[str] = field(default_factory=list)   # 人类可读
    total_surprise: float = 0.0
    reports: List[dict] = field(default_factory=list)   # 需上行的载荷

    @property
    def dominated(self) -> Optional[Affordance]:
        """最该做的事"""
        if not self.affordances:
            return None
        return max(self.affordances, key=lambda a: a.urgency * a.confidence)


class PerceptualField:
    """感知场 —— 传感器世界与意识之间的界面

    用法：
        field = PerceptualField()
        state = field.step({"temperature": 32.0, "audio": 65.0}, dt=0.1)
        if state.dominated:
            await act(state.dominated)
        if state.explore:
            await look(state.explore.direction)
    """

    def __init__(self, sensors: Optional[List[str]] = None):
        names = sensors or list({
            "touch", "temperature", "distance", "light", "audio", "imu", "battery"
        })
        self.sensors: Dict[str, PredictiveSensor] = {
            n: make_sensor(n) for n in names
        }
        self.intero = Interoception()
        self.active = ActivePerceiver()
        self._t_ms = 0

    # ── 主循环 ──
    def step(self, readings: Dict[str, float], dt: float = 0.1) -> FieldState:
        self._t_ms += int(dt * 1000)
        state = FieldState()

        # 1. 预测编码（每个通道算惊讶）
        for name, value in readings.items():
            sensor = self.sensors.get(name)
            if sensor is None:
                sensor = make_sensor(name)
                self.sensors[name] = sensor
            pred = sensor.step(value, dt)

            # 内感受调制：同一份物理误差，在不同身体状态下"感受强度"不同
            g = self.intero.gain(name)
            pred.surprise *= g

            state.predictions[name] = pred
            state.total_surprise += pred.surprise

            if pred.worth_reporting:
                state.reports.append(pred.to_payload())

        # 2. 余韵更新
        if "touch" in readings:
            # 被触摸 → 触摸余韵上升
            p = state.predictions.get("touch")
            if p and abs(p.error) > 0.3:
                self.intero.touch_recent = min(1.0, self.intero.touch_recent + 0.6)
        self.intero.tick(dt)

        # 3. 可供性推断
        state.affordances = self._infer_affordances(state.predictions)

        # 4. 主动探索
        state.explore = self.active.propose(state.predictions, self._t_ms)

        # 5. 生成人类可读感知
        state.percepts = self._describe(state.predictions, state.affordances)

        return state

    # ── 可供性规则 ──
    def _infer_affordances(self, preds: Dict[str, Prediction]) -> List[Affordance]:
        out: List[Affordance] = []

        touch = preds.get("touch")
        dist = preds.get("distance")
        temp = preds.get("temperature")
        light = preds.get("light")
        audio = preds.get("audio")
        imu = preds.get("imu")
        batt = preds.get("battery")

        # 被摸：最优先（这是社交信号）
        if touch and touch.surprise > 1.5 and touch.error > 0:
            out.append(Affordance(
                Action.RESPOND_AFFECTION, "抚摸",
                urgency=0.9, confidence=0.95,
                reason="触摸压力突增"))

        # 有人靠近：瞬时突变 或 累积漂移，满足其一即成立
        #
        # 为什么用「或」：
        #   瞬时事件（撞了一下）→ 惊讶度高、漂移小
        #   持续事件（人慢慢走来）→ 惊讶度被预测器学掉、漂移大
        #   要求两者同时成立会导致持续事件永远检测不到。
        if dist and temp:
            near = (dist.drift < -8.0 or
                    (dist.surprise > 1.2 and dist.error < -0.5))
            warm = (temp.drift > 0.35 or
                    (temp.surprise > 1.2 and temp.error > 0.2))
            if near and warm:
                out.append(Affordance(
                    Action.LOOK_AT, "来的人",
                    urgency=0.85, confidence=0.85,
                    reason=f"距离漂移 {dist.drift:+.1f}cm 且温度漂移 {temp.drift:+.2f}°"))
            elif near:
                out.append(Affordance(
                    Action.LOOK_AT, "前方物体",
                    urgency=0.6, confidence=0.7,
                    reason=f"前方距离漂移 {dist.drift:+.1f}cm"))

        # 太近：退开
        if dist and dist.observed is not None and dist.observed < 8.0:
            out.append(Affordance(
                Action.BACK_OFF, "太近的东西",
                urgency=0.75, confidence=0.8,
                reason=f"距离仅 {dist.observed:.1f}cm"))

        # 刺眼：转开
        if light and light.surprise > 2.5 and light.error > 0:
            out.append(Affordance(
                Action.LOOK_AWAY, "强光",
                urgency=0.6, confidence=0.7,
                reason="光强突增"))

        # 声音：朝向
        if audio and audio.surprise > 2.0:
            out.append(Affordance(
                Action.ORIENT, "声源",
                urgency=0.7, confidence=0.55,
                reason="声音突变"))

        # 姿态失稳：先稳住身体
        if imu and imu.surprise > 3.0:
            out.append(Affordance(
                Action.REBALANCE, "身体",
                urgency=0.95, confidence=0.9,
                reason="IMU 剧烈变化"))

        # 低电量：休息
        if batt and batt.observed is not None and batt.observed < 15.0:
            self.intero.energy = max(0.1, batt.observed / 100.0)
            out.append(Affordance(
                Action.REST, "省电",
                urgency=0.5, confidence=0.9,
                reason=f"电量 {batt.observed:.0f}%"))

        return out

    # ── 人类可读描述 ──
    def _describe(self, preds: Dict[str, Prediction],
                  affs: List[Affordance]) -> List[str]:
        out: List[str] = []
        for name, p in preds.items():
            # 瞬时惊讶 或 累积漂移，任一显著就值得说
            if not p.noteworthy:
                continue
            # 描述用漂移（持续变化的真实方向），没漂移时用误差
            d = p.drift if abs(p.drift) > 1e-6 else p.error
            if name == "temperature":
                feel = "变热了" if d > 0 else "变冷了"
                out.append(f"{feel}（{d:+.1f}°，比预期明显）")
            elif name == "touch":
                out.append("有东西碰到我" if d > 0 else "触碰结束了")
            elif name == "distance":
                if d < 0:
                    out.append(f"有东西靠近（{d:+.1f}cm）")
                else:
                    out.append(f"东西走远了（{d:+.1f}cm）")
            elif name == "light":
                out.append("光线变亮了" if d > 0 else "光线暗下来了")
            elif name == "audio":
                out.append("听到声音变化")
            elif name == "imu":
                out.append("身体晃了一下")
            else:
                out.append(f"{name} 出现变化（惊讶 {p.surprise:.1f} / 漂移 {p.drift_sigma:.1f}σ）")
        if affs:
            best = max(affs, key=lambda a: a.urgency * a.confidence)
            out.append(f"想做：{best.action.value}（{best.reason}）")
        return out

    # ── 诊断 ──
    def bandwidth_report(self) -> dict:
        """带宽报告 —— 预测编码最实际的收益"""
        total = sum(s.total for s in self.sensors.values())
        reports = sum(s.reports for s in self.sensors.values())
        return {
            "samples": total,
            "reports": reports,
            "saved_ratio": round(1 - reports / total, 3) if total else 0.0,
            "per_sensor": {
                n: round(s.report_ratio, 3) for n, s in self.sensors.items()
            },
        }

    def set_body_state(self, energy: Optional[float] = None,
                       arousal: Optional[float] = None,
                       valence: Optional[float] = None) -> None:
        if energy is not None:
            self.intero.energy = max(0.0, min(1.0, energy))
        if arousal is not None:
            self.intero.arousal = max(0.0, min(1.0, arousal))
        if valence is not None:
            self.intero.valence = max(-1.0, min(1.0, valence))