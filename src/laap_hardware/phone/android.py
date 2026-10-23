"""Android ADB 控制器 — 比 iOS HID 精确得多

Android 有 ADB，可以：
- 精确截屏
- 精确点击
- **直接 dump UI 元素树，拿到坐标！**（不用视觉猜）
- 无线调试，连 ESP32 都不需要

依赖: adb (Android Platform Tools)
"""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

from phone.types import ActionResult, ActionType, ScreenFrame

logger = logging.getLogger("laap.phone.android")


@dataclass
class UIElement:
    """UI 元素 — 安卓能直接拿到这个"""
    text: str = ""
    content_desc: str = ""      # 无障碍描述
    resource_id: str = ""        # 资源 ID
    class_name: str = ""
    package: str = ""
    bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    clickable: bool = False
    enabled: bool = True
    focused: bool = False
    scrollable: bool = False

    @property
    def center(self) -> Tuple[int, int]:
        """元素中心坐标"""
        l, t, r, b = self.bounds
        return ((l + r) // 2, (t + b) // 2)

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "desc": self.content_desc,
            "id": self.resource_id,
            "class": self.class_name,
            "bounds": list(self.bounds),
            "center": list(self.center),
            "clickable": self.clickable,
            "enabled": self.enabled,
        }

    def matches(self, query: str) -> bool:
        """模糊匹配"""
        q = query.lower()
        return (
            q in self.text.lower()
            or q in self.content_desc.lower()
            or q in self.resource_id.lower()
        )


@dataclass
class AndroidConfig:
    """Android 控制器配置"""
    device_id: Optional[str] = None      # 指定设备（多设备时）
    adb_path: str = "adb"                # adb 可执行文件路径
    default_timeout: int = 15            # 命令超时（秒）
    screenshot_quality: int = 80         # JPEG 质量
    dump_ui_timeout: int = 20            # UI dump 超时
    auto_wake: bool = True               # 自动唤醒屏幕


