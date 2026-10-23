"""手机控制的数据类型"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ActionType(str, Enum):
    """动作类型"""
    TAP = "tap"
    DRAG = "drag"
    TYPE = "type"
    KEY = "key"
    HOME = "home"
    BACK = "back"
    SWIPE = "swipe"
    SCREENSHOT = "screenshot"
    WAIT = "wait"


class PhoneOS(str, Enum):
    """手机系统"""
    IOS = "ios"
    ANDROID = "android"
    UNKNOWN = "unknown"


class TransportRoute(str, Enum):
    """传输路线"""
    HID = "hid"           # USB HID 鼠标键盘（推荐）
    NCM = "ncm"           # USB 网卡 + CoreDevice
    BLUETOOTH_HID = "ble"  # 蓝牙 HID


@dataclass
class ScreenFrame:
    """屏幕帧 — LAAPer 的眼睛看到的画面"""
    frame_id: str
    timestamp: float = field(default_factory=time.time)

    # 图像数据
    data: bytes = b""
    width: int = 0
    height: int = 0
    format: str = "jpeg"       # jpeg / png / h264
    rotation: int = 0          # 0 / 90 / 180 / 270

    # 状态
    foreground_app: str = ""
    is_locked: bool = False

    def to_dict(self) -> Dict:
        return {
            "frame_id": self.frame_id,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "foreground_app": self.foreground_app,
            "is_locked": self.is_locked,
            "size_bytes": len(self.data),
        }

    def size_kb(self) -> float:
        return round(len(self.data) / 1024, 1)


@dataclass
class TouchAction:
    """触摸动作

    坐标使用归一化值（0-1），与分辨率无关。
    """
    action_type: ActionType

    # 坐标（归一化 0-1）
    x: float = 0.0
    y: float = 0.0
    to_x: float = 0.0
    to_y: float = 0.0

    # 时间
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)

    # 文本/按键
    text: str = ""
    key: str = ""

    # 元数据
    generation: int = 1
    action_id: int = 0

    def to_protocol(self) -> str:
        """转换成 ESP32 HID 协议命令（ASCII 格式）

        参考 actell 的 USB 输入协议：
            id TAP generation x y
            id DRAG generation x y tx ty duration
            id STOP generation
        """
        # 归一化坐标 → 16 位整数（0-65535）
        px = max(0, min(65535, int(self.x * 65535)))
        py = max(0, min(65535, int(self.y * 65535)))
        tx = max(0, min(65535, int(self.to_x * 65535)))
        ty = max(0, min(65535, int(self.to_y * 65535)))

        if self.action_type == ActionType.TAP:
            return f"{self.action_id} TAP {self.generation} {px} {py}"
        elif self.action_type in (ActionType.DRAG, ActionType.SWIPE):
            dur = max(100, min(2000, self.duration_ms or 300))
            return f"{self.action_id} DRAG {self.generation} {px} {py} {tx} {ty} {dur}"
        elif self.action_type == ActionType.TYPE:
            return f"{self.action_id} TYPE {self.generation} {self.text}"
        elif self.action_type == ActionType.KEY:
            return f"{self.action_id} KEY {self.generation} {self.key}"
        elif self.action_type == ActionType.HOME:
            return f"{self.action_id} HOME {self.generation}"
        else:
            return f"{self.action_id} PING"

    def to_dict(self) -> Dict:
        return {
            "type": self.action_type.value,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "to_x": round(self.to_x, 4),
            "to_y": round(self.to_y, 4),
            "duration_ms": self.duration_ms,
            "text": self.text,
            "key": self.key,
        }


@dataclass
class PhoneInfo:
    """手机信息"""
    os_type: PhoneOS = PhoneOS.UNKNOWN
    os_version: str = ""
    model: str = ""
    screen_width: int = 0
    screen_height: int = 0
    scale: float = 1.0
    is_locked: bool = False


@dataclass
class ActionResult:
    """动作执行结果"""
    success: bool
    action_type: ActionType
    message: str = ""
    changed: bool = False           # 屏幕是否变化
    new_frame: Optional[ScreenFrame] = None
    error: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "action": self.action_type.value,
            "message": self.message,
            "changed": self.changed,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 1),
        }