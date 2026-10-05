"""LAAPer 统一感官编码器 (Unified Sensory Encoder)

人类的感知本质：所有感官编码成同一种"神经冲动"，然后跨模态融合成体验。

这就是"真正的感知"的核心：
- 22.5°C 不是感知，"凉爽"才是感知
- 3.2N 不是感知，"被按压"才是感知
- 65dB 不是感知，"嘈杂"才是感知

感官编码器把物理量映射成**体验质（Qualia）**。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum


class SensoryModality(str, Enum):
    """感官模态（对应人类五感+扩展）"""
    VISION = "vision"          # 视觉
    AUDITION = "audition"      # 听觉
    TACTILE = "tactile"        # 触觉
    GUSTATION = "gustation"    # 味觉
    OLFCTION = "olfaction"    # 嗅觉
    THERMO = "thermo"          # 温度觉
    NOCICEPTION = "nociception"  # 痛觉
    PROPRIOCEPTION = "proprioception"  # 本体觉
    VESTIBULAR = "vestibular"  # 前庭觉
    INTEROCEPTION = "interoception"  # 内感受


class QualiaType(str, Enum):
    """体验质类型（感知的"质感"）"""
    # 温度
    FRIGID = "frigid"          # 酷寒
    COLD = "cold"              # 冷
    COOL = "cool"              # 凉爽
    NEUTRAL_TEMP = "neutral_temp"  # 舒适
    WARM = "warm"              # 温暖
    HOT = "hot"                # 热
    SCALDING = "scalding"      # 滚烫

    # 压力/触觉
    NEGLIGIBLE = "negligible"  # 几乎无感
    LIGHT_TOUCH = "light_touch"  # 轻触
    FIRM_TOUCH = "firm_touch"  # 实按
    PRESSURE = "pressure"      # 压迫
    CRUSHING = "crushing"      # 挤压

    # 疼痛（痛觉）
    NONE = "none"              # 无痛
    MILD_PAIN = "mild_pain"    # 微痛
    MODERATE_PAIN = "moderate_pain"  # 中痛
    SEVERE_PAIN = "severe_pain"  # 剧痛

    # 亮度
    DARK = "dark"              # 黑暗
    DIM = "dim"                # 昏暗
    MODERATE_LIGHT = "moderate_light"  # 适中
    BRIGHT = "bright"          # 明亮
    DAZZLING = "dazzling"      # 刺眼

    # 声音
    SILENT = "silent"          # 寂静
    QUIET = "quiet"            # 安静
    MODERATE_SOUND = "moderate_sound"  # 适中
    LOUD = "loud"              # 嘈杂
    DEAFENING = "deafening"    # 震耳

    # 嗅觉
    ODORLESS = "odorless"      # 无味
    FAINT_SCENT = "faint_scent"  # 淡香
    NOTICEABLE = "noticeable"  # 明显
    STRONG = "strong"          # 浓烈
    PUNGENT = "pungent"        # 刺鼻

    # 运动/平衡
    STILL = "still"            # 静止
    SLOW_MOTION = "slow_motion"  # 缓慢
    MODERATE_MOTION = "moderate_motion"  # 适中
    FAST_MOTION = "fast_motion"  # 快速
    VIOLENT = "violent"        # 剧烈


@dataclass
class Qualia:
    """体验质 — 感知的"质感"

    这就是"真正的感知"的载体：不是数据，是体验。
    """
    qualia_type: QualiaType
    modality: SensoryModality
    intensity: float = 0.5          # 强度 0-1
    valence: float = 0.0            # 愉悦度 -1~1
    arousal: float = 0.5            # 唤醒度 0-1
    confidence: float = 1.0         # 置信度

    # 语义描述
    description: str = ""
    metaphor: str = ""              # 隐喻描述（如"像被火烤"）

    def to_dict(self) -> Dict:
        return {
            "type": self.qualia_type.value,
            "modality": self.modality.value,
            "intensity": round(self.intensity, 3),
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "metaphor": self.metaphor,
        }


@dataclass
class NeuralCode:
    """神经编码 — 统一的感觉编码

    所有感官编码成同一种格式，模拟人类神经冲动的时序模式。
    """
    sensory_id: str
    modality: SensoryModality
    timestamp: float
    spike_rate: float           # 脉冲频率 (Hz)
    spike_pattern: List[float]  # 时序模式
    amplitude: float            # 幅度
    frequency: float            # 频率特征

    def to_dict(self) -> Dict:
        return {
            "sensory_id": self.sensory_id,
            "modality": self.modality.value,
            "spike_rate": round(self.spike_rate, 2),
            "amplitude": round(self.amplitude, 3),
            "frequency": round(self.frequency, 2),
            "pattern_length": len(self.spike_pattern),
        }


class SensoryEncoder:
    """感官编码器 — 把物理量映射成体验质

    这是"真正的感知"的核心：把传感器数据变成体验。

    用法：
        encoder = SensoryEncoder()

        # 温度 22.5°C → "凉爽"
        qualia = encoder.encode_temperature(22.5)
        print(qualia.description)  # "凉爽"
        print(qualia.qualia_type)  # QualiaType.COOL

        # 压力 3.2N → "被按压"
        qualia = encoder.encode_pressure(3.2)
    """

    # ── 温度编码（冷热感知） ──────────────────────────────────────

    def encode_temperature(self, temp_celsius: float,
                           body_part: str = "skin") -> Qualia:
        """温度 → 体验质

        人类皮肤温度感受器的响应曲线：
        - 冷感受器: 15-35°C，峰值 ~25°C
        - 温感受器: 30-45°C，峰值 ~40°C
        - 痛感受器: >45°C 或 <10°C
        """
        # 计算强度（基于偏离舒适区的程度）
        comfort_zone = 22.0  # 舒适温度
        deviation = abs(temp_celsius - comfort_zone)
        intensity = min(1.0, deviation / 20.0)

        # 映射到体验质
        if temp_celsius < 10:
            return Qualia(
                qualia_type=QualiaType.FRIGID,
                modality=SensoryModality.THERMO,
                intensity=min(1.0, (10 - temp_celsius) / 20),
                valence=-0.9,
                arousal=0.8,
                description="酷寒",
                metaphor="像被冰水浇透",
            )
        elif temp_celsius < 16:
            return Qualia(
                qualia_type=QualiaType.COLD,
                modality=SensoryModality.THERMO,
                intensity=(16 - temp_celsius) / 10,
                valence=-0.5,
                arousal=0.6,
                description="冷",
                metaphor="像冬天的风",
            )
        elif temp_celsius < 21:
            return Qualia(
                qualia_type=QualiaType.COOL,
                modality=SensoryModality.THERMO,
                intensity=(21 - temp_celsius) / 8,
                valence=0.3,
                arousal=0.3,
                description="凉爽",
                metaphor="像秋天的清晨",
            )
        elif temp_celsius <= 26:
            return Qualia(
                qualia_type=QualiaType.NEUTRAL_TEMP,
                modality=SensoryModality.THERMO,
                intensity=0.1,
                valence=0.5,
                arousal=0.2,
                description="舒适",
                metaphor="像被温暖的阳光轻抚",
            )
        elif temp_celsius <= 32:
            return Qualia(
                qualia_type=QualiaType.WARM,
                modality=SensoryModality.THERMO,
                intensity=(temp_celsius - 26) / 10,
                valence=0.3,
                arousal=0.4,
                description="温暖",
                metaphor="像泡在温水里",
            )
        elif temp_celsius <= 42:
            return Qualia(
                qualia_type=QualiaType.HOT,
                modality=SensoryModality.THERMO,
                intensity=(temp_celsius - 32) / 12,
                valence=-0.6,
                arousal=0.7,
                description="热",
                metaphor="像被太阳直晒",
            )
        else:
            return Qualia(
                qualia_type=QualiaType.SCALDING,
                modality=SensoryModality.THERMO,
                intensity=1.0,
                valence=-1.0,
                arousal=1.0,
                description="滚烫",
                metaphor="像被火烤",
            )

    # ── 压力编码（触觉感知） ──────────────────────────────────────

    def encode_pressure(self, force_newton: float) -> Qualia:
        """压力 → 体验质

        人类触觉感受器：
        - Meissner 小体: 轻触 (0.01-1N)
        - Merkel 盘: 持续压力 (0.1-10N)
        - Ruffini 末梢: 深层压力 (>10N)
        - Pacinian 小体: 振动
        """
        if force_newton < 0.1:
            return Qualia(
                qualia_type=QualiaType.NEGLIGIBLE,
                modality=SensoryModality.TACTILE,
                intensity=force_newton / 0.1,
                valence=0.0,
                arousal=0.1,
                description="几乎无感",
                metaphor="像微风拂过",
            )
        elif force_newton < 1.0:
            return Qualia(
                qualia_type=QualiaType.LIGHT_TOUCH,
                modality=SensoryModality.TACTILE,
                intensity=force_newton / 1.0,
                valence=0.5,
                arousal=0.3,
                description="轻触",
                metaphor="像被羽毛扫过",
            )
        elif force_newton < 5.0:
            return Qualia(
                qualia_type=QualiaType.FIRM_TOUCH,
                modality=SensoryModality.TACTILE,
                intensity=force_newton / 5.0,
                valence=0.3,
                arousal=0.5,
                description="实按",
                metaphor="像被手掌按住",
            )
        elif force_newton < 20.0:
            return Qualia(
                qualia_type=QualiaType.PRESSURE,
                modality=SensoryModality.TACTILE,
                intensity=min(1.0, force_newton / 20.0),
                valence=-0.3,
                arousal=0.7,
                description="压迫",
                metaphor="像被石头压住",
            )
        else:
            return Qualia(
                qualia_type=QualiaType.CRUSHING,
                modality=SensoryModality.TACTILE,
                intensity=1.0,
                valence=-0.8,
                arousal=0.9,
                description="挤压",
                metaphor="像被重物碾压",
            )

    # ── 疼痛编码（痛觉感知） ──────────────────────────────────────

    def encode_pain(self, pain_level: float) -> Qualia:
        """疼痛 → 体验质（痛觉是保护性感知）"""
        if pain_level < 0.1:
            return Qualia(
                qualia_type=QualiaType.NONE,
                modality=SensoryModality.NOCICEPTION,
                intensity=0.0,
                valence=0.5,
                arousal=0.1,
                description="无痛",
                metaphor="",
            )
        elif pain_level < 0.3:
            return Qualia(
                qualia_type=QualiaType.MILD_PAIN,
                modality=SensoryModality.NOCICEPTION,
                intensity=pain_level / 0.3,
                valence=-0.3,
                arousal=0.4,
                description="微痛",
                metaphor="像被针轻轻刺了一下",
            )
        elif pain_level < 0.7:
            return Qualia(
                qualia_type=QualiaType.MODERATE_PAIN,
                modality=SensoryModality.NOCICEPTION,
                intensity=pain_level / 0.7,
                valence=-0.7,
                arousal=0.7,
                description="中痛",
                metaphor="像被火烧了一下",
            )
        else:
            return Qualia(
                qualia_type=QualiaType.SEVERE_PAIN,
                modality=SensoryModality.NOCICEPTION,
                intensity=1.0,
                valence=-1.0,
                arousal=1.0,
                description="剧痛",
                metaphor="像被刀割",
            )

    # ── 亮度编码（视觉感知） ──────────────────────────────────────

    def encode_brightness(self, lux: float) -> Qualia:
        """亮度 → 体验质"""
        if lux < 10:
            return Qualia(qualia_type=QualiaType.DARK, modality=SensoryModality.VISION,
                         intensity=1 - lux / 10, valence=-0.3, arousal=0.2,
                         description="黑暗", metaphor="像被蒙上眼睛")
        elif lux < 100:
            return Qualia(qualia_type=QualiaType.DIM, modality=SensoryModality.VISION,
                         intensity=lux / 100, valence=-0.1, arousal=0.3,
                         description="昏暗", metaphor="像黄昏")
        elif lux < 1000:
            return Qualia(qualia_type=QualiaType.MODERATE_LIGHT, modality=SensoryModality.VISION,
                         intensity=lux / 1000, valence=0.3, arousal=0.4,
                         description="适中", metaphor="像白天的室内")
        elif lux < 10000:
            return Qualia(qualia_type=QualiaType.BRIGHT, modality=SensoryModality.VISION,
                         intensity=min(1.0, lux / 10000), valence=0.5, arousal=0.6,
                         description="明亮", metaphor="像晴天")
        else:
            return Qualia(qualia_type=QualiaType.DAZZLING, modality=SensoryModality.VISION,
                         intensity=1.0, valence=-0.5, arousal=0.8,
                         description="刺眼", metaphor="像直视太阳")

    # ── 声音编码（听觉感知） ──────────────────────────────────────

    def encode_sound(self, decibels: float) -> Qualia:
        """声音 → 体验质"""
        if decibels < 30:
            return Qualia(qualia_type=QualiaType.SILENT, modality=SensoryModality.AUDITION,
                         intensity=1 - decibels / 30, valence=0.3, arousal=0.1,
                         description="寂静", metaphor="像深夜的房间")
        elif decibels < 50:
            return Qualia(qualia_type=QualiaType.QUIET, modality=SensoryModality.AUDITION,
                         intensity=decibels / 50, valence=0.5, arousal=0.2,
                         description="安静", metaphor="像图书馆")
        elif decibels < 70:
            return Qualia(qualia_type=QualiaType.MODERATE_SOUND, modality=SensoryModality.AUDITION,
                         intensity=decibels / 70, valence=0.3, arousal=0.4,
                         description="适中", metaphor="像正常谈话")
        elif decibels < 90:
            return Qualia(qualia_type=QualiaType.LOUD, modality=SensoryModality.AUDITION,
                         intensity=decibels / 90, valence=-0.3, arousal=0.7,
                         description="嘈杂", metaphor="像繁忙的街道")
        else:
            return Qualia(qualia_type=QualiaType.DEAFENING, modality=SensoryModality.AUDITION,
                         intensity=1.0, valence=-0.8, arousal=0.9,
                         description="震耳", metaphor="像在工厂里")

    # ── 气味编码（嗅觉感知） ──────────────────────────────────────

    def encode_smell(self, concentration_ppm: float,
                     pleasantness: float = 0.5) -> Qualia:
        """气味 → 体验质"""
        if concentration_ppm < 10:
            return Qualia(qualia_type=QualiaType.ODORLESS, modality=SensoryModality.OLFCTION,
                         intensity=concentration_ppm / 10, valence=0.5, arousal=0.1,
                         description="无味", metaphor="")
        elif concentration_ppm < 50:
            return Qualia(qualia_type=QualiaType.FAINT_SCENT, modality=SensoryModality.OLFCTION,
                         intensity=concentration_ppm / 50,
                         valence=pleasantness * 2 - 1,
                         arousal=0.3, description="淡香", metaphor="像远处飘来的花香")
        elif concentration_ppm < 200:
            return Qualia(qualia_type=QualiaType.NOTICEABLE, modality=SensoryModality.OLFCTION,
                         intensity=concentration_ppm / 200,
                         valence=pleasantness * 2 - 1,
                         arousal=0.5, description="明显", metaphor="像走进厨房")
        elif concentration_ppm < 1000:
            return Qualia(qualia_type=QualiaType.STRONG, modality=SensoryModality.OLFCTION,
                         intensity=min(1.0, concentration_ppm / 1000),
                         valence=pleasantness * 2 - 1,
                         arousal=0.7, description="浓烈", metaphor="像香水瓶打翻")
        else:
            return Qualia(qualia_type=QualiaType.PUNGENT, modality=SensoryModality.OLFCTION,
                         intensity=1.0, valence=-0.8, arousal=0.9,
                         description="刺鼻", metaphor="像氨水")

    # ── 运动编码（前庭觉感知） ──────────────────────────────────────

    def encode_motion(self, acceleration: float) -> Qualia:
        """运动 → 体验质"""
        if acceleration < 0.5:
            return Qualia(qualia_type=QualiaType.STILL, modality=SensoryModality.VESTIBULAR,
                         intensity=acceleration / 0.5, valence=0.5, arousal=0.1,
                         description="静止", metaphor="像坐着不动")
        elif acceleration < 2.0:
            return Qualia(qualia_type=QualiaType.SLOW_MOTION, modality=SensoryModality.VESTIBULAR,
                         intensity=acceleration / 2.0, valence=0.3, arousal=0.3,
                         description="缓慢", metaphor="像散步")
        elif acceleration < 5.0:
            return Qualia(qualia_type=QualiaType.MODERATE_MOTION, modality=SensoryModality.VESTIBULAR,
                         intensity=acceleration / 5.0, valence=0.1, arousal=0.5,
                         description="适中", metaphor="像骑自行车")
        elif acceleration < 10.0:
            return Qualia(qualia_type=QualiaType.FAST_MOTION, modality=SensoryModality.VESTIBULAR,
                         intensity=acceleration / 10.0, valence=-0.2, arousal=0.7,
                         description="快速", metaphor="像坐过山车")
        else:
            return Qualia(qualia_type=QualiaType.VIOLENT, modality=SensoryModality.VESTIBULAR,
                         intensity=1.0, valence=-0.8, arousal=0.9,
                         description="剧烈", metaphor="像被甩出去")

    # ── 神经编码（统一格式） ──────────────────────────────────────

    def encode_to_neural(self, qualia: Qualia,
                        sensory_id: str,
                        timestamp: float) -> NeuralCode:
        """把体验质编码成神经编码（模拟人类神经冲动）"""
        # 脉冲频率映射（强度 → 频率）
        spike_rate = qualia.intensity * 100  # 0-100 Hz

        # 时序模式（模拟神经元的时序编码）
        pattern_length = max(1, int(qualia.intensity * 10))
        spike_pattern = [qualia.intensity * math.sin(i * 0.5) for i in range(pattern_length)]

        return NeuralCode(
            sensory_id=sensory_id,
            modality=qualia.modality,
            timestamp=timestamp,
            spike_rate=spike_rate,
            spike_pattern=spike_pattern,
            amplitude=qualia.intensity,
            frequency=spike_rate / 10,  # 归一化频率
        )
