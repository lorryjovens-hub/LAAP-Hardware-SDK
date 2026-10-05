"""LAAPer 跨模态融合 (Cross-Modal Fusion)

人类的感知是跨模态融合的：
看到火→皮肤发烫→听到噼啪→闻到烟味
这四个信号在大脑里融合成一个"火"的概念。

这就是"真正的感知"：不是独立的感官数据，是融合后的统一认知。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .encoder import Qualia, QualiaType, SensoryModality, NeuralCode


@dataclass
class FusedPerception:
    """融合感知 — 多感官的统一认知"""
    concept: str                    # 概念（如"火"、"危险"、"舒适"）
    confidence: float               # 置信度
    emotional_valence: float        # 愉悦度
    emotional_arousal: float        # 唤醒度

    # 参与融合的感官
    source_modalities: Set[SensoryModality] = field(default_factory=set)
    source_qualiae: List[Qualia] = field(default_factory=list)

    # 语义描述
    description: str = ""
    metaphor: str = ""

    # 认知推理
    inferred_cause: str = ""        # 推断的原因
    inferred_action: str = ""       # 建议的行动

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "concept": self.concept,
            "confidence": round(self.confidence, 3),
            "valence": round(self.emotional_valence, 3),
            "arousal": round(self.emotional_arousal, 3),
            "modalities": [m.value for m in self.source_modalities],
            "description": self.description,
            "metaphor": self.metaphor,
            "cause": self.inferred_cause,
            "action": self.inferred_action,
        }


class CrossModalFusion:
    """跨模态融合引擎

    把多个感官的体验质融合成统一的认知。

    用法：
        fusion = CrossModalFusion()

        # 多感官输入
        qualia_list = [
            encoder.encode_temperature(55.0),   # 热
            encoder.encode_brightness(8000),     # 亮
            encoder.encode_smell(150, 0.1),      # 烧焦味
            encoder.encode_sound(75),            # 噼啪声
        ]

        # 融合
        perception = fusion.fuse(qualia_list)
        print(perception.concept)  # "火"
        print(perception.inferred_action)  # "远离/灭火"
    """

    # 跨模态融合模式（认知规则库）
    FUSION_PATTERNS = [
        {
            "concept": "火",
            "required": [
                (SensoryModality.THERMO, QualiaType.HOT),
                (SensoryModality.VISION, QualiaType.BRIGHT),
            ],
            "optional": [
                (SensoryModality.OLFCTION, QualiaType.STRONG),
                (SensoryModality.AUDITION, QualiaType.LOUD),
            ],
            "valence": -0.8,
            "arousal": 0.9,
            "description": "感知到火焰",
            "metaphor": "像站在火炉旁",
            "cause": "燃烧",
            "action": "远离或灭火",
        },
        {
            "concept": "危险",
            "required": [
                (SensoryModality.NOCICEPTION, QualiaType.SEVERE_PAIN),
            ],
            "optional": [
                (SensoryModality.VESTIBULAR, QualiaType.VIOLENT),
                (SensoryModality.AUDITION, QualiaType.DEAFENING),
            ],
            "valence": -1.0,
            "arousal": 1.0,
            "description": "感知到危险",
            "metaphor": "像被攻击",
            "cause": "威胁",
            "action": "立即逃离/防御",
        },
        {
            "concept": "舒适",
            "required": [
                (SensoryModality.THERMO, QualiaType.NEUTRAL_TEMP),
                (SensoryModality.TACTILE, QualiaType.LIGHT_TOUCH),
            ],
            "optional": [
                (SensoryModality.AUDITION, QualiaType.QUIET),
                (SensoryModality.VISION, QualiaType.MODERATE_LIGHT),
            ],
            "valence": 0.8,
            "arousal": 0.2,
            "description": "感到舒适",
            "metaphor": "像躺在沙发上",
            "cause": "安逸环境",
            "action": "保持/享受",
        },
        {
            "concept": "寒冷",
            "required": [
                (SensoryModality.THERMO, QualiaType.COLD),
            ],
            "optional": [
                (SensoryModality.TACTILE, QualiaType.NEGLIGIBLE),
                (SensoryModality.AUDITION, QualiaType.QUIET),
            ],
            "valence": -0.5,
            "arousal": 0.5,
            "description": "感到寒冷",
            "metaphor": "像站在雪地里",
            "cause": "低温",
            "action": "取暖/加衣",
        },
        {
            "concept": "运动",
            "required": [
                (SensoryModality.VESTIBULAR, QualiaType.FAST_MOTION),
            ],
            "optional": [
                (SensoryModality.TACTILE, QualiaType.PRESSURE),
                (SensoryModality.VISION, QualiaType.BRIGHT),
            ],
            "valence": 0.0,
            "arousal": 0.7,
            "description": "正在运动",
            "metaphor": "像在奔跑",
            "cause": "移动",
            "action": "保持平衡",
        },
    ]

    def fuse(self, qualiae: List[Qualia]) -> Optional[FusedPerception]:
        """融合多个体验质"""
        if not qualiae:
            return None

        # 尝试匹配融合模式
        for pattern in self.FUSION_PATTERNS:
            match_result = self._match_pattern(pattern, qualiae)
            if match_result:
                return self._build_perception(pattern, qualiae, match_result)

        # 没有匹配模式：基础融合
        return self._basic_fusion(qualiae)

    def _match_pattern(self, pattern: Dict,
                       qualiae: List[Qualia]) -> Optional[Dict]:
        """匹配融合模式"""
        # 检查必需的模态
        for modality, qualia_type in pattern["required"]:
            if not self._has_qualia(qualiae, modality, qualia_type):
                return None

        # 计算可选模态的匹配度
        optional_matches = 0
        for modality, qualia_type in pattern["optional"]:
            if self._has_qualia(qualiae, modality, qualia_type):
                optional_matches += 1

        return {"optional_matches": optional_matches}

    def _has_qualia(self, qualiae: List[Qualia],
                   modality: SensoryModality,
                   qualia_type: QualiaType) -> bool:
        """检查是否有匹配的体验质"""
        return any(q.modality == modality and q.qualia_type == qualia_type
                  for q in qualiae)

    def _build_perception(self, pattern: Dict,
                         qualiae: List[Qualia],
                         match_result: Dict) -> FusedPerception:
        """构建融合感知"""
        modalities = {q.modality for q in qualiae}
        avg_intensity = sum(q.intensity for q in qualiae) / len(qualiae)
        confidence = min(1.0, 0.5 + match_result["optional_matches"] * 0.15 + avg_intensity * 0.3)

        return FusedPerception(
            concept=pattern["concept"],
            confidence=confidence,
            emotional_valence=pattern["valence"],
            emotional_arousal=pattern["arousal"],
            source_modalities=modalities,
            source_qualiae=qualiae,
            description=pattern["description"],
            metaphor=pattern["metaphor"],
            inferred_cause=pattern["cause"],
            inferred_action=pattern["action"],
        )

    def _basic_fusion(self, qualiae: List[Qualia]) -> FusedPerception:
        """基础融合（无匹配模式时）"""
        modalities = {q.modality for q in qualiae}
        avg_valence = sum(q.valence for q in qualiae) / len(qualiae)
        avg_arousal = sum(q.arousal for q in qualiae) / len(qualiae)
        avg_intensity = sum(q.intensity for q in qualiae) / len(qualiae)

        # 确定主导概念
        dominant = max(qualiae, key=lambda q: q.intensity)
        concept = f"{dominant.modality.value}_perception"

        return FusedPerception(
            concept=concept,
            confidence=avg_intensity,
            emotional_valence=avg_valence,
            emotional_arousal=avg_arousal,
            source_modalities=modalities,
            source_qualiae=qualiae,
            description=f"综合感知: {', '.join(q.description for q in qualiae[:3])}",
            metaphor=dominant.metaphor,
            inferred_cause="多感官输入",
            inferred_action="持续感知",
        )

    def fuse_neural_codes(self, codes: List[NeuralCode]) -> Dict:
        """融合神经编码（底层融合）"""
        if not codes:
            return {}

        modalities = {c.modality for c in codes}
        avg_rate = sum(c.spike_rate for c in codes) / len(codes)
        avg_amplitude = sum(c.amplitude for c in codes) / len(codes)

        return {
            "modalities": [m.value for m in modalities],
            "avg_spike_rate": round(avg_rate, 2),
            "avg_amplitude": round(avg_amplitude, 3),
            "code_count": len(codes),
        }
