"""LDP — LAAP Device Protocol（硬件统一接入协议）

## 为什么需要它

四类机器人（宠物/狗/车/桌面）差异巨大，但**对 LAAP 来说它们是同一类东西**：

    它们都能「感知」（摄像头/IMU/触摸/超声）
    它们都能「运动」（轮子/腿/云台）
    它们都能「说话听话」（喇叭/麦克风）

所以协议只需要覆盖三件事 + 一层状态同步，不必为每类机器人单独设计。

## 消息族

    ┌─ 注册 ─────────────────────────────────┐
    │ hello / register      上报身份 + 能力      │
    │ heartbeat             心跳保活             │
    └────────────────────────────────────────┘
    ┌─ 感知 → LAAP ──────────────────────────┐
    │ percept      {sensor, data}            │
    │  sensor: imu / touch / distance / image │
    │          / audio / temperature         │
    └────────────────────────────────────────┘
    ┌─ LAAP → 运动 ──────────────────────────┐
    │ motion.move    {vx, vy, omega}         │
    │ motion.pose    {name}                  │
    │ motion.action  {name, params}          │
    │ motion.stop    {}                       │
    └────────────────────────────────────────┘
    ┌─ 对话 ─────────────────────────────────┐
    │ dialogue.text  {role, text}   双向       │
    │ dialogue.state {state}        listening/│
    │                               thinking/ │
    │                               speaking  │
    └────────────────────────────────────────┘
    ┌─ 状态回报 ──────────────────────────────┐
    │ state.report   {battery, motion, ...}  │
    └────────────────────────────────────────┘

## 传输

复用已有 `laaper/hub` 的三端传输：
  · 局域网 ws://<ip>:8765
  · 云端   wss://api.laap.cn/ws
另有屏幕流专用 :8766（见 screen_stream.py）

二进制帧（音频/图像）与 JSON 文本走同一条 WS，用 opcode 区分。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageKind(str, Enum):
    """LDP 消息类型"""
    # 注册
    HELLO = "hello"
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    HELLO_ACK = "hello_ack"

    # 感知（设备 → LAAP）
    PERCEPT = "percept"

    # 运动（LAAP → 设备）
    MOTION_MOVE = "motion.move"
    MOTION_POSE = "motion.pose"
    MOTION_ACTION = "motion.action"
    MOTION_STOP = "motion.stop"

    # 对话（双向）
    DIALOGUE_TEXT = "dialogue.text"
    DIALOGUE_STATE = "dialogue.state"

    # 状态
    STATE_REPORT = "state.report"
    ERROR = "error"


class MotionCommand(str, Enum):
    """运动动词（跨身体统一的语义层）"""
    MOVE = "move"           # 前进/后退/横移/转向
    POSE = "pose"           # 命名姿态
    ACTION = "action"       # 复合动作
    STOP = "stop"


# 各身体支持的姿态（LAAP 用它做能力协商）
POSES_BY_KIND: Dict[str, List[str]] = {
    "car": ["stop", "home"],
    "dog": ["stand", "sit", "home", "wave"],
    "pet": ["home", "look_up", "look_down", "think", "sleep", "nod"],
}


@dataclass
class LDPMessage:
    """LDP 消息信封"""
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)

    msg_id: str = field(default_factory=lambda: f"ldp_{uuid.uuid4().hex[:10]}")
    device_id: str = ""
    ts: float = field(default_factory=time.time)

    # 可靠投递
    ack_required: bool = False
    reply_to: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "kind": self.kind,
            "payload": self.payload,
            "msg_id": self.msg_id,
            "device_id": self.device_id,
            "ts": self.ts,
            "ack_required": self.ack_required,
            "reply_to": self.reply_to,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Optional["LDPMessage"]:
        try:
            d = json.loads(raw)
        except Exception:
            return None
        return cls(
            kind=d.get("kind", ""),
            payload=d.get("payload", {}) or {},
            msg_id=d.get("msg_id", ""),
            device_id=d.get("device_id", ""),
            ts=d.get("ts", time.time()),
            ack_required=d.get("ack_required", False),
            reply_to=d.get("reply_to", ""),
        )


class LDPProtocol:
    """LDP 协议端：设备侧和 LAAP 侧共用一个实现

    设备侧用法（ESP32 固件或 Python 模拟）：
        p = LDPProtocol(device_id="pet-01", kind="pet")
        await ws.send(p.hello())                  # 注册
        await ws.send(p.percept("imu", {...}))    # 上报感知
        msg = LDPProtocol.from_json(await ws.recv())
        if msg.kind == "motion.move":
            motion.move(**msg.payload)

    LAAP 侧用法：
        p = LDPProtocol(device_id="laap-hub")
        p.on_motion = lambda m: print(m)          # 处理上报
        reply = p.parse(raw)                      # 解析设备消息
    """

    def __init__(
        self,
        device_id: str = "laap-device",
        kind: str = "pet",
        capabilities: Optional[Dict[str, Any]] = None,
        name: str = "LAAP Device",
    ):
        self.device_id = device_id
        self.kind = kind
        self.name = name
        self.capabilities = capabilities or self._default_caps(kind)

        # 上报统计
        self.last_percept: Dict[str, Any] = {}
        self.connected_at = 0.0
        self.heartbeat_at = 0.0

    # ── 能力声明 ──────────────────────────────────

    def _default_caps(self, kind: str) -> Dict[str, Any]:
        """按机器人类型给出默认能力（可覆盖）"""
        base = {
            "sensors": ["imu"],
            "actuators": ["motion"],
            "poses": POSES_BY_KIND.get(kind, []),
            "dialogue": True,
        }
        if kind == "car":
            base["sensors"] += ["encoder", "distance"]
            base["motion"] = "differential"
        elif kind == "dog":
            base["sensors"] += ["touch", "distance"]
            base["motion"] = "quadruped"
            base["joints"] = 12
        elif kind == "pet":
            base["sensors"] += ["touch", "distance", "light"]
            base["motion"] = "pantilt"
            base["display"] = True
        return base

    # ── 消息构造 ──────────────────────────────────

    def hello(self) -> str:
        return LDPMessage(
            kind=MessageKind.HELLO,
            device_id=self.device_id,
            payload={
                "device_id": self.device_id,
                "name": self.name,
                "kind": self.kind,
                "capabilities": self.capabilities,
                "protocol": "ldp/1.0",
            },
        ).to_json()

    def heartbeat(self) -> str:
        self.heartbeat_at = time.time()
        return LDPMessage(
            kind=MessageKind.HEARTBEAT,
            device_id=self.device_id,
            payload={"ts": time.time()},
        ).to_json()

    def percept(self, sensor: str, data: Dict[str, Any]) -> str:
        """上报感知"""
        self.last_percept = {"sensor": sensor, "data": data}
        return LDPMessage(
            kind=MessageKind.PERCEPT,
            device_id=self.device_id,
            payload={"sensor": sensor, "data": data},
        ).to_json()

    def state_report(self, state: Dict[str, Any]) -> str:
        return LDPMessage(
            kind=MessageKind.STATE_REPORT,
            device_id=self.device_id,
            payload=state,
        ).to_json()

    def dialogue_text(self, text: str, role: str = "assistant") -> str:
        return LDPMessage(
            kind=MessageKind.DIALOGUE_TEXT,
            device_id=self.device_id,
            payload={"role": role, "text": text},
        ).to_json()

    def dialogue_state(self, state: str) -> str:
        """listening / thinking / speaking / idle"""
        return LDPMessage(
            kind=MessageKind.DIALOGUE_STATE,
            device_id=self.device_id,
            payload={"state": state},
        ).to_json()

    # ── 下发（LAAP → 设备）──────────────────────────

    def motion_move(self, vx: float = 0, vy: float = 0,
                    omega: float = 0) -> str:
        return LDPMessage(
            kind=MessageKind.MOTION_MOVE,
            device_id=self.device_id,
            payload={"vx": vx, "vy": vy, "omega": omega},
        ).to_json()

    def motion_pose(self, name: str) -> str:
        return LDPMessage(
            kind=MessageKind.MOTION_POSE,
            device_id=self.device_id,
            payload={"name": name},
        ).to_json()

    def motion_action(self, name: str, params: Optional[Dict] = None) -> str:
        return LDPMessage(
            kind=MessageKind.MOTION_ACTION,
            device_id=self.device_id,
            payload={"name": name, "params": params or {}},
        ).to_json()

    def motion_stop(self) -> str:
        return LDPMessage(
            kind=MessageKind.MOTION_STOP,
            device_id=self.device_id,
            payload={},
        ).to_json()

    # ── 解析 ──────────────────────────────────

    def parse(self, raw: str) -> Optional[LDPMessage]:
        """解析一条消息（自动刷新心跳时间）"""
        msg = LDPMessage.from_json(raw)
        if msg and msg.kind == MessageKind.HEARTBEAT:
            self.heartbeat_at = time.time()
        return msg

    def is_alive(self, timeout_s: float = 45.0) -> bool:
        """设备是否还在线（按心跳判断）"""
        if not self.heartbeat_at:
            return False
        return (time.time() - self.heartbeat_at) < timeout_s

    # ── 自然语言 → 运动指令（LAAP 侧的语义映射）─────────────────────

    @staticmethod
    def text_to_motion(text: str, kind: str = "pet") -> Optional[Dict[str, Any]]:
        """把中文指令映射成运动命令

        这是 LAAP 指令层和硬件运动层之间的翻译。

            "往前走"     → {"cmd": "move", "vx": 150}
            "往左转"     → {"cmd": "move", "omega": -60}
            "坐下"       → {"cmd": "pose", "name": "sit"}
            "打个招呼"   → {"cmd": "pose", "name": "wave"}
            "停"         → {"cmd": "stop"}
            "看着我"     → {"cmd": "pose", "name": "look_up"}（宠物）
        """
        t = text.strip()

        # 停止
        if any(k in t for k in ("停", "别动", "站住", "stop")):
            return {"cmd": MotionCommand.STOP.value}

        # 姿态
        pose_map = {
            "坐下": "sit", "坐着": "sit",
            "站起来": "stand", "起立": "stand",
            "回家": "home", "复位": "home",
            "打招呼": "wave", "挥手": "wave",
            "抬头": "look_up", "看着我": "look_up",
            "低头": "look_down",
            "思考": "think", "睡": "sleep", "点一下头": "nod",
        }
        for kw, pose in pose_map.items():
            if kw in t:
                if pose in POSES_BY_KIND.get(kind, []):
                    return {"cmd": MotionCommand.POSE.value, "name": pose}
                # 不支持该姿态时降级为哼一声（由上层处理）
                return None

        # 速度
        speed = 150.0
        if any(k in t for k in ("快", "快点", "加速")):
            speed = 300.0
        if any(k in t for k in ("慢", "慢点", "慢一点")):
            speed = 80.0

        # 方向
        if any(k in t for k in ("前进", "往前", "向前", "走")):
            return {"cmd": MotionCommand.MOVE.value, "vx": speed}
        if any(k in t for k in ("后退", "往后", "倒")):
            return {"cmd": MotionCommand.MOVE.value, "vx": -speed}
        if any(k in t for k in ("左转", "往左", "向左")):
            return {"cmd": MotionCommand.MOVE.value, "omega": 60}
        if any(k in t for k in ("右转", "往右", "向右")):
            return {"cmd": MotionCommand.MOVE.value, "omega": -60}
        if any(k in t for k in ("左移", "横向左")):
            return {"cmd": MotionCommand.MOVE.value, "vy": speed}
        if any(k in t for k in ("右移", "横向右")):
            return {"cmd": MotionCommand.MOVE.value, "vy": -speed}

        return None


# ══════════════════════════════════════════════════════════
#  自检
# ══════════════════════════════════════════════════════════

def self_test() -> Dict:
    """协议收发 + 语义映射自检"""
    p = LDPProtocol(device_id="pet-01", kind="pet")
    hello = p.parse(p.hello())
    percept = p.parse(p.percept("imu", {"roll": 1.2}))
    move = p.parse(p.motion_move(vx=100))

    cases = {
        "往前走": ("move", 150),
        "快点前进": ("move", 300),
        "坐下": ("pose", "sit"),
        "停": ("stop", None),
    }
    results = {}
    for text, (cmd, val) in cases.items():
        r = p.text_to_motion(text, kind="pet")
        results[text] = r

    return {
        "hello_ok": hello is not None and hello.kind == "hello",
        "percept_ok": percept is not None
            and percept.payload.get("sensor") == "imu",
        "move_ok": move is not None and move.payload.get("vx") == 100,
        "caps": p.capabilities,
        "semantic": results,
    }