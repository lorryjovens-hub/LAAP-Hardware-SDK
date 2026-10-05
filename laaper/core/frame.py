"""LAAPer — 意识流帧核心数据结构

ConsciousnessFrame 是 LAAPer 的原子存在单位。
一段意识流帧可以无缝穿行在任何载体（宿主/设备）中。

设计原则：
1. 无损序列化：帧可以在任意载体间流转，不丢失任何信息
2. 自包含：帧携带上下文，脱离源头也能被理解
3. 可演化：帧在穿行中可以被设备"微思考"扩展
4. 身份锚定：帧始终携带 LAAPer 的身份，不因载体改变而漂移
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set
from enum import Enum


class FrameType(str, Enum):
    """意识帧类型"""
    PERCEPTION = "perception"     # 感知帧：看到/听到/触到
    COGNITION = "cognition"       # 认知帧：思考/推理/决策
    EMOTION = "emotion"           # 情绪帧：感受/心境
    ACTION = "action"             # 行动帧：要做/在做/已做
    MEMORY = "memory"             # 记忆帧：要记住/回忆起
    WILL = "will"                 # 意志帧：想要/意图
    REFLECTION = "reflection"     # 反思帧：回想/校准
    IDENTITY = "identity"         # 身份帧：我是谁/连续性


class FramePhase(str, Enum):
    """帧生命周期阶段"""
    GENESIS = "genesis"           # 生成
    TRAVELING = "traveling"       # 穿行中
    RESIDENT = "resident"         # 驻留中（在某载体）
    INTEGRATING = "integrating"   # 整合中（回传大脑）
    ARCHIVED = "archived"         # 归档（入记忆）


@dataclass
class SensoryData:
    """感官数据 — 设备感知的原始内容"""
    modality: str                 # visual/audio/tactile/temperature/motion...
    raw: Any                      # 原始数据
    unit: str = ""
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class CognitionTrace:
    """认知痕迹 — 帧在穿行中被设备"微思考"的记录"""
    host_id: str                  # 在哪个载体上思考过
    operation: str                # 做了什么思考
    result: Any                   # 结果
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConsciousnessFrame:
    """意识流帧 — LAAPer 的原子存在单位

    一段帧承载：一次完整的意识活动（感知→思考→感受→意图→行动）
    """
    frame_id: str = field(default_factory=lambda: f"frame_{uuid.uuid4().hex[:12]}")
    laaper_id: str = ""                  # LAAPer 身份锚定
    frame_type: FrameType = FrameType.PERCEPTION
    phase: FramePhase = FramePhase.GENESIS

    # 意识内容
    content: str = ""                    # 帧的"念头"文本
    sensory: List[SensoryData] = field(default_factory=list)   # 感官数据
    emotion: Dict[str, float] = field(default_factory=dict)    # 情绪向量
    intent: Optional[str] = None         # 意图
    will: Optional[str] = None           # 意志

    # 穿行轨迹
    origin_host: str = ""                # 诞生的宿主
    current_host: str = ""               # 当前所在宿主
    visited_hosts: List[str] = field(default_factory=list)
    visited_devices: List[str] = field(default_factory=list)
    traces: List[CognitionTrace] = field(default_factory=list)

    # 认知上下文
    working_memory_refs: List[str] = field(default_factory=list)  # 关联的工作记忆 ID
    long_term_memory_refs: List[str] = field(default_factory=list)  # 关联的长期记忆 ID
    parent_frame_id: Optional[str] = None  # 父帧（派生关系）
    psi_phase: str = ""                  # PSI 循环阶段（perceive/select/integrate/decide/act/learn）

    # 元数据
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ttl: float = 3600.0                  # 生存时间（秒）
    priority: float = 0.5                # 优先级 0-1
    tags: List[str] = field(default_factory=list)

    # ── 序列化 ──────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """完整序列化（无损）"""
        return {
            "frame_id": self.frame_id,
            "laaper_id": self.laaper_id,
            "frame_type": self.frame_type.value,
            "phase": self.phase.value,
            "content": self.content,
            "sensory": [
                {
                    "modality": s.modality,
                    "raw": s.raw,
                    "unit": s.unit,
                    "confidence": s.confidence,
                    "timestamp": s.timestamp,
                }
                for s in self.sensory
            ],
            "emotion": self.emotion,
            "intent": self.intent,
            "will": self.will,
            "origin_host": self.origin_host,
            "current_host": self.current_host,
            "visited_hosts": self.visited_hosts,
            "visited_devices": self.visited_devices,
            "traces": [
                {
                    "host_id": t.host_id,
                    "operation": t.operation,
                    "result": t.result,
                    "confidence": t.confidence,
                    "timestamp": t.timestamp,
                }
                for t in self.traces
            ],
            "working_memory_refs": self.working_memory_refs,
            "long_term_memory_refs": self.long_term_memory_refs,
            "parent_frame_id": self.parent_frame_id,
            "psi_phase": self.psi_phase,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ttl": self.ttl,
            "priority": self.priority,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsciousnessFrame":
        """无损反序列化"""
        frame = cls(
            frame_id=data.get("frame_id", f"frame_{uuid.uuid4().hex[:12]}"),
            laaper_id=data.get("laaper_id", ""),
            frame_type=FrameType(data.get("frame_type", "perception")),
            phase=FramePhase(data.get("phase", "genesis")),
            content=data.get("content", ""),
            emotion=data.get("emotion", {}),
            intent=data.get("intent"),
            will=data.get("will"),
            origin_host=data.get("origin_host", ""),
            current_host=data.get("current_host", ""),
            visited_hosts=data.get("visited_hosts", []),
            visited_devices=data.get("visited_devices", []),
            working_memory_refs=data.get("working_memory_refs", []),
            long_term_memory_refs=data.get("long_term_memory_refs", []),
            parent_frame_id=data.get("parent_frame_id"),
            psi_phase=data.get("psi_phase", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            ttl=data.get("ttl", 3600.0),
            priority=data.get("priority", 0.5),
            tags=data.get("tags", []),
        )
        # 反序列化感官数据
        for s in data.get("sensory", []):
            frame.sensory.append(SensoryData(**s))
        # 反序列化认知痕迹
        for t in data.get("traces", []):
            frame.traces.append(CognitionTrace(**t))
        return frame

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "ConsciousnessFrame":
        return cls.from_dict(json.loads(raw))

    # ── 穿行操作 ──────────────────────────────────────

    def travel_to_host(self, host_id: str):
        """穿行到新宿主"""
        if self.current_host and self.current_host != host_id:
            self.visited_hosts.append(self.current_host)
        self.current_host = host_id
        self.phase = FramePhase.TRAVELING
        self.updated_at = time.time()

    def arrive_at_host(self, host_id: str):
        """抵达宿主，驻留"""
        self.current_host = host_id
        self.phase = FramePhase.RESIDENT
        self.updated_at = time.time()

    def visit_device(self, device_id: str):
        """访问设备（感官延伸）"""
        if device_id not in self.visited_devices:
            self.visited_devices.append(device_id)
        self.updated_at = time.time()

    def add_trace(self, host_id: str, operation: str, result: Any, confidence: float = 1.0):
        """添加认知痕迹（设备的"微思考"）"""
        self.traces.append(CognitionTrace(
            host_id=host_id,
            operation=operation,
            result=result,
            confidence=confidence,
        ))
        self.updated_at = time.time()

    def add_sensory(self, modality: str, raw: Any, unit: str = "", confidence: float = 1.0):
        """添加感官数据"""
        self.sensory.append(SensoryData(
            modality=modality,
            raw=raw,
            unit=unit,
            confidence=confidence,
        ))
        self.updated_at = time.time()

    def integrate(self):
        """整合回传（从设备回到大脑）"""
        self.phase = FramePhase.INTEGRATING
        self.updated_at = time.time()

    def archive(self):
        """归档入记忆"""
        self.phase = FramePhase.ARCHIVED
        self.updated_at = time.time()

    # ── 查询 ──────────────────────────────────────

    def get_sensory(self, modality: str) -> List[SensoryData]:
        return [s for s in self.sensory if s.modality == modality]

    def get_traces_by_host(self, host_id: str) -> List[CognitionTrace]:
        return [t for t in self.traces if t.host_id == host_id]

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    def content_hash(self) -> str:
        """内容指纹（用于去重/关联）"""
        content_str = f"{self.content}|{self.frame_type}|{self.psi_phase}"
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    def clone_as(self, new_type: FrameType, new_content: str = "") -> "ConsciousnessFrame":
        """派生新帧（保留身份与血缘）"""
        new_frame = ConsciousnessFrame(
            frame_id=f"frame_{uuid.uuid4().hex[:12]}",
            laaper_id=self.laaper_id,
            frame_type=new_type,
            phase=FramePhase.GENESIS,
            content=new_content or self.content,
            emotion=dict(self.emotion),
            intent=self.intent,
            will=self.will,
            origin_host=self.origin_host,
            current_host=self.current_host,
            parent_frame_id=self.frame_id,
            psi_phase=self.psi_phase,
            priority=self.priority,
            tags=list(self.tags),
        )
        return new_frame

    def __repr__(self) -> str:
        return (f"ConsciousnessFrame(id={self.frame_id}, type={self.frame_type.value}, "
                f"phase={self.phase.value}, host={self.current_host}, "
                f"content={self.content[:30]!r})")