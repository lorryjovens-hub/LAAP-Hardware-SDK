"""LAAP Phone Bridge — 手机控制单元

让 LAAPer 通过对话控制真实手机。

## 两条路线

### Android（推荐，最简单）
    adb exec-out screencap    → 截屏
    adb shell input tap       → 点击
    adb shell uiautomator     → UI 元素树（精确坐标，不用猜）

    优势：无线调试，不需要任何额外硬件

### iOS（需要 ESP32）
    AirPlay 投屏              → 眼睛
    USB HID 鼠标键盘          → 手指

    原理：iOS 沙盒拦住 App 截屏/注入触摸，
         但允许 AirPlay 投屏出去 + 外接 USB 外设。
         ESP32 在物理层绕过沙盒的墙。

## 架构

    用户说话
        ↓
    LAAP 认知引擎
        ↓ MCP 工具
    UnifiedPhoneController
        ├─ AndroidController   (ADB)
        └─ PhoneBridge + AirPlay (iOS)
        ↓
    手机屏幕
"""
from phone.types import (
    ScreenFrame,
    TouchAction,
    ActionType,
    PhoneInfo,
    ActionResult,
    PhoneOS,
)
from phone.bridge import PhoneBridge, BridgeConfig, BridgeTransport
from phone.controller import PhoneController
from phone.vision_loop import VisionActionLoop, TaskResult
from phone.mcp_tools import PHONE_TOOLS, PhoneToolHandler

# 新增模块（可用性取决于环境依赖）
try:
    from phone.android import AndroidController, AndroidConfig, UIElement
    _HAS_ANDROID = True
except Exception:
    AndroidController = None
    AndroidConfig = None
    UIElement = None
    _HAS_ANDROID = False

try:
    from phone.vision_model import (
        VisionModelClient, VisionConfig, UIAwareVisionClient
    )
    _HAS_VISION_MODEL = True
except Exception:
    VisionModelClient = None
    VisionConfig = None
    UIAwareVisionClient = None
    _HAS_VISION_MODEL = False

try:
    from phone.airplay import AirPlayReceiver, AirPlayConfig
    _HAS_AIRPLAY = True
except Exception:
    AirPlayReceiver = None
    AirPlayConfig = None
    _HAS_AIRPLAY = False

try:
    from phone.unified import UnifiedPhoneController
    _HAS_UNIFIED = True
except Exception:
    UnifiedPhoneController = None
    _HAS_UNIFIED = False


__all__ = [
    # 核心
    "ScreenFrame",
    "TouchAction",
    "ActionType",
    "PhoneInfo",
    "ActionResult",
    "PhoneOS",
    "UIElement",
    # iOS 路线
    "PhoneBridge",
    "BridgeConfig",
    "BridgeTransport",
    "AirPlayReceiver",
    "AirPlayConfig",
    # Android 路线
    "AndroidController",
    "AndroidConfig",
    # 统一
    "PhoneController",
    "UnifiedPhoneController",
    # 视觉
    "VisionActionLoop",
    "TaskResult",
    "VisionModelClient",
    "VisionConfig",
    "UIAwareVisionClient",
    # MCP
    "PHONE_TOOLS",
    "PhoneToolHandler",
]


def capabilities() -> dict:
    """报告当前环境的能力"""
    import shutil

    return {
        "android_adb": shutil.which("adb") is not None,
        "airplay_uxplay": shutil.which("uxplay") is not None,
        "pyav": _has_module("av"),
        "httpx": _has_module("httpx"),
        "modules": {
            "android": _HAS_ANDROID,
            "vision_model": _HAS_VISION_MODEL,
            "airplay": _HAS_AIRPLAY,
            "unified": _HAS_UNIFIED,
        },
    }


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
