"""Phone Controller — 手机控制单元

把底层桥接封装成 LAAPer 能理解的"身体部位"。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from phone.bridge import BridgeConfig, PhoneBridge
from phone.types import (
    ActionResult,
    ActionType,
    PhoneInfo,
    PhoneOS,
    ScreenFrame,
    TouchAction,
    TransportRoute,
)

logger = logging.getLogger("laap.phone.controller")


class PhoneController:
    """手机控制器 — LAAPer 的"外部手眼"

    用法:
        phone = PhoneController()
        await phone.connect()

        # 感知
        frame = await phone.screenshot()

        # 行动
        await phone.tap(0.5, 0.8)

        # 会话
        await phone.type_text("你好")
        await phone.press_key("enter")
    """

    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config = config or BridgeConfig()
        self.bridge = PhoneBridge(self.config)

        # 统计数据
        self._actions_total = 0
        self._actions_failed = 0
        self._frames_captured = 0
        self._session_start = 0.0

    # ── 连接管理 ──────────────────────────────────────

    async def connect(self) -> bool:
        """连接手机"""
        ok = await self.bridge.connect()
        if ok:
            self._session_start = time.time()
            logger.info("手机控制器就绪")
        return ok

    async def disconnect(self):
        await self.bridge.disconnect()

    @property
    def connected(self) -> bool:
        return self.bridge.connected

    # ── 感知 ──────────────────────────────────────

    async def screenshot(self) -> Optional[ScreenFrame]:
        """截取手机屏幕

        这是 LAAPer 的"眼睛"。
        """
        if not self.bridge.connected:
            logger.error("未连接，无法截屏")
            return None

        # 通过 HID 协议请求截屏
        # 实际实现中，ESP32 会推送 PUSH FRAME <base64> 消息
        # 这里返回缓存的帧或请求新的
        frame = self.bridge.last_frame
        if frame:
            self._frames_captured += 1
            return frame

        # 首次请求，等待帧推送
        await asyncio.sleep(0.5)
        frame = self.bridge.last_frame
        if frame:
            self._frames_captured += 1
        return frame

    async def get_info(self) -> PhoneInfo:
        """获取手机信息"""
        return self.bridge.get_info()

    # ── 行动 ──────────────────────────────────────

    async def tap(self, x: float, y: float) -> ActionResult:
        """点击屏幕（归一化坐标 0-1）"""
        start = time.time()
        self._actions_total += 1

        ok = await self.bridge.tap(x, y)
        elapsed = (time.time() - start) * 1000

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.TAP,
            message=f"点击 ({x:.2f}, {y:.2f})",
            latency_ms=elapsed,
        )

    async def drag(
        self,
        x: float,
        y: float,
        to_x: float,
        to_y: float,
        duration_ms: int = 300,
    ) -> ActionResult:
        """拖拽"""
        start = time.time()
        self._actions_total += 1

        ok = await self.bridge.drag(x, y, to_x, to_y, duration_ms)
        elapsed = (time.time() - start) * 1000

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.DRAG,
            message=f"拖拽 ({x:.2f},{y:.2f}) → ({to_x:.2f},{to_y:.2f})",
            latency_ms=elapsed,
        )

    async def swipe(self, direction: str = "up",
                    distance: float = 0.5) -> ActionResult:
        """方向滑动"""
        start = time.time()
        self._actions_total += 1

        ok = await self.bridge.swipe(direction, distance)
        elapsed = (time.time() - start) * 1000

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.SWIPE,
            message=f"向{direction}滑动",
            latency_ms=elapsed,
        )

    async def type_text(self, text: str) -> ActionResult:
        """输入文字"""
        start = time.time()
        self._actions_total += 1

        ok = await self.bridge.type_text(text)
        elapsed = (time.time() - start) * 1000

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.TYPE,
            message=f"输入: {text[:30]}",
            latency_ms=elapsed,
        )

    async def press_key(self, key: str) -> ActionResult:
        """按键"""
        start = time.time()
        self._actions_total += 1

        ok = await self.bridge.press_key(key)
        elapsed = (time.time() - start) * 1000

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.KEY,
            message=f"按键: {key}",
            latency_ms=elapsed,
        )

    async def go_home(self) -> ActionResult:
        """回到主屏"""
        start = time.time()
        self._actions_total += 1

        ok = await self.bridge.go_home()
        elapsed = (time.time() - start) * 1000

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.HOME,
            message="回到主屏",
            latency_ms=elapsed,
        )

    async def wait(self, seconds: float = 1.0) -> ActionResult:
        """等待（让界面稳定）"""
        start = time.time()
        await asyncio.sleep(seconds)
        return ActionResult(
            success=True,
            action_type=ActionType.WAIT,
            message=f"等待 {seconds}s",
            latency_ms=(time.time() - start) * 1000,
        )

    async def emergency_stop(self) -> ActionResult:
        """紧急停止（释放所有输入）"""
        ok = await self.bridge.stop()
        return ActionResult(
            success=ok,
            action_type=ActionType.KEY,
            message="紧急停止",
        )

    # ── 统计 ──────────────────────────────────────

    def get_stats(self) -> Dict:
        uptime = time.time() - self._session_start if self._session_start else 0
        return {
            "connected": self.connected,
            "hid_available": self.bridge.transport.hid_available,
            "actions_total": self._actions_total,
            "actions_failed": self._actions_failed,
            "success_rate": round(
                (self._actions_total - self._actions_failed)
                / max(1, self._actions_total) * 100, 1
            ),
            "frames_captured": self._frames_captured,
            "uptime_seconds": round(uptime, 1),
            "route": self.config.route.value,
        }