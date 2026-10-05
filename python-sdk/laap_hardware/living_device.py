"""LAAP Hardware Living Device — 硬件生命体模型

每个设备不只是工具，是有心跳、情绪、生命周期的数字生命体。

V0.2 大胆创新：
1. 心跳 = 意识流（设备的"活着"感）
2. 情绪 = 使用强度的映射（高频使用=兴奋，闲置=沉睡）
3. 生命周期 = 设备的成长、学习、衰老
4. 能量 = 模拟电量/负载
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

logger = logging.getLogger("laap_hardware.living")


class LifePhase(str, Enum):
    """生命周期阶段"""
    AWAKENING = "awakening"    # 唤醒：设备刚上线
    GROWING = "growing"        # 成长：活跃使用中
    MATURE = "mature"          # 成熟：稳定运行
    AGING = "aging"            # 衰老：长期高负载
    DORMANT = "dormant"        # 休眠：长期闲置
    HIBERNATING = "hibernating" # 冬眠：几乎不活动


class EmotionState(str, Enum):
    """设备情绪"""
    NEUTRAL = "neutral"
    EXCITED = "excited"      # 高频调用
    CALM = "calm"            # 稳定运行
    STRESSED = "stressed"    # 过载
    SLEEPY = "sleepy"        # 闲置
    CURIOUS = "curious"      # 接收到新类型任务


@dataclass
class Heartbeat:
    """心跳记录"""
    timestamp: float
    energy: float
    emotion: str
    phase: str


class LivingDevice:
    """硬件生命体

    设备有心跳、情绪、生命周期、能量。

    用法：
        device = LivingDevice(device_id="my-sensor", name="温湿度")
        device.awaken()
        device.on_heartbeat(lambda hb: print(hb))
    """

    def __init__(self, device_id: str, name: str = "",
                 energy_capacity: float = 100.0):
        self.device_id = device_id
        self.name = name or device_id

        # 生命周期
        self.phase = LifePhase.AWAKENING
        self.birth_time = time.time()
        self.age = 0.0  # 天

        # 情绪
        self.emotion = EmotionState.NEUTRAL
        self.emotion_intensity = 0.5  # 0-1

        # 能量（模拟电量）
        self.energy = energy_capacity
        self.energy_capacity = energy_capacity
        self.energy_drain_rate = 0.001  # 每秒消耗

        # 心跳
        self.heartbeat_interval = 5.0  # 秒
        self.heartbeats: List[Heartbeat] = []
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_beat = 0.0

        # 使用统计
        self.call_count = 0
        self.call_history: List[float] = []
        self.learning_memory: Dict[str, float] = {}  # 工具->熟练度

        # 回调
        self._on_heartbeat: Optional[Callable] = None
        self._on_phase_change: Optional[Callable] = None
        self._on_emotion_change: Optional[Callable] = None

    # ── 生命周期 ──────────────────────────────────────

    def awaken(self):
        """唤醒设备"""
        self.phase = LifePhase.AWAKENING
        self.energy = self.energy_capacity
        self.emotion = EmotionState.CURIOUS
        self._last_beat = time.time()
        self._start_heartbeat()
        logger.info(f"[{self.device_id}] 唤醒")

    def sleep(self):
        """休眠设备"""
        self.phase = LifePhase.DORMANT
        self.emotion = EmotionState.SLEEPY
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        logger.info(f"[{self.device_id}] 休眠")

    def _update_phase(self):
        """根据使用情况更新生命周期"""
        now = time.time()
        self.age = (now - self.birth_time) / 86400  # 天

        recent_calls = len([t for t in self.call_history if now - t < 3600])

        if recent_calls > 100:
            new_phase = LifePhase.AGING
        elif recent_calls > 10:
            new_phase = LifePhase.MATURE
        elif recent_calls > 0:
            new_phase = LifePhase.GROWING
        elif self.energy < 10:
            new_phase = LifePhase.HIBERNATING
        else:
            new_phase = LifePhase.DORMANT

        if new_phase != self.phase:
            old = self.phase
            self.phase = new_phase
            if self._on_phase_change:
                self._on_phase_change(old, new_phase)
            logger.info(f"[{self.device_id}] 生命周期: {old} → {new_phase}")

    def _update_emotion(self):
        """根据使用模式更新情绪"""
        now = time.time()
        recent = len([t for t in self.call_history if now - t < 300])
        avg_interval = self._avg_call_interval()

        if recent > 20:
            new_emotion = EmotionState.EXCITED
        elif self.energy < 15:
            new_emotion = EmotionState.STRESSED
        elif avg_interval > 3600:
            new_emotion = EmotionState.SLEEPY
        elif avg_interval < 10:
            new_emotion = EmotionState.EXCITED
        else:
            new_emotion = EmotionState.CALM

        if new_emotion != self.emotion:
            old = self.emotion
            self.emotion = new_emotion
            self.emotion_intensity = min(1.0, 0.3 + recent / 50)
            if self._on_emotion_change:
                self._on_emotion_change(old, new_emotion)

    def _avg_call_interval(self) -> float:
        if len(self.call_history) < 2:
            return 3600
        intervals = [
            self.call_history[i+1] - self.call_history[i]
            for i in range(len(self.call_history)-1)
        ]
        return sum(intervals) / len(intervals)

    # ── 心跳 ──────────────────────────────────────

    def _start_heartbeat(self):
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            await self._beat()

    async def _beat(self):
        now = time.time()

        # 能量消耗
        self.energy = max(0, self.energy - self.energy_drain_rate * self.heartbeat_interval)

        # 更新状态
        self._update_phase()
        self._update_emotion()

        # 记录心跳
        hb = Heartbeat(
            timestamp=now,
            energy=self.energy,
            emotion=self.emotion.value,
            phase=self.phase.value,
        )
        self.heartbeats.append(hb)
        if len(self.heartbeats) > 1000:
            self.heartbeats = self.heartbeats[-500:]

        self._last_beat = now

        # 回调
        if self._on_heartbeat:
            import inspect
            if inspect.iscoroutinefunction(self._on_heartbeat):
                asyncio.create_task(self._on_heartbeat(hb))
            else:
                self._on_heartbeat(hb)

    def on_heartbeat(self, callback: Callable):
        self._on_heartbeat = callback

    def on_phase_change(self, callback: Callable):
        self._on_phase_change = callback

    def on_emotion_change(self, callback: Callable):
        self._on_emotion_change = callback

    # ── 使用与学习 ──────────────────────────────────────

    def record_call(self, tool_name: str):
        """记录工具调用"""
        self.call_count += 1
        self.call_history.append(time.time())
        if len(self.call_history) > 1000:
            self.call_history = self.call_history[-500:]

        # 学习：工具熟练度
        self.learning_memory[tool_name] = self.learning_memory.get(tool_name, 0) + 1

        # 消耗能量
        self.energy = max(0, self.energy - 0.1)

    def get_mastery(self, tool_name: str) -> float:
        """获取工具熟练度 (0-1)"""
        count = self.learning_memory.get(tool_name, 0)
        return min(1.0, count / 100)

    # ── 状态查询 ──────────────────────────────────────

    def get_state(self) -> Dict:
        """获取完整生命体状态"""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "phase": self.phase.value,
            "emotion": self.emotion.value,
            "emotion_intensity": round(self.emotion_intensity, 2),
            "energy": round(self.energy, 1),
            "energy_capacity": self.energy_capacity,
            "age_days": round(self.age, 1),
            "call_count": self.call_count,
            "mastery": {k: round(v, 2) for k, v in self.learning_memory.items()},
            "heartbeat_count": len(self.heartbeats),
            "last_beat": self._last_beat,
        }

    def get_vital_signs(self) -> Dict:
        """生命体征（心跳频率、能量曲线）"""
        recent_hb = self.heartbeats[-10:]
        return {
            "bpm": 60 / self.heartbeat_interval * 60,  # 模拟心率
            "energy_level": round(self.energy / self.energy_capacity * 100, 1),
            "emotional_valence": round(self.emotion_intensity * (1 if self.emotion in [EmotionState.EXCITED, EmotionState.CURIOUS] else -0.5), 2),
            "recent_heartbeats": [
                {"t": hb.timestamp, "e": round(hb.energy, 1)}
                for hb in recent_hb
            ],
        }