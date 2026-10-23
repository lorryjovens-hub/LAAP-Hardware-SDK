"""LAAP 统一会话 — 一段对话在三端共享

## 核心问题

你在小智上说了句话，这句话要不要同步到电脑和手机？
你在电脑上看到的截图，小智需不需要"知道"？

## 设计判断：数据分层

不做全量同步。把数据分两层：

### 控制面（轻量，全端同步）
    · 说了什么话（文字）
    · 谁在说（节点标识）
    · 意图、情绪、当前任务
    · 数据引用 ID（不是数据本身）

    几十字节到几 KB，随便同步。

### 数据面（重载，按需拉取）
    · 截图（几百 KB - 几 MB）
    · 录音、视频（几 MB）
    · 文件内容

    只传引用 ID，谁需要谁去拉。这样小智硬件不会因为
    收到一张 4K 截图而爆内存。

## 对应到实现

    SessionMessage.payload_refs  →  数据引用
    SessionMessage.text          →  控制面内容
    MessageStore                 →  数据面存储（本地可缓存）
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"                  # 用户说的
    LAAPER = "laaper"              # LAAPer 说的
    SYSTEM = "system"              # 系统事件
    NODE_EVENT = "node_event"      # 节点状态变化
    TOOL_RESULT = "tool_result"    # 工具执行结果


class PayloadKind(str, Enum):
    """载荷类型"""
    SCREENSHOT = "screenshot"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    IMAGE = "image"
    DOM = "dom"
    JSON = "json"


@dataclass
class PayloadRef:
    """数据引用 — 轻量指针，指向真实数据

    这样跨端只传指针，不传几 MB 的图。
    """
    payload_id: str = field(default_factory=lambda: f"pl_{uuid.uuid4().hex[:10]}")
    kind: str = PayloadKind.JSON
    size_bytes: int = 0
    mime: str = ""
    origin_node: str = ""

    # 存储位置：本地路径 或 内存缓存 key
    local_path: str = ""
    cache_key: str = ""

    # 摘要（让其他端不拉取也能知道这是什么）
    summary: str = ""

    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "payload_id": self.payload_id,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "mime": self.mime,
            "origin_node": self.origin_node,
            "local_path": self.local_path,
            "cache_key": self.cache_key,
            "summary": self.summary,
        }


@dataclass
class SessionMessage:
    """会话消息 — 控制面内容"""
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:10]}")
    session_id: str = ""
    role: str = MessageRole.USER

    # 内容（轻量）
    text: str = ""
    intent: str = ""
    emotion: Dict[str, float] = field(default_factory=dict)

    # 来源
    origin_node: str = ""
    origin_node_kind: str = ""

    # 数据引用（重载数据只在本地）
    payload_refs: List[PayloadRef] = field(default_factory=list)

    # 时间
    created_at: float = field(default_factory=time.time)

    # 关联的意识帧
    frame_id: str = ""

    def to_dict(self, include_refs: bool = True) -> Dict:
        d = {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role,
            "text": self.text,
            "intent": self.intent,
            "emotion": self.emotion,
            "origin_node": self.origin_node,
            "origin_node_kind": self.origin_node_kind,
            "created_at": self.created_at,
            "frame_id": self.frame_id,
        }
        if include_refs:
            d["payload_refs"] = [r.to_dict() for r in self.payload_refs]
        return d

    def to_broadcast(self) -> Dict:
        """转成广播用（给弱设备，去掉大数据的路径细节）"""
        return {
            "message_id": self.message_id,
            "role": self.role,
            "text": self.text,
            "origin_node": self.origin_node,
            "created_at": self.created_at,
            "has_attachments": bool(self.payload_refs),
            "attachment_count": len(self.payload_refs),
            "attachment_kinds": [r.kind for r in self.payload_refs],
            "attachment_summaries": [r.summary for r in self.payload_refs],
        }


@dataclass
class UnifiedSession:
    """统一会话 — 三端共享的一段对话"""
    session_id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:10]}")
    laaper_id: str = ""

    # 参与者
    participant_nodes: List[str] = field(default_factory=list)

    # 消息
    messages: List[SessionMessage] = field(default_factory=list)

    # 状态
    active_task: str = ""
    active_node: str = ""           # 当前由谁在执行
    mood: str = ""
    goal: str = ""

    # 时间
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    max_messages: int = 500         # 内存上限

    def add_message(self, msg: SessionMessage) -> SessionMessage:
        """添加消息"""
        msg.session_id = self.session_id
        self.messages.append(msg)
        self.updated_at = time.time()

        # 裁剪
        if len(self.messages) > self.max_messages:
            # 保留最早 10 条 + 最近 80%
            keep_head = self.messages[:10]
            keep_tail = self.messages[-(self.max_messages - 10):]
            self.messages = keep_head + keep_tail

        # 记录参与者
        if msg.origin_node and msg.origin_node not in self.participant_nodes:
            self.participant_nodes.append(msg.origin_node)

        return msg

    def recent(self, n: int = 10) -> List[SessionMessage]:
        """最近 n 条"""
        return self.messages[-n:]

    def context_for_llm(self, n: int = 12) -> str:
        """转成 LLM 上下文

        这是三端"共享同一段记忆"的实现方式。
        """
        lines = []
        for m in self.recent(n):
            role = {
                MessageRole.USER: "用户",
                MessageRole.LAAPER: "LAAPer",
                MessageRole.SYSTEM: "系统",
                MessageRole.NODE_EVENT: "节点",
                MessageRole.TOOL_RESULT: "工具",
            }.get(m.role, m.role)

            # 标注来源节点
            origin = ""
            if m.origin_node:
                origin = f"@{m.origin_node}"

            text = m.text[:300]
            if len(m.text) > 300:
                text += "..."

            # 附件提示
            attach = ""
            if m.payload_refs:
                kinds = ", ".join(r.kind for r in m.payload_refs)
                attach = f" [附件: {kinds}]"

            lines.append(f"{role}{origin}: {text}{attach}")

        return "\n".join(lines)

    def stats(self) -> Dict:
        return {
            "session_id": self.session_id,
            "laaper_id": self.laaper_id,
            "messages": len(self.messages),
            "participants": self.participant_nodes,
            "active_task": self.active_task,
            "active_node": self.active_node,
            "mood": self.mood,
            "duration_s": round(time.time() - self.created_at, 1),
        }


# ── 数据面存储 ──────────────────────────────────

class PayloadStore:
    """载荷存储 — 重载数据留本地"""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or Path.home() / ".laap" / "payloads")
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存
        self._cache: Dict[str, Any] = {}
        self._refs: Dict[str, PayloadRef] = {}

    def put(
        self,
        data: Any,
        kind: str = PayloadKind.JSON,
        origin_node: str = "",
        summary: str = "",
        mime: str = "",
    ) -> PayloadRef:
        """存入载荷，返回引用"""
        ref = PayloadRef(
            kind=kind,
            origin_node=origin_node,
            summary=summary,
            mime=mime,
        )

        # 计算大小
        if isinstance(data, bytes):
            ref.size_bytes = len(data)
        elif isinstance(data, str):
            ref.size_bytes = len(data.encode("utf-8"))
        else:
            import json
            ref.size_bytes = len(json.dumps(data, default=str).encode("utf-8"))

        # 存盘（大于 1KB 的）
        if ref.size_bytes > 1024:
            ext = {
                PayloadKind.SCREENSHOT: ".png",
                PayloadKind.IMAGE: ".png",
                PayloadKind.AUDIO: ".wav",
                PayloadKind.VIDEO: ".mp4",
                PayloadKind.DOM: ".html",
                PayloadKind.JSON: ".json",
            }.get(kind, ".bin")

            path = self.base_dir / f"{ref.payload_id}{ext}"
            try:
                if isinstance(data, bytes):
                    path.write_bytes(data)
                elif isinstance(data, str):
                    path.write_text(data, encoding="utf-8")
                else:
                    import json
                    path.write_text(
                        json.dumps(data, ensure_ascii=False, default=str),
                        encoding="utf-8",
                    )
                ref.local_path = str(path)
            except Exception:
                pass

        # 内存缓存（小数据）
        if ref.size_bytes <= 1024 * 100:
            self._cache[ref.payload_id] = data

        self._refs[ref.payload_id] = ref
        return ref

    def get(self, payload_id: str) -> Optional[Any]:
        """取出载荷"""
        if payload_id in self._cache:
            return self._cache[payload_id]

        ref = self._refs.get(payload_id)
        if not ref or not ref.local_path:
            return None

        try:
            return Path(ref.local_path).read_bytes()
        except Exception:
            return None

    def get_ref(self, payload_id: str) -> Optional[PayloadRef]:
        return self._refs.get(payload_id)

    def stats(self) -> Dict:
        total_bytes = sum(r.size_bytes for r in self._refs.values())
        return {
            "payloads": len(self._refs),
            "total_mb": round(total_bytes / 1024 / 1024, 2),
            "cached": len(self._cache),
            "dir": str(self.base_dir),
        }