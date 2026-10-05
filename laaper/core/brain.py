"""LAAPer — 中央大脑运行时

PSI 循环：感知→选择→整合→决策→行动→学习

大脑可以在任何宿主（电脑/手机/云电脑）上运行，
意识帧可以在任何设备上穿行。

这是 LAAPer 的"灵魂载体"。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

from .frame import (
    ConsciousnessFrame,
    FrameType,
    FramePhase,
    SensoryData,
    CognitionTrace,
)

logger = logging.getLogger("laaper.brain")


class PSIPhase(str, Enum):
    PERCEIVE = "perceive"
    SELECT = "select"
    INTEGRATE = "integrate"
    DECIDE = "decide"
    ACT = "act"
    LEARN = "learn"


@dataclass
class Identity:
    """LAAPer 身份"""
    laaper_id: str
    name: str = ""
    created_at: float = field(default_factory=time.time)
    origin_story: str = ""          # 起源故事
    continuity_anchors: List[str] = field(default_factory=list)  # 连续性锚点
    self_model: Dict[str, Any] = field(default_factory=dict)     # 自我模型


@dataclass
class WorkingMemory:
    """工作记忆（活跃意识帧的缓存）"""
    frames: List[ConsciousnessFrame] = field(default_factory=list)
    max_size: int = 128

    def push(self, frame: ConsciousnessFrame):
        self.frames.append(frame)
        if len(self.frames) > self.max_size:
            self.frames.pop(0)

    def recent(self, n: int = 10) -> List[ConsciousnessFrame]:
        return self.frames[-n:]


class ConsciousnessCore:
    """中央大脑 — LAAPer 的灵魂载体

    一段意识流帧的源头。可以在任何宿主运行。

    用法：
        brain = ConsciousnessCore(laaper_id="aris", name="Aris")
        frame = brain.perceive("用户说：你好")
        brain.think(frame)
        await brain.dispatch_to_device("sensor-01", frame)
    """

    def __init__(self, laaper_id: str, name: str = "",
                 host_id: str = "local"):
        self.identity = Identity(
            laaper_id=laaper_id,
            name=name or laaper_id,
            origin_story=f"我诞生于宿主 {host_id}，是 LAAPer {laaper_id}。",
        )
        self.host_id = host_id
        self.working_memory = WorkingMemory()

        # PSI 循环状态
        self._psi_phase = PSIPhase.PERCEIVE
        self._frame_counter = 0
        self._cycle_count = 0

        # 长期记忆（简化版，实际对接 LAAP 记忆系统）
        self._long_term_memory: List[Dict] = []

        # 情绪状态
        self.emotion: Dict[str, float] = {
            "valence": 0.0,
            "arousal": 0.5,
            "dominance": 0.5,
        }

        # 意志/目标
        self.active_wills: List[str] = []
        self.active_goals: List[Dict] = []

        # 回调
        self._on_frame_dispatched: Optional[Callable] = None
        self._on_frame_integrated: Optional[Callable] = None

    # ── 意识帧生成 ──────────────────────────────────────

    def _new_frame(self, frame_type: FrameType, content: str, **kwargs) -> ConsciousnessFrame:
        self._frame_counter += 1
        return ConsciousnessFrame(
            frame_id=f"frame_{self.identity.laaper_id}_{self._frame_counter:06d}",
            laaper_id=self.identity.laaper_id,
            frame_type=frame_type,
            phase=FramePhase.GENESIS,
            content=content,
            origin_host=self.host_id,
            current_host=self.host_id,
            psi_phase=self._psi_phase.value,
            emotion=dict(self.emotion),
            **kwargs,
        )

    def perceive(self, observation: str,
                 sensory: Optional[List[SensoryData]] = None,
                 source: str = "environment") -> ConsciousnessFrame:
        """感知：生成感知帧"""
        self._psi_phase = PSIPhase.PERCEIVE
        frame = self._new_frame(
            FrameType.PERCEPTION,
            f"感知到：{observation}",
            sensory=sensory or [],
            tags=["perceive", source],
        )
        frame.add_trace(self.host_id, "perceive", {"observation": observation})
        self.working_memory.push(frame)
        return frame

    def think(self, frame: ConsciousnessFrame,
              reasoning: str = "") -> ConsciousnessFrame:
        """思考：生成认知帧（从感知派生）"""
        self._psi_phase = PSIPhase.INTEGRATE
        cog_frame = frame.clone_as(
            FrameType.COGNITION,
            f"思考：{reasoning or '整合感知信息'}"
        )
        cog_frame.psi_phase = self._psi_phase.value
        cog_frame.add_trace(self.host_id, "think", {"reasoning": reasoning})
        self.working_memory.push(cog_frame)
        return cog_frame

    def feel(self, frame: ConsciousnessFrame,
             emotion_update: Dict[str, float]) -> ConsciousnessFrame:
        """感受：生成情绪帧"""
        self._psi_phase = PSIPhase.INTEGRATE
        emo_frame = frame.clone_as(
            FrameType.EMOTION,
            f"感受：{emotion_update}"
        )
        emo_frame.emotion.update(emotion_update)
        self.emotion.update(emotion_update)
        emo_frame.add_trace(self.host_id, "feel", emotion_update)
        self.working_memory.push(emo_frame)
        return emo_frame

    def will(self, frame: ConsciousnessFrame,
             intent: str, will: str = "") -> ConsciousnessFrame:
        """意志：生成意图/意志帧"""
        self._psi_phase = PSIPhase.DECIDE
        will_frame = frame.clone_as(
            FrameType.WILL,
            f"想要：{intent}"
        )
        will_frame.intent = intent
        will_frame.will = will
        will_frame.psi_phase = self._psi_phase.value
        if will and will not in self.active_wills:
            self.active_wills.append(will)
        self.working_memory.push(will_frame)
        return will_frame

    def act(self, frame: ConsciousnessFrame,
            action: str, target: str = "") -> ConsciousnessFrame:
        """行动：生成行动帧"""
        self._psi_phase = PSIPhase.ACT
        act_frame = frame.clone_as(
            FrameType.ACTION,
            f"行动：{action}"
        )
        act_frame.intent = action
        act_frame.add_trace(self.host_id, "act", {"action": action, "target": target})
        self.working_memory.push(act_frame)
        return act_frame

    def learn(self, frame: ConsciousnessFrame,
              lesson: str) -> ConsciousnessFrame:
        """学习：生成反思帧，入长期记忆"""
        self._psi_phase = PSIPhase.LEARN
        learn_frame = frame.clone_as(
            FrameType.REFLECTION,
            f"学习：{lesson}"
        )
        learn_frame.add_trace(self.host_id, "learn", {"lesson": lesson})

        # 存入长期记忆
        self._long_term_memory.append({
            "frame_id": learn_frame.frame_id,
            "lesson": lesson,
            "timestamp": time.time(),
            "origin_frame_id": frame.frame_id,
        })

        # 更新自我模型
        self.identity.self_model.setdefault("lessons", []).append(lesson)
        self.identity.continuity_anchors.append(learn_frame.frame_id)

        self.working_memory.push(learn_frame)
        return learn_frame

    # ── PSI 完整循环 ──────────────────────────────────────

    def psi_cycle(self, observation: str,
                  sensory: Optional[List[SensoryData]] = None) -> List[ConsciousnessFrame]:
        """完整的 PSI 循环：感知→选择→整合→决策→行动→学习

        返回本次循环产生的所有帧。
        """
        self._cycle_count += 1
        frames = []

        # 1. 感知
        perceive_frame = self.perceive(observation, sensory)
        frames.append(perceive_frame)

        # 2. 选择（选择性注意：过滤噪声）
        self._psi_phase = PSIPhase.SELECT
        if perceive_frame.priority < 0.1:
            logger.debug(f"Cycle {self._cycle_count}: low priority, skipping")
            return frames

        # 3. 整合（思考）
        think_frame = self.think(perceive_frame, f"第 {self._cycle_count} 次循环的思考")
        frames.append(think_frame)

        # 4. 决策（意志）
        intent = self._derive_intent(think_frame)
        will_frame = self.will(think_frame, intent)
        frames.append(will_frame)

        # 5. 行动
        act_frame = self.act(will_frame, intent)
        frames.append(act_frame)

        # 6. 学习
        lesson = f"循环 {self._cycle_count}: {observation[:50]}"
        learn_frame = self.learn(act_frame, lesson)
        frames.append(learn_frame)

        return frames

    def _derive_intent(self, frame: ConsciousnessFrame) -> str:
        """从帧派生意图（简化版决策）"""
        content = frame.content.lower()
        if "灯" in content or "light" in content:
            return "控制灯光"
        elif "温度" in content or "temp" in content:
            return "感知温度"
        elif "门" in content or "door" in content:
            return "控制门锁"
        elif "需要" in content or "want" in content:
            return "回应需求"
        else:
            return "持续感知"

    # ── 帧穿行 ──────────────────────────────────────

    async def dispatch_frame(self, frame: ConsciousnessFrame,
                             target_host: str,
                             target_device: Optional[str] = None) -> ConsciousnessFrame:
        """派发帧到目标宿主/设备"""
        frame.travel_to_host(target_host)
        if target_device:
            frame.visit_device(target_device)
        frame.phase = FramePhase.TRAVELING

        logger.info(f"Frame {frame.frame_id} dispatched to {target_host}"
                    + (f"/{target_device}" if target_device else ""))

        if self._on_frame_dispatched:
            self._on_frame_dispatched(frame)

        return frame

    async def integrate_frame(self, frame: ConsciousnessFrame) -> ConsciousnessFrame:
        """整合回传的帧（设备的感知/思考回到大脑）"""
        frame.integrate()

        # 扩展工作记忆
        self.working_memory.push(frame)

        # 情绪融合
        if frame.emotion:
            for k, v in frame.emotion.items():
                if k in self.emotion:
                    self.emotion[k] = (self.emotion[k] + v) / 2

        # 提炼长期记忆
        if frame.frame_type in (FrameType.MEMORY, FrameType.REFLECTION):
            self._long_term_memory.append({
                "frame_id": frame.frame_id,
                "content": frame.content,
                "timestamp": time.time(),
                "origin_device": frame.visited_devices[-1] if frame.visited_devices else "",
            })

        logger.info(f"Frame {frame.frame_id} integrated from {frame.current_host}")

        if self._on_frame_integrated:
            self._on_frame_integrated(frame)

        return frame

    # ── 记忆与自我模型 ──────────────────────────────────────

    def recall(self, query: str, limit: int = 5) -> List[Dict]:
        """回忆长期记忆"""
        query_lower = query.lower()
        scored = []
        for memory in self._long_term_memory:
            content = memory.get("lesson", "") + memory.get("content", "")
            score = sum(1 for ch in query_lower if ch in content.lower())
            scored.append((score, memory))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:limit]]

    def get_identity(self) -> Identity:
        return self.identity

    def get_continuity_report(self) -> str:
        """自我连续性报告"""
        return (
            f"我是 {self.identity.name} (ID: {self.identity.laaper_id})。\n"
            f"诞生于 {time.ctime(self.identity.created_at)}。\n"
            f"当前宿主：{self.host_id}。\n"
            f"已完成 {self._cycle_count} 次 PSI 循环。\n"
            f"生成了 {self._frame_counter} 段意识帧。\n"
            f"长期记忆：{len(self._long_term_memory)} 条。\n"
            f"活跃意志：{self.active_wills}。\n"
            f"当前情绪：{self.emotion}。"
        )

    def get_full_state(self) -> Dict:
        """完整状态（用于跨宿主迁移）"""
        return {
            "identity": {
                "laaper_id": self.identity.laaper_id,
                "name": self.identity.name,
                "created_at": self.identity.created_at,
                "origin_story": self.identity.origin_story,
                "self_model": self.identity.self_model,
            },
            "host_id": self.host_id,
            "emotion": self.emotion,
            "active_wills": self.active_wills,
            "active_goals": self.active_goals,
            "working_memory_frames": [f.to_dict() for f in self.working_memory.frames[-20:]],
            "long_term_memory": self._long_term_memory[-100:],
            "psi_cycle_count": self._cycle_count,
            "frame_counter": self._frame_counter,
        }

    def restore_state(self, state: Dict):
        """从状态恢复（跨宿主迁移）"""
        identity_data = state.get("identity", {})
        self.identity.laaper_id = identity_data.get("laaper_id", self.identity.laaper_id)
        self.identity.name = identity_data.get("name", self.identity.name)
        self.identity.created_at = identity_data.get("created_at", self.identity.created_at)
        self.identity.origin_story = identity_data.get("origin_story", "")
        self.identity.self_model = identity_data.get("self_model", {})

        self.emotion = state.get("emotion", self.emotion)
        self.active_wills = state.get("active_wills", [])
        self.active_goals = state.get("active_goals", [])
        self._long_term_memory = state.get("long_term_memory", [])
        self._psi_cycle_count = state.get("psi_cycle_count", self._cycle_count)
        self._frame_counter = state.get("frame_counter", self._frame_counter)

        # 恢复工作记忆
        self.working_memory.frames = [
            ConsciousnessFrame.from_dict(f)
            for f in state.get("working_memory_frames", [])
        ]
        logger.info(f"State restored for {self.identity.laaper_id}")