class AndroidController:
    """Android 控制器 — 通过 ADB 精确控制

    用法:
        android = AndroidController()
        await android.connect()

        # 截屏
        frame = await android.screenshot()

        # dump UI 元素（精确坐标！）
        elements = await android.dump_ui()
        btn = next(e for e in elements if e.matches("设置"))
        await android.tap(btn.center[0], btn.center[1])

        # 或者直接按文字点击
        await android.tap_text("设置")
    """

    def __init__(
        self,
        device_id: Optional[str] = None,
        adb_path: str = "adb",
        config: Optional[AndroidConfig] = None,
    ):
        cfg = config or AndroidConfig(device_id=device_id, adb_path=adb_path)
        self.config = cfg
        self.device_id = cfg.device_id
        self.adb_path = cfg.adb_path
        self._connected = False
        self._screen_size = (1080, 2400)

        # 统计
        self._actions_total = 0
        self._actions_failed = 0

    # ── ADB 基础 ──────────────────────────────────────

    def _adb_cmd(self, *args: str) -> List[str]:
        cmd = [self.adb_path]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.extend(args)
        return cmd

    def _run(self, *args: str, timeout: int = 15) -> Tuple[bool, bytes]:
        """同步执行 adb 命令"""
        try:
            result = subprocess.run(
                self._adb_cmd(*args),
                capture_output=True,
                timeout=timeout,
            )
            return result.returncode == 0, result.stdout
        except subprocess.TimeoutExpired:
            logger.error(f"ADB 超时: {' '.join(args)}")
            return False, b""
        except FileNotFoundError:
            logger.error("找不到 adb，请安装 Android Platform Tools")
            return False, b""
        except Exception as e:
            logger.error(f"ADB 执行失败: {e}")
            return False, b""

    async def connect(self) -> bool:
        """连接设备"""
        ok, output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._run("devices")
        )

        if not ok:
            return False

        devices = []
        for line in output.decode("utf-8", errors="replace").splitlines()[1:]:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            dev_id, status = line.split("\t", 1)
            if status.strip() == "device":
                devices.append(dev_id)

        if not devices:
            logger.error("没有已授权的 Android 设备")
            return False

        if not self.device_id:
            self.device_id = devices[0]

        # 获取屏幕尺寸
        ok, output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._run("shell", "wm", "size")
        )
        if ok:
            text = output.decode("utf-8", errors="replace")
            m = re.search(r"(\d+)x(\d+)", text)
            if m:
                self._screen_size = (int(m.group(1)), int(m.group(2)))

        self._connected = True
        logger.info(
            f"Android 已连接: {self.device_id} "
            f"({self._screen_size[0]}x{self._screen_size[1]})"
        )
        return True

    @property
    def connected(self) -> bool:
        return self._connected

    # ── 感知 ──────────────────────────────────────

    async def screenshot(self) -> Optional[ScreenFrame]:
        """截屏 — adb exec-out screencap"""
        self._connected and None

        ok, data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._run("exec-out", "screencap", "-p")
        )

        if not ok or not data:
            logger.error("截屏失败")
            return None

        # 检查是否是有效 PNG
        if not data.startswith(b"\x89PNG"):
            logger.error(f"截屏数据格式错误: {data[:20]}")
            return None

        return ScreenFrame(
            frame_id=f"android_{uuid.uuid4().hex[:8]}",
            data=data,
            width=self._screen_size[0],
            height=self._screen_size[1],
            format="png",
        )

    async def dump_ui(self) -> List[UIElement]:
        """dump UI 元素树 — 这是安卓的杀手锏

        直接拿到所有元素的精确坐标，不用视觉模型猜。
        """
        ok, _ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run("shell", "uiautomator", "dump", "/sdcard/ui.xml")
        )
        if not ok:
            return []

        ok, data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run("exec-out", "cat", "/sdcard/ui.xml")
        )
        if not ok or not data:
            return []

        return self._parse_ui_xml(data.decode("utf-8", errors="replace"))

    def _parse_ui_xml(self, xml_text: str) -> List[UIElement]:
        """解析 uiautomator XML"""
        elements = []
        try:
            # 去掉可能的垃圾前缀
            start = xml_text.find("<?xml")
            if start > 0:
                xml_text = xml_text[start:]

            root = ElementTree.fromstring(xml_text)

            for node in root.iter("node"):
                bounds_str = node.get("bounds", "")
                m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
                if not m:
                    continue

                elem = UIElement(
                    text=node.get("text", ""),
                    content_desc=node.get("content-desc", ""),
                    resource_id=node.get("resource-id", ""),
                    class_name=node.get("class", ""),
                    package=node.get("package", ""),
                    bounds=(
                        int(m.group(1)), int(m.group(2)),
                        int(m.group(3)), int(m.group(4)),
                    ),
                    clickable=node.get("clickable") == "true",
                    enabled=node.get("enabled") == "true",
                    focused=node.get("focused") == "true",
                    scrollable=node.get("scrollable") == "true",
                )

                # 只保留有意义的元素
                if elem.text or elem.content_desc or elem.clickable:
                    elements.append(elem)

        except ElementTree.ParseError as e:
            logger.error(f"UI XML 解析失败: {e}")

        return elements

    async def current_app(self) -> str:
        """获取当前前台应用"""
        ok, data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run("shell", "dumpsys", "window", "|", "grep", "mCurrentFocus")
        )
        if ok:
            text = data.decode("utf-8", errors="replace")
            m = re.search(r"([a-zA-Z0-9_.]+)/", text)
            if m:
                return m.group(1)
        return ""

    # ── 行动 ──────────────────────────────────────

    async def tap(self, x: int, y: int) -> ActionResult:
        """点击（像素坐标）"""
        start = time.time()
        self._actions_total += 1

        ok, _ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run("shell", "input", "tap", str(x), str(y))
        )

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.TAP,
            message=f"点击 ({x}, {y})",
            latency_ms=(time.time() - start) * 1000,
        )

    async def tap_text(self, query: str, index: int = 0) -> ActionResult:
        """按文字点击 — 不用猜坐标！"""
        elements = await self.dump_ui()
        matches = [e for e in elements if e.matches(query) and e.clickable]

        if not matches:
            # 放宽条件：不限 clickable
            matches = [e for e in elements if e.matches(query)]

        if not matches or index >= len(matches):
            return ActionResult(
                success=False,
                action_type=ActionType.TAP,
                error=f"找不到元素: {query}",
            )

        elem = matches[index]
        cx, cy = elem.center
        result = await self.tap(cx, cy)
        result.message = f"点击「{elem.text or elem.content_desc or query}」({cx}, {cy})"
        result.changed = True
        return result

    async def tap_element(self, elem: UIElement) -> ActionResult:
        """点击 UI 元素"""
        cx, cy = elem.center
        return await self.tap(cx, cy)

    async def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
    ) -> ActionResult:
        """滑动"""
        start = time.time()
        self._actions_total += 1

        ok, _ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run(
                "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration_ms)
            )
        )

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.SWIPE,
            message=f"滑动 ({x1},{y1})→({x2},{y2})",
            latency_ms=(time.time() - start) * 1000,
        )

    async def type_text(self, text: str) -> ActionResult:
        """输入文字"""
        start = time.time()
        self._actions_total += 1

        # 空格需要转义
        escaped = text.replace(" ", "%s")
        ok, _ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run("shell", "input", "text", escaped)
        )

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.TYPE,
            message=f"输入: {text[:30]}",
            latency_ms=(time.time() - start) * 1000,
        )

    async def press_key(self, key: str) -> ActionResult:
        """按键（KEYCODE_*）"""
        key_map = {
            "enter": "66",
            "back": "4",
            "home": "3",
            "menu": "82",
            "escape": "111",
            "backspace": "67",
            "delete": "112",
            "volume_up": "24",
            "volume_down": "25",
        }

        code = key_map.get(key, key)
        start = time.time()
        self._actions_total += 1

        ok, _ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run("shell", "input", "keyevent", code)
        )

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.KEY,
            message=f"按键: {key}",
            latency_ms=(time.time() - start) * 1000,
        )

    async def go_home(self) -> ActionResult:
        """回主页"""
        return await self.press_key("home")

    async def launch_app(self, package: str) -> ActionResult:
        """启动应用"""
        start = time.time()
        self._actions_total += 1

        ok, _ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run(
                "shell", "monkey", "-p", package,
                "-c", "android.intent.category.LAUNCHER", "1"
            )
        )

        if not ok:
            self._actions_failed += 1

        return ActionResult(
            success=ok,
            action_type=ActionType.KEY,
            message=f"启动: {package}",
            latency_ms=(time.time() - start) * 1000,
        )

    async def stop(self) -> ActionResult:
        """停止（安卓没有 HID 锁死问题，只回主页）"""
        return await self.go_home()

    def get_stats(self) -> Dict:
        return {
            "platform": "android",
            "connected": self._connected,
            "device_id": self.device_id,
            "screen": f"{self._screen_size[0]}x{self._screen_size[1]}",
            "actions_total": self._actions_total,
            "actions_failed": self._actions_failed,
            "success_rate": round(
                (self._actions_total - self._actions_failed)
                / max(1, self._actions_total) * 100, 1
            ),
        }