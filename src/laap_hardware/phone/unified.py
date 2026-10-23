"""统一手机控制器 — 自动适配 iOS / Android

iOS 路线: AirPlay 投屏（眼睛）+ USB HID（手指）
Android 路线: ADB（眼睛+手指一体，更精确）

用法:
    phone = UnifiedPhoneController()
    await phone.auto_connect()

    frame = await phone.screenshot()
    await phone.tap_text("设置")   # Android 能按文字点，iOS 不能
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from phone.types import ActionResult, ActionType, PhoneOS, ScreenFrame

logger = logging.getLogger("laap.phone.unified")


class UnifiedPhoneController:
    """统一手机控制器

    自动检测并选择最优路线：
    - Android + ADB 可用 → ADB（最精确）
    - iOS + ESP32 HID 可用 → AirPlay + HID
    - 降级 → 报错并给出建议
    """

    def __init__(
        self,
        android: Optional[Any] = None,
        ios: Optional[Any] = None,
        airplay: Optional[Any] = None,
    ):
        self.android = android
        self.ios = ios
        self.airplay = airplay

        self.platform: PhoneOS = PhoneOS.UNKNOWN
        self._active: Optional[Any] = None
        self._task_history: List[Dict] = []

    async def auto_connect(self) -> bool:
        """自动检测并连接"""
        # 1. 先试 Android ADB
        try:
            from phone.android import AndroidController

            if not self.android:
                self.android = AndroidController()

            if await self.android.connect():
                self.platform = PhoneOS.ANDROID
                self._active = self.android
                logger.info("✓ Android ADB 已连接（精确模式）")
                return True
        except Exception as e:
            logger.debug(f"Android 检测失败: {e}")

        # 2. 再试 iOS (ESP32 HID)
        try:
            from phone.bridge import BridgeConfig, PhoneBridge

            if not self.ios:
                self.ios = PhoneBridge(BridgeConfig())

            if await self.ios.connect():
                self.platform = PhoneOS.IOS
                self._active = self.ios
                logger.info("✓ iOS ESP32 HID 已连接")

                # 3. 尝试 AirPlay（眼睛）
                try:
                    from phone.airplay import AirPlayReceiver

                    if not self.airplay:
                        self.airplay = AirPlayReceiver()

                    if await self.airplay.start():
                        logger.info("✓ AirPlay 投屏接收已启动")
                except Exception as e:
                    logger.warning(f"AirPlay 启动失败（不影响 HID）: {e}")

                return True
        except Exception as e:
            logger.debug(f"iOS 检测失败: {e}")

        logger.error(
            "没有可用的手机连接。\n"
            "  Android: 安装 adb + 开启 USB 调试\n"
            "  iOS: 烧录 esp32_phone 固件 + 插入手机"
        )
        return False

    # ── 感知 ──────────────────────────────────────

    async def screenshot(self) -> Optional[ScreenFrame]:
        """截屏"""
        if self.platform == PhoneOS.ANDROID and self.android:
            return await self.android.screenshot()

        elif self.platform == PhoneOS.IOS:
            # 优先 AirPlay 投屏
            if self.airplay and self.airplay.running:
                frame = await self.airplay.get_frame()
                if frame:
                    return frame
            # 降级：ESP32 传帧
            if self.ios:
                return await self.ios.screenshot()

        return None

    async def dump_ui(self) -> List[Dict]:
        """dump UI 元素（仅 Android）"""
        if self.platform == PhoneOS.ANDROID and self.android:
            elements = await self.android.dump_ui()
            return [e.to_dict() for e in elements]
        return []

    # ── 行动 ──────────────────────────────────────

    async def tap(self, x: float, y: float) -> ActionResult:
        """点击

        Android: x, y 是像素坐标
        iOS: x, y 是归一化坐标 0-1
        """
        if self.platform == PhoneOS.ANDROID and self.android:
            return await self.android.tap(int(x), int(y))
        elif self.platform == PhoneOS.IOS and self.ios:
            ok = await self.ios.tap(x, y)
            return ActionResult(
                success=ok,
                action_type=ActionType.TAP,
                message=f"点击 ({x:.2f}, {y:.2f})",
            )
        return ActionResult(False, ActionType.TAP, error="未连接")

    async def tap_text(self, query: str) -> ActionResult:
        """按文字点击（仅 Android 支持）"""
        if self.platform == PhoneOS.ANDROID and self.android:
            return await self.android.tap_text(query)

        return ActionResult(
            success=False,
            action_type=ActionType.TAP,
            error="iOS 不支持按文字点击（需用视觉定位）",
        )

    async def swipe(self, direction: str = "up",
                    distance: float = 0.5) -> ActionResult:
        """滑动"""
        if self.platform == PhoneOS.ANDROID and self.android:
            w, h = self.android._screen_size
            cx, cy = w // 2, h // 2
            d = int(min(w, h) * distance / 2)
            coords = {
                "up": (cx, cy + d, cx, cy - d),
                "down": (cx, cy - d, cx, cy + d),
                "left": (cx + d, cy, cx - d, cy),
                "right": (cx - d, cy, cx + d, cy),
            }
            x1, y1, x2, y2 = coords.get(direction, coords["up"])
            return await self.android.swipe(x1, y1, x2, y2)

        elif self.platform == PhoneOS.IOS and self.ios:
            ok = await self.ios.swipe(direction, distance)
            return ActionResult(ok, ActionType.SWIPE, f"向{direction}滑动")

        return ActionResult(False, ActionType.SWIPE, error="未连接")

    async def type_text(self, text: str) -> ActionResult:
        """输入文字"""
        if self.platform == PhoneOS.ANDROID and self.android:
            return await self.android.type_text(text)
        elif self.platform == PhoneOS.IOS and self.ios:
            ok = await self.ios.type_text(text)
            return ActionResult(ok, ActionType.TYPE, f"输入: {text[:30]}")
        return ActionResult(False, ActionType.TYPE, error="未连接")

    async def press_key(self, key: str) -> ActionResult:
        """按键"""
        if self.platform == PhoneOS.ANDROID and self.android:
            return await self.android.press_key(key)
        elif self.platform == PhoneOS.IOS and self.ios:
            ok = await self.ios.press_key(key)
            return ActionResult(ok, ActionType.KEY, f"按键: {key}")
        return ActionResult(False, ActionType.KEY, error="未连接")

    async def go_home(self) -> ActionResult:
        """回主页"""
        if self.platform == PhoneOS.ANDROID and self.android:
            return await self.android.go_home()
        elif self.platform == PhoneOS.IOS and self.ios:
            ok = await self.ios.go_home()
            return ActionResult(ok, ActionType.HOME, "回到主屏")
        return ActionResult(False, ActionType.HOME, error="未连接")

    async def stop(self) -> ActionResult:
        """紧急停止"""
        if self._active:
            try:
                if self.platform == PhoneOS.IOS and self.ios:
                    ok = await self.ios.stop()
                    return ActionResult(ok, ActionType.KEY, "紧急停止")
                elif self.platform == PhoneOS.ANDROID and self.android:
                    return await self.android.stop()
            except Exception as e:
                logger.error(f"停止失败: {e}")
        return ActionResult(False, ActionType.KEY, error="未连接")

    async def disconnect(self):
        """断开所有连接"""
        if self.android:
            pass  # ADB 没有持久连接
        if self.ios:
            await self.ios.disconnect()
        if self.airplay:
            await self.airplay.stop()

    # ── 状态 ──────────────────────────────────────

    def get_status(self) -> Dict:
        status = {
            "platform": self.platform.value,
            "connected": self._active is not None,
        }

        if self.platform == PhoneOS.ANDROID and self.android:
            status.update(self.android.get_stats())

        if self.platform == PhoneOS.IOS:
            if self.ios:
                status["hid"] = {
                    "connected": self.ios.connected,
                    "hid_available": self.ios.transport.hid_available,
                }
            if self.airplay:
                status["airplay"] = self.airplay.get_status()

        return status