"""LAAP 三端节点抽象 — 电脑 / 手机 / 小智硬件

## 为什么需要节点抽象

三个载体能力完全不同：

| 节点 | 独有能力 | 缺什么 |
|------|---------|--------|
| 电脑 | 高算力、全 OS 控制、浏览器 | 不能随身 |
| 手机 | 移动、摄像头、GPS、触摸 | 算力低、不能看电脑屏 |
| 小智硬件 | 语音输入输出、物理在场 | 只有嘴和耳朵 |

三者联动的前提是**先把自己的能力说清楚**，中枢才知道该派谁干活。

## 节点能力声明

每个节点上报：
  · 我能感知什么（摄像头/麦克风/传感器/屏幕）
  · 我能行动什么（点击/打字/执行命令/说话）
  · 我有哪些资源（算力/电量/带宽）

中枢据此路由任务。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class NodeKind(str, Enum):
    """节点类型"""
    PC = "pc"                  # 电脑 — 大脑+手
    PHONE = "phone"            # 手机 — 移动感官
    HARDWARE = "hardware"      # 小智硬件 — 嘴和耳朵
    CLOUD = "cloud"            # 云端 — 持久化大脑
    UNKNOWN = "unknown"


class SensorKind(str, Enum):
    """感知能力"""
    SCREEN = "screen"              # 屏幕内容
    CAMERA = "camera"              # 摄像头
    MICROPHONE = "microphone"      # 麦克风
    SPEAKER = "speaker"            # 扬声器
    TOUCH = "touch"                # 触摸
    KEYBOARD = "keyboard"          # 键盘
    MOUSE = "mouse"                # 鼠标
    GPS = "gps"                    # 定位
    MOTION = "motion"              # 加速度/陀螺仪
    TEMPERATURE = "temperature"    # 温度
    HUMIDITY = "humidity"          # 湿度
    PRESSURE = "pressure"          # 压力
    LIGHT = "light"                # 光照
    PROXIMITY = "proximity"        # 接近


class ActuatorKind(str, Enum):
    """行动能力"""
    CLICK = "click"                # 点击
    TYPE = "type"                  # 输入文字
    SHELL = "shell"                # 执行命令
    FILE = "file"                  # 文件操作
    BROWSE = "browse"              # 浏览网页
    SPEAK = "speak"                # 说话（TTS）
    DISPLAY = "display"            # 显示内容
    VIBRATE = "vibrate"            # 震动
    RELAY = "relay"                # 继电器控制


@dataclass
class NodeCapabilities:
    """节点能力声明"""
    sensors: Set[str] = field(default_factory=set)
    actuators: Set[str] = field(default_factory=set)

    # 资源
    compute: float = 1.0           # 算力 0-1（相对）
    battery: float = 1.0           # 电量 0-1
    bandwidth: float = 1.0         # 带宽 0-1
    always_on: bool = False        # 是否常开

    # 限制
    max_payload_kb: int = 10240    # 单次最大数据量
    supports_streaming: bool = False

    def can_sense(self, kind: str) -> bool:
        return kind in self.sensors

    def can_act(self, kind: str) -> bool:
        return kind in self.actuators

    def to_dict(self) -> Dict:
        return {
            "sensors": sorted(self.sensors),
            "actuators": sorted(self.actuators),
            "compute": self.compute,
            "battery": self.battery,
            "bandwidth": self.bandwidth,
            "always_on": self.always_on,
            "max_payload_kb": self.max_payload_kb,
            "supports_streaming": self.supports_streaming,
        }


@dataclass
class NodeInfo:
    """节点信息"""
    node_id: str
    name: str
    kind: NodeKind
    capabilities: NodeCapabilities = field(default_factory=NodeCapabilities)

    # 状态
    online: bool = False
    last_seen: float = 0.0
    connected_at: float = 0.0

    # 元数据
    address: str = ""
    transport: str = "websocket"     # websocket / mcp / http
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def heartbeat(self):
        """更新心跳"""
        self.last_seen = time.time()
        self.online = True

    @property
    def stale(self) -> bool:
        """是否失联（30 秒无心跳）"""
        return self.online and (time.time() - self.last_seen) > 30

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "kind": self.kind.value,
            "capabilities": self.capabilities.to_dict(),
            "online": self.online and not self.stale,
            "last_seen": self.last_seen,
            "address": self.address,
            "transport": self.transport,
            "tags": self.tags,
        }


# ── 预置节点工厂 ──────────────────────────────────

def make_pc_node(node_id: str = "pc-01", name: str = "LAAP 电脑端") -> NodeInfo:
    """电脑节点 — 大脑 + 双手"""
    return NodeInfo(
        node_id=node_id,
        name=name,
        kind=NodeKind.PC,
        capabilities=NodeCapabilities(
            sensors={SensorKind.SCREEN, SensorKind.MICROPHONE,
                     SensorKind.SPEAKER, SensorKind.KEYBOARD, SensorKind.MOUSE},
            actuators={ActuatorKind.CLICK, ActuatorKind.TYPE, ActuatorKind.SHELL,
                       ActuatorKind.FILE, ActuatorKind.BROWSE, ActuatorKind.SPEAK,
                       ActuatorKind.DISPLAY},
            compute=1.0,
            battery=1.0,           # 插电
            bandwidth=1.0,
            always_on=True,
            max_payload_kb=51200,
            supports_streaming=True,
        ),
    )


def make_phone_node(node_id: str = "phone-01", name: str = "LAAP 手机端") -> NodeInfo:
    """手机节点 — 移动感官 + 便携显示屏"""
    return NodeInfo(
        node_id=node_id,
        name=name,
        kind=NodeKind.PHONE,
        capabilities=NodeCapabilities(
            sensors={SensorKind.SCREEN, SensorKind.CAMERA, SensorKind.MICROPHONE,
                     SensorKind.SPEAKER, SensorKind.TOUCH, SensorKind.GPS,
                     SensorKind.MOTION, SensorKind.LIGHT, SensorKind.PROXIMITY},
            actuators={ActuatorKind.CLICK, ActuatorKind.TYPE, ActuatorKind.SPEAK,
                       ActuatorKind.DISPLAY, ActuatorKind.VIBRATE},
            compute=0.4,
            battery=0.8,
            bandwidth=0.6,
            always_on=False,
            max_payload_kb=8192,
            supports_streaming=True,
        ),
    )


def make_hardware_node(node_id: str = "xiaozhi-01",
                       name: str = "小智硬件") -> NodeInfo:
    """小智硬件节点 — 嘴和耳朵，物理在场"""
    return NodeInfo(
        node_id=node_id,
        name=name,
        kind=NodeKind.HARDWARE,
        capabilities=NodeCapabilities(
            sensors={SensorKind.MICROPHONE, SensorKind.TEMPERATURE,
                     SensorKind.HUMIDITY, SensorKind.PRESSURE,
                     SensorKind.LIGHT, SensorKind.PROXIMITY},
            actuators={ActuatorKind.SPEAK, ActuatorKind.RELAY,
                       ActuatorKind.VIBRATE},
            compute=0.05,
            battery=0.9,
            bandwidth=0.4,
            always_on=True,
            max_payload_kb=512,
            supports_streaming=True,
        ),
    )


# ── 任务路由决策 ──────────────────────────────────

@dataclass
class TaskRequirement:
    """任务需要什么"""
    needs_sensors: Set[str] = field(default_factory=set)
    needs_actuators: Set[str] = field(default_factory=set)
    min_compute: float = 0.0
    payload_kb: int = 0
    latency_critical: bool = False


@dataclass
class RoutingDecision:
    """路由决策"""
    node_id: str
    score: float
    reason: str
    fallback_nodes: List[str] = field(default_factory=list)


def score_node_for_task(
    node: NodeInfo,
    req: TaskRequirement,
) -> float:
    """给节点打分（0-1），越高越合适

    这是中枢决定"派谁干活"的核心算法。
    """
    if not node.online or node.stale:
        return 0.0

    caps = node.capabilities

    # 1. 必须有全部所需感知能力
    if not req.needs_sensors.issubset(caps.sensors):
        return 0.0

    # 2. 必须有全部所需行动能力
    if not req.needs_actuators.issubset(caps.actuators):
        return 0.0

    # 3. 算力门槛
    if caps.compute < req.min_compute:
        return 0.0

    # 4. 载荷门槛
    if caps.max_payload_kb < req.payload_kb:
        return 0.0

    score = 0.5

    # 算力加分
    score += caps.compute * 0.2

    # 电量加分（低电量扣分）
    if caps.battery < 0.2:
        score -= 0.3
    else:
        score += caps.battery * 0.1

    # 常开加分
    if caps.always_on:
        score += 0.1

    # 延迟敏感任务偏向电脑
    if req.latency_critical and node.kind == NodeKind.PC:
        score += 0.15

    # 移动任务偏向手机
    if SensorKind.GPS in req.needs_sensors and node.kind == NodeKind.PHONE:
        score += 0.15

    # 语音任务偏向硬件（近人）
    if (ActuatorKind.SPEAK in req.needs_actuators
            and node.kind == NodeKind.HARDWARE):
        score += 0.1

    # 展示任务偏向随身设备
    # “把图发我手机” 这类需求，电脑虽然也能显示，但人要的是手机
    if ActuatorKind.DISPLAY in req.needs_actuators:
        if node.kind in (NodeKind.PHONE, NodeKind.HARDWARE):
            score += 0.25

    # 摄像头/触摸类任务只在手机合理
    if (SensorKind.CAMERA in req.needs_sensors
            or SensorKind.TOUCH in req.needs_sensors):
        if node.kind == NodeKind.PHONE:
            score += 0.2

    return max(0.0, min(1.0, score))


def route_task(
    nodes: List[NodeInfo],
    req: TaskRequirement,
) -> Optional[RoutingDecision]:
    """选择最合适的节点执行任务"""
    scored = []
    for node in nodes:
        s = score_node_for_task(node, req)
        if s > 0:
            scored.append((s, node))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best_node = scored[0]
    fallbacks = [n.node_id for _, n in scored[1:4]]

    # 构建理由
    reasons = []
    if req.needs_sensors:
        reasons.append(f"需要感知 {sorted(req.needs_sensors)}")
    if req.needs_actuators:
        reasons.append(f"需要行动 {sorted(req.needs_actuators)}")
    if req.min_compute > 0:
        reasons.append(f"算力 ≥ {req.min_compute}")

    return RoutingDecision(
        node_id=best_node.node_id,
        score=best_score,
        reason="; ".join(reasons) or "默认最优",
        fallback_nodes=fallbacks,
    )