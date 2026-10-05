"""LAAPer 世界模型 (World Model)

物理世界的因果理解：不只记住"发生了什么"，还要理解"为什么会这样"。

核心创新：
1. 因果图（Causal Graph）— 事件之间的因果关系
2. 物理定律（Physics Laws）— 世界的运行规则
3. 预测（Prediction）— 基于因果推断未来
4. 反事实（Counterfactual）— "如果...会怎样"
5. 抽象概念（Abstract Concepts）— 从具体到抽象

这是"理解世界"的基石。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from enum import Enum
from collections import defaultdict


class CausalRelation(str, Enum):
    """因果关系类型"""
    CAUSES = "causes"              # 直接导致
    ENABLES = "enables"            # 使能（必要但不充分）
    PREVENTS = "prevents"          # 阻止
    CORRELATES = "correlates"      # 相关（非因果）
    FEEDBACK = "feedback"          # 反馈循环


class PhysicsLaw(str, Enum):
    """物理定律"""
    GRAVITY = "gravity"            # 重力
    THERMODYNAMICS = "thermodynamics"  # 热力学
    CONSERVATION = "conservation"  # 守恒
    FRICTION = "friction"          # 摩擦
    ELECTROMAGNETISM = "electromagnetism"  # 电磁


@dataclass
class CausalEdge:
    """因果边（事件 A 导致事件 B）"""
    cause_id: str
    effect_id: str
    relation: CausalRelation
    strength: float = 0.5          # 因果强度 0-1
    confidence: float = 0.5        # 置信度
    delay_seconds: float = 0.0     # 因果延迟

    def to_dict(self) -> Dict:
        return {
            "cause": self.cause_id,
            "effect": self.effect_id,
            "relation": self.relation.value,
            "strength": round(self.strength, 3),
            "confidence": round(self.confidence, 3),
            "delay": self.delay_seconds,
        }


@dataclass
class WorldEvent:
    """世界事件"""
    event_id: str
    timestamp: float
    description: str
    location: Optional[Tuple[float, float, float]] = None  # (x, y, z)
    properties: Dict[str, Any] = field(default_factory=dict)

    # 涉及的实体
    entities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.event_id,
            "time": self.timestamp,
            "desc": self.description,
            "loc": self.location,
            "props": self.properties,
            "entities": self.entities,
        }


@dataclass
class Prediction:
    """预测"""
    prediction_id: str
    event_type: str
    confidence: float
    expected_time: float
    expected_properties: Dict[str, Any]

    # 推理路径
    based_on_events: List[str] = field(default_factory=list)
    causal_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.prediction_id,
            "type": self.event_type,
            "confidence": round(self.confidence, 3),
            "expected_time": self.expected_time,
            "properties": self.expected_properties,
            "based_on": self.based_on_events,
        }


class WorldModel:
    """世界模型 — 物理世界的因果理解

    用法：
        world = WorldModel()

        # 记录事件
        world.record_event("evt_1", "温度升高", {"temperature": 35})
        world.record_event("evt_2", "风扇启动", {"fan_speed": 3000})

        # 学习因果
        world.learn_causality("evt_1", "evt_2", CausalRelation.CAUSES, strength=0.8)

        # 预测
        prediction = world.predict_next({"temperature": 40})

        # 反事实
        result = world.counterfactual({"temperature": 20}, "evt_2")
    """

    def __init__(self, model_id: str = "world-model"):
        self.model_id = model_id

        # 事件历史
        self.events: Dict[str, WorldEvent] = {}
        self.event_timeline: List[str] = []  # 按时间排序的事件 ID

        # 因果图
        self.causal_graph: Dict[str, List[CausalEdge]] = defaultdict(list)

        # 物理定律（可学习）
        self.physics_laws: Dict[PhysicsLaw, Dict] = {}

        # 抽象概念
        self.concepts: Dict[str, Dict] = {}

        # 统计
        self.total_events = 0
        self.total_predictions = 0
        self.total_causal_edges = 0

    # ── 事件记录 ──────────────────────────────────────

    def record_event(self, event_id: str, description: str,
                    properties: Optional[Dict] = None,
                    entities: Optional[List[str]] = None,
                    location: Optional[Tuple] = None) -> WorldEvent:
        """记录世界事件"""
        event = WorldEvent(
            event_id=event_id,
            timestamp=time.time(),
            description=description,
            location=location,
            properties=properties or {},
            entities=entities or [],
        )

        self.events[event_id] = event
        self.event_timeline.append(event_id)
        self.total_events += 1

        # 自动学习因果（基于时间邻近性）
        self._auto_learn_causality(event)

        return event

    def _auto_learn_causality(self, new_event: WorldEvent):
        """自动学习因果（基于时间邻近性和属性变化）"""
        # 查找最近的事件
        recent_events = [self.events[eid] for eid in self.event_timeline[-10:]]

        for prev_event in recent_events:
            if prev_event.event_id == new_event.event_id:
                continue

            time_diff = new_event.timestamp - prev_event.timestamp
            if time_diff < 0 or time_diff > 60:  # 60秒窗口
                continue

            # 检查属性关联
            correlation = self._compute_correlation(prev_event, new_event)
            if correlation > 0.3:
                self.learn_causality(
                    prev_event.event_id,
                    new_event.event_id,
                    CausalRelation.CAUSES if time_diff < 5 else CausalRelation.CORRELATES,
                    strength=correlation,
                    confidence=0.5,
                    delay=time_diff,
                )

    def _compute_correlation(self, event1: WorldEvent,
                           event2: WorldEvent) -> float:
        """计算事件相关性"""
        # 检查实体重叠
        entities1 = set(event1.entities)
        entities2 = set(event2.entities)
        entity_overlap = len(entities1 & entities2) / max(1, len(entities1 | entities2))

        # 检查属性变化
        prop_overlap = 0
        for key in event1.properties:
            if key in event2.properties:
                v1 = event1.properties[key]
                v2 = event2.properties[key]
                if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                    if abs(v1 - v2) < max(abs(v1), abs(v2)) * 0.5:
                        prop_overlap += 1

        return (entity_overlap * 0.5 + prop_overlap / 3 * 0.5)

    # ── 因果学习 ──────────────────────────────────────

    def learn_causality(self, cause_id: str, effect_id: str,
                       relation: CausalRelation,
                       strength: float = 0.5,
                       confidence: float = 0.5,
                       delay: float = 0.0):
        """学习因果关系"""
        edge = CausalEdge(
            cause_id=cause_id,
            effect_id=effect_id,
            relation=relation,
            strength=strength,
            confidence=confidence,
            delay_seconds=delay,
        )

        self.causal_graph[cause_id].append(edge)
        self.total_causal_edges += 1

    def get_causal_chain(self, event_id: str,
                        max_depth: int = 5) -> List[CausalEdge]:
        """获取因果链（从事件向前追溯）"""
        chain = []
        visited = set()
        queue = [(event_id, 0)]

        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth >= max_depth:
                continue
            visited.add(current)

            for edge in self.causal_graph.get(current, []):
                chain.append(edge)
                queue.append((edge.effect_id, depth + 1))

        return chain

    def get_root_causes(self, event_id: str) -> List[str]:
        """获取根本原因"""
        # 反向遍历因果图
        causes = []
        visited = set()

        def find_causes(eid: str):
            if eid in visited:
                return
            visited.add(eid)

            # 查找导致 eid 的事件
            for cause_id, edges in self.causal_graph.items():
                for edge in edges:
                    if edge.effect_id == eid:
                        if cause_id not in visited:
                            causes.append(cause_id)
                            find_causes(cause_id)

        find_causes(event_id)
        return causes

    # ── 预测 ──────────────────────────────────────

    def predict_next(self, current_state: Dict,
                    context: Optional[Dict] = None) -> Optional[Prediction]:
        """预测下一个事件"""
        # 查找类似的历史模式
        patterns = self._find_patterns(current_state)

        if not patterns:
            return None

        # 选择最可能的模式
        best_pattern = max(patterns, key=lambda p: p["confidence"])

        prediction = Prediction(
            prediction_id=f"pred_{int(time.time()*1000)}",
            event_type=best_pattern["event_type"],
            confidence=best_pattern["confidence"],
            expected_time=time.time() + best_pattern.get("delay", 0),
            expected_properties=best_pattern.get("properties", {}),
            based_on_events=best_pattern.get("based_on", []),
        )

        self.total_predictions += 1
        return prediction

    def _find_patterns(self, state: Dict) -> List[Dict]:
        """查找历史模式"""
        patterns = []

        # 查找相似状态后的事件
        for event_id in self.event_timeline[-100:]:
            event = self.events.get(event_id)
            if not event:
                continue

            similarity = self._compute_state_similarity(state, event.properties)
            if similarity > 0.5:
                # 查找这个事件之后发生了什么
                idx = self.event_timeline.index(event_id)
                if idx + 1 < len(self.event_timeline):
                    next_id = self.event_timeline[idx + 1]
                    next_event = self.events.get(next_id)
                    if next_event:
                        patterns.append({
                            "event_type": next_event.description,
                            "confidence": similarity,
                            "properties": next_event.properties,
                            "delay": next_event.timestamp - event.timestamp,
                            "based_on": [event_id, next_id],
                        })

        return patterns

    def _compute_state_similarity(self, state1: Dict,
                                 state2: Dict) -> float:
        """计算状态相似度"""
        if not state1 or not state2:
            return 0.0

        common_keys = set(state1.keys()) & set(state2.keys())
        if not common_keys:
            return 0.0

        similarity = 0
        for key in common_keys:
            v1 = state1[key]
            v2 = state2[key]
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                max_val = max(abs(v1), abs(v2), 1)
                if abs(v1 - v2) / max_val < 0.3:
                    similarity += 1

        return similarity / len(common_keys)

    # ── 反事实推理 ──────────────────────────────────────

    def counterfactual(self, alternative_state: Dict,
                      target_event_id: str) -> Dict:
        """反事实推理："如果...会怎样"

        假设世界状态是 alternative_state，target_event 会发生吗？
        """
        target_event = self.events.get(target_event_id)
        if not target_event:
            return {"would_happen": False, "reason": "Event not found"}

        # 检查根本原因
        root_causes = self.get_root_causes(target_event_id)

        # 检查替代状态是否满足因果条件
        would_happen = True
        reasons = []

        for cause_id in root_causes:
            cause_event = self.events.get(cause_id)
            if not cause_event:
                continue

            # 检查原因是否会在替代状态下发生
            if not self._check_cause_satisfied(cause_event, alternative_state):
                would_happen = False
                reasons.append(f"Cause '{cause_event.description}' not satisfied")

        return {
            "would_happen": would_happen,
            "event": target_event.description,
            "reasons": reasons,
            "confidence": 0.7 if would_happen else 0.3,
        }

    def _check_cause_satisfied(self, cause_event: WorldEvent,
                             state: Dict) -> bool:
        """检查原因是否在给定状态下满足"""
        # 简化：检查关键属性是否匹配
        for key, value in cause_event.properties.items():
            if key in state:
                state_value = state[key]
                if isinstance(value, (int, float)) and isinstance(state_value, (int, float)):
                    if abs(value - state_value) > abs(value) * 0.5:
                        return False
        return True

    # ── 抽象概念 ──────────────────────────────────────

    def abstract_concept(self, concept_name: str,
                        event_ids: List[str]) -> Dict:
        """从具体事件中抽象概念"""
        events = [self.events[eid] for eid in event_ids if eid in self.events]

        # 提取共同特征
        common_entities = set(events[0].entities) if events else set()
        for e in events[1:]:
            common_entities &= set(e.entities)

        common_props = {}
        for key in events[0].properties if events else {}:
            values = [e.properties.get(key) for e in events]
            if all(v is not None for v in values):
                common_props[key] = sum(values) / len(values) if isinstance(values[0], (int, float)) else values[0]

        concept = {
            "name": concept_name,
            "description": f"抽象概念: {concept_name}",
            "common_entities": list(common_entities),
            "common_properties": common_props,
            "example_events": event_ids,
            "created_at": time.time(),
        }

        self.concepts[concept_name] = concept
        return concept

    def match_concept(self, event: WorldEvent) -> Optional[str]:
        """匹配事件到已知概念"""
        best_match = None
        best_score = 0

        for name, concept in self.concepts.items():
            score = 0

            # 检查实体匹配
            common = set(event.entities) & set(concept["common_entities"])
            score += len(common) / max(1, len(concept["common_entities"]))

            if score > best_score and score > 0.3:
                best_score = score
                best_match = name

        return best_match

    # ── 物理定律 ──────────────────────────────────────

    def learn_physics_law(self, law: PhysicsLaw,
                         params: Dict[str, float]):
        """学习物理定律参数"""
        self.physics_laws[law] = {
            "params": params,
            "learned_at": time.time(),
            "observations": 0,
        }

    def apply_physics(self, law: PhysicsLaw,
                     state: Dict) -> Dict:
        """应用物理定律预测状态变化"""
        if law not in self.physics_laws:
            return state

        params = self.physics_laws[law]["params"]
        new_state = dict(state)

        if law == PhysicsLaw.GRAVITY:
            # 重力: h = h0 + v0*t - 0.5*g*t^2
            if "height" in state and "velocity" in state:
                g = params.get("g", 9.8)
                t = params.get("t", 1.0)
                h = state["height"] + state["velocity"] * t - 0.5 * g * t * t
                new_state["height"] = h

        elif law == PhysicsLaw.THERMODYNAMICS:
            # 热传导: dT/dt = k*(T_env - T)
            if "temperature" in state:
                k = params.get("k", 0.1)
                T_env = params.get("T_env", 22.0)
                dT = k * (T_env - state["temperature"])
                new_state["temperature"] = state["temperature"] + dT

        return new_state

    # ── 查询 ──────────────────────────────────────

    def get_world_state(self) -> Dict:
        """获取世界模型状态"""
        return {
            "model_id": self.model_id,
            "total_events": self.total_events,
            "total_predictions": self.total_predictions,
            "total_causal_edges": self.total_causal_edges,
            "concepts": list(self.concepts.keys()),
            "physics_laws": list(self.physics_laws.keys()),
            "recent_events": [
                self.events[eid].to_dict()
                for eid in self.event_timeline[-5:]
            ],
        }