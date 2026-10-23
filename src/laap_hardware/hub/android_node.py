"""Android 节点 — 把手机真正接入三端联动

## 为什么安卓这条路值得优先做

iOS 要 AirPlay + USB HID，硬件门槛高。安卓有 ADB，是降维打击：

    adb exec-out screencap      截屏
    adb shell input tap         点击
    adb shell uiautomator dump  UI 元素树（精确坐标）

而且 **支持无线调试**：手机和电脑同一个 Wi-Fi，`adb connect 192.168.x.x:5555`
之后不用插线。这让"手机作为三端之一"变得零成本。

## 接入中枢

    from laaper.hub import TriNodeHub
    from laaper.hub.android_node import register_android_node

    hub = TriNodeHub(laaper_id="aris")
    hub.register_phone("phone-01")

    ok = await register_android_node(hub, "phone-01")
    # 手机就会出现在节点列表里，能截屏、能点击

## 能力映射

    Android 能力            →  节点能力
    截屏                     →  screen 感知
    摄像头拍照               →  camera 感知
    GPS 定位                 →  gps 感知
    点击/滑动/输入           →  click/type 行动
    显示内容                 →  display 行动
    震动                     →  vibrate 行动
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laaper.hub.android")


def find_adb() -> Optional[str]:
    """查找 adb 可执行文件"""
    # 1. 环境变量
    env_adb = os.environ.get("ADB_PATH")
    if env_adb and Path(env_adb).exists():
        return env_adb

    # 2. LAAP 自带
    candidates = [
        r"D:\LAAP\tools\platform-tools\adb.exe",
        str(Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"),
        "/usr/local/bin/adb",
        "/usr/bin/adb",
    ]
    for c in candidates:
        if Path(c).exists():
            return c

    # 3. PATH
    return shutil.which("adb")


@dataclass
class AndroidDeviceInfo:
    """安卓设备信息"""
    serial: str = ""
    state: str = ""              # device / offline / unauthorized
    model: str = ""
    android_version: str = ""
    screen_size: tuple = (1080, 2400)
    transport: str = "usb"       # usb / tcpip


class AndroidBridge:
    """Android ADB 桥接

    封装 adb 命令，提供感知和动作。
    """

    def __init__(self, adb_path: Optional[str] = None, serial: str = ""):
        self.adb_path = adb_path or find_adb()
        self.serial = serial
        self._devices: List[AndroidDeviceInfo] = []
        self._screen_size = (1080, 2400)

        # 统计
        self.stats = {
            "screenshots": 0,
            "taps": 0,
            "swipes": 0,
            "types": 0,
            "ui_dumps": 0,
            "failures": 0,
        }

    @property
    def available(self) -> bool:
        return self.adb_path is not None

    # ── 基础命令 ──────────────────────────────────

    def _cmd(self, *args: str) -> List[str]:
        cmd = [self.adb_path or "adb"]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return cmd

    def _run(
        self,
        *args: str,
        timeout: int = 20,
        binary: bool = False,
    ) -> tuple[bool, Any]:
        """同步执行 adb"""
        try:
            result = subprocess.run(
                self._cmd(*args),
                capture_output=True,
                timeout=timeout,
            )
            out = result.stdout
            if not binary:
                out = out.decode("utf-8", errors="replace")
            return result.returncode == 0, out
        except subprocess.TimeoutExpired:
            self.stats["failures"] += 1
            logger.error(f"adb 超时: {' '.join(args)}")
            return False, b"" if binary else ""
        except Exception as e:
            self.stats["failures"] += 1
            logger.error(f"adb 异常: {e}")
            return False, b"" if binary else ""

    async def _run_async(
        self,
        *args: str,
        timeout: int = 20,
        binary: bool = False,
    ) -> tuple[bool, Any]:
        """异步执行 adb"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._run(*args, timeout=timeout, binary=binary)
        )

    # ── 设备发现 ──────────────────────────────────

    async def list_devices(self) -> List[AndroidDeviceInfo]:
        """列出已连接的安卓设备"""
        ok, out = await self._run_async("devices", "-l")
        if not ok:
            return []

        devices = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            serial = parts[0]
            state = parts[1]

            info = AndroidDeviceInfo(serial=serial, state=state)
            info.transport = "tcpip" if ":" in serial else "usb"

            # 解析型号
            for p in parts[2:]:
                if p.startswith("model:"):
                    info.model = p[6:].replace("_", " ")

            if state == "device":
                info.android_version = await self._get_prop(
                    "ro.build.version.release", serial
                )
                info.screen_size = await self._get_screen_size(serial)

            devices.append(info)

        self._devices = devices
        return devices

    async def _get_prop(self, prop: str, serial: str = "") -> str:
        args = ["-s", serial, "shell", "getprop", prop] if serial else \
               ["shell", "getprop", prop]
        ok, out = await self._run_async(*args)
        return out.strip() if ok else ""

    async def _get_screen_size(self, serial: str = "") -> tuple:
        args = ["-s", serial, "shell", "wm", "size"] if serial else \
               ["shell", "wm", "size"]
        ok, out = await self._run_async(*args)
        if ok and "x" in out:
            import re
            m = re.search(r"(\d+)x(\d+)", out)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        return (1080, 2400)

    async def connect_wireless(self, address: str, port: int = 5555) -> bool:
        """无线连接（手机和电脑同一 Wi-Fi）"""
        target = f"{address}:{port}" if ":" not in address else address
        logger.info(f"无线连接安卓: {target}")
        ok, out = await self._run_async("connect", target, timeout=20)
        if ok and ("connected" in out.lower()):
            self.serial = target
            return True
        logger.error(f"无线连接失败: {out}")
        return False

    async def enable_tcpip(self, port: int = 5555) -> bool:
        """开启无线调试（需要先 USB 连接一次）"""
        ok, out = await self._run_async("tcpip", str(port))
        return ok and "restarting" in out.lower()

    async def connect(self, serial: str = "") -> bool:
        """连接设备"""
        if not self.available:
            logger.error("adb 不可用")
            return False

        devices = await self.list_devices()
        usable = [d for d in devices if d.state == "device"]

        if not usable:
            logger.error(
                "没有可用的安卓设备。检查：\n"
                "  1. 手机开启了 USB 调试\n"
                "  2. 数据线是数据线不是充电线\n"
                "  3. 手机已授权这台电脑（屏幕上有弹窗要点允许）"
            )
            return False

        if serial:
            match = [d for d in usable if d.serial == serial]
            if not match:
                logger.error(f"找不到设备 {serial}")
                return False
            self.serial = serial
        else:
            self.serial = usable[0].serial

        self._screen_size = usable[0].screen_size
        logger.info(
            f"已连接安卓: {self.serial} "
            f"({usable[0].model}, Android {usable[0].android_version}, "
            f"{self._screen_size[0]}x{self._screen_size[1]})"
        )
        return True

    # ── 感知 ──────────────────────────────────

    async def screenshot(self) -> Optional[bytes]:
        """截屏，返回 PNG bytes"""
        ok, data = await self._run_async(
            "exec-out", "screencap", "-p", timeout=25, binary=True
        )

        if not ok or not data or len(data) < 100:
            self.stats["failures"] += 1
            return None

        self.stats["screenshots"] += 1
        return data

    async def dump_ui(self) -> List[Dict]:
        """dump UI 元素树

        这是安卓最大的优势：直接拿到精确坐标，不用视觉猜。
        """
        # dump 到设备
        ok, _ = await self._run_async(
            "shell", "uiautomator", "dump", "/sdcard/window_dump.xml",
            timeout=25,
        )
        if not ok:
            return []

        # 拉回来
        ok, xml = await self._run_async(
            "exec-out", "cat", "/sdcard/window_dump.xml",
            timeout=20, binary=False,
        )
        if not ok or not xml:
            return []

        self.stats["ui_dumps"] += 1
        return self._parse_ui_xml(xml)

    def _parse_ui_xml(self, xml: str) -> List[Dict]:
        """解析 uiautomator XML"""
        import re

        elements = []

        # 逐个 node 解析
        pattern = re.compile(r"<node\s+([^>]+?)/?>", re.S)

        for i, m in enumerate(pattern.finditer(xml)):
            attrs_str = m.group(1)

            # 解析属性
            attrs = {}
            for am in re.finditer(r'([\w-]+)="([^"]*)"', attrs_str):
                attrs[am.group(1)] = am.group(2)

            # 跳过无意义的
            if not attrs.get("clickable") == "true" and \
               not attrs.get("text") and \
               not attrs.get("content-desc") and \
               attrs.get("class", "").split(".")[-1] not in (
                   "EditText", "Button", "TextView", "ImageView",
               ):
                continue

            # 解析 bounds
            bounds = attrs.get("bounds", "")
            bm = re.search(
                r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds
            )
            if not bm:
                continue

            x1, y1, x2, y2 = map(int, bm.groups())
            w = x2 - x1
            h = y2 - y1

            if w < 3 or h < 3:
                continue

            sw, sh = self._screen_size
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2

            elements.append({
                "index": i,
                "text": attrs.get("text", ""),
                "desc": attrs.get("content-desc", ""),
                "class": attrs.get("class", "").split(".")[-1],
                "package": attrs.get("package", ""),
                "resource_id": attrs.get("resource-id", ""),
                "clickable": attrs.get("clickable") == "true",
                "enabled": attrs.get("enabled") == "true",
                "scrollable": attrs.get("scrollable") == "true",
                "checked": attrs.get("checked") == "true",
                "focused": attrs.get("focused") == "true",
                "bounds": [x1, y1, x2, y2],
                "center": [int(cx), int(cy)],
                "nx": round(cx / sw, 3),
                "ny": round(cy / sh, 3),
                "size": [w, h],
            })

        return elements

    async def get_current_app(self) -> Dict:
        """当前前台应用"""
        ok, out = await self._run_async(
            "shell", "dumpsys", "window", timeout=20
        )
        if not ok:
            return {}

        import re
        m = re.search(r"mCurrentFocus=Window\{[^}]*\s([\w.]+)/([\w.]+)\}",
                      out)
        if m:
            return {"package": m.group(1), "activity": m.group(2)}
        return {}

    # ── 行动 ──────────────────────────────────

    async def tap(self, x: int, y: int) -> bool:
        ok, _ = await self._run_async("shell", "input", "tap",
                                      str(int(x)), str(int(y)))
        if ok:
            self.stats["taps"] += 1
        return ok

    async def tap_normalized(self, nx: float, ny: float) -> bool:
        """按归一化坐标点击"""
        sw, sh = self._screen_size
        return await self.tap(int(nx * sw), int(ny * sh))

    async def long_press(self, x: int, y: int, duration_ms: int = 800) -> bool:
        ok, _ = await self._run_async(
            "shell", "input", "swipe",
            str(int(x)), str(int(y)), str(int(x)), str(int(y)),
            str(duration_ms),
        )
        return ok

    async def swipe(
        self,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300,
    ) -> bool:
        ok, _ = await self._run_async(
            "shell", "input", "swipe",
            str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)),
            str(duration_ms),
        )
        if ok:
            self.stats["swipes"] += 1
        return ok

    async def type_text(self, text: str) -> bool:
        """输入文字（中文需要特殊处理）"""
        # 转义 shell 特殊字符
        safe = text.replace(" ", "%s").replace("'", "").replace('"', "")
        ok, _ = await self._run_async("shell", "input", "text", safe)
        if ok:
            self.stats["types"] += 1
        return ok

    async def tap_text(self, query: str) -> bool:
        """按文字找元素并点击（安卓独有优势）"""
        elements = await self.dump_ui()
        q = query.lower()

        # 优先精确匹配
        for e in elements:
            if e["text"].lower() == q or e["desc"].lower() == q:
                if e["clickable"]:
                    return await self.tap(e["center"][0], e["center"][1])

        # 模糊匹配
        for e in elements:
            hay = f'{e["text"]} {e["desc"]} {e["resource_id"]}'.lower()
            if q in hay:
                return await self.tap(e["center"][0], e["center"][1])

        logger.warning(f"找不到文字: {query}")
        return False

    async def press_key(self, key: str) -> bool:
        """按键"""
        key_map = {
            "back": "KEYCODE_BACK",
            "home": "KEYCODE_HOME",
            "recent": "KEYCODE_APP_SWITCH",
            "enter": "KEYCODE_ENTER",
            "power": "KEYCODE_POWER",
            "volume_up": "KEYCODE_VOLUME_UP",
            "volume_down": "KEYCODE_VOLUME_DOWN",
            "delete": "KEYCODE_DEL",
        }
        code = key_map.get(key.lower(), key)
        ok, _ = await self._run_async("shell", "input", "keyevent", code)
        return ok

    async def launch_app(self, package: str) -> bool:
        """启动应用"""
        ok, _ = await self._run_async(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        return ok

    async def vibrate(self, duration_ms: int = 300) -> bool:
        """震动"""
        ok, _ = await self._run_async(
            "shell", "cmd", "vibrator", "vibrate", str(duration_ms)
        )
        return ok

    async def get_battery(self) -> Dict:
        """电量"""
        ok, out = await self._run_async("shell", "dumpsys", "battery")
        if not ok:
            return {}

        import re
        info = {}
        for key, pattern in (
            ("level", r"level:\s*(\d+)"),
            ("status", r"status:\s*(\d+)"),
            ("temperature", r"temperature:\s*(\d+)"),
        ):
            m = re.search(pattern, out)
            if m:
                info[key] = int(m.group(1))

        return info

    def get_stats(self) -> Dict:
        return {
            "adb": self.adb_path,
            "serial": self.serial,
            "screen": f"{self._screen_size[0]}x{self._screen_size[1]}",
            **self.stats,
        }


# ══════════════════════════════════════════════════════════
#  注册到三端中枢
# ══════════════════════════════════════════════════════════

async def register_android_node(
    hub: Any,
    node_id: str = "phone-01",
    adb_path: Optional[str] = None,
    serial: str = "",
    auto_connect: bool = True,
) -> Dict[str, Any]:
    """把安卓设备接入三端中枢

    返回注册结果。
    """
    bridge = AndroidBridge(adb_path=adb_path, serial=serial)

    if not bridge.available:
        return {
            "success": False,
            "error": "找不到 adb。安装方式：\n"
                     "  Windows: 下载 Android Platform Tools\n"
                     "  macOS: brew install android-platform-tools\n"
                     "  Linux: sudo apt install adb",
        }

    # 连接
    if auto_connect:
        if not await bridge.connect(serial):
            return {
                "success": False,
                "error": "没有可用的安卓设备（检查 USB 调试是否开启）",
                "adb": bridge.adb_path,
            }

    # 更新节点能力（真实能力，不是声明）
    node = hub.nodes.get(node_id)
    if node:
        battery = await bridge.get_battery()
        if "level" in battery:
            node.capabilities.battery = battery["level"] / 100.0

        # 真实屏幕尺寸写入元数据
        node.metadata["screen_size"] = list(bridge._screen_size)
        node.metadata["adb"] = bridge.adb_path
        node.metadata["serial"] = bridge.serial

        # 安卓确认有摄像头和 GPS 才加
        node.capabilities.sensors.update({"camera", "gps", "touch"})

    hub.heartbeat(node_id)

    # ── 注册处理器 ────────────────────────────────

    # 截屏
    async def screenshot(params: Dict) -> Dict:
        data = await bridge.screenshot()
        if not data:
            return {"success": False, "error": "手机截屏失败"}

        ref = hub.payloads.put(
            data,
            kind="screenshot",
            origin_node=node_id,
            summary="手机截屏",
            mime="image/png",
        )
        return {
            "success": True,
            "data": {
                "payload_id": ref.payload_id,
                "path": ref.local_path,
                "size_kb": ref.size_bytes // 1024,
                "screen": f"{bridge._screen_size[0]}x{bridge._screen_size[1]}",
            },
        }

    hub.transport.register_handler(node_id, "screenshot", screenshot)

    # UI dump
    async def ui_dump(params: Dict) -> Dict:
        elements = await bridge.dump_ui()
        app = await bridge.get_current_app()
        return {
            "success": True,
            "data": {
                "elements": elements[:100],
                "count": len(elements),
                "current_app": app,
            },
        }

    hub.transport.register_handler(node_id, "ui_dump", ui_dump)

    # 点击（归一化坐标）
    async def tap(params: Dict) -> Dict:
        nx = params.get("x", 0.5)
        ny = params.get("y", 0.5)

        if "text" in params:
            ok = await bridge.tap_text(params["text"])
            return {
                "success": ok,
                "data": {"text": params["text"]},
                "error": "" if ok else f"找不到文字 {params['text']}",
            }

        ok = await bridge.tap_normalized(nx, ny)
        return {
            "success": ok,
            "data": {"x": nx, "y": ny},
            "error": "" if ok else "点击失败",
        }

    hub.transport.register_handler(node_id, "tap", tap)
    hub.transport.register_handler(node_id, "click", tap)

    # 输入
    async def type_text(params: Dict) -> Dict:
        text = params.get("text", "")
        ok = await bridge.type_text(text)
        return {
            "success": ok,
            "data": {"text": text[:50]},
            "error": "" if ok else "输入失败",
        }

    hub.transport.register_handler(node_id, "type", type_text)

    # 滑动
    async def swipe(params: Dict) -> Dict:
        direction = params.get("direction", "up")
        sw, sh = bridge._screen_size
        cx, cy = sw // 2, sh // 2
        d = int(min(sw, sh) * 0.3)

        coords = {
            "up": (cx, cy + d, cx, cy - d),
            "down": (cx, cy - d, cx, cy + d),
            "left": (cx + d, cy, cx - d, cy),
            "right": (cx - d, cy, cx + d, cy),
        }
        x1, y1, x2, y2 = coords.get(direction, coords["up"])
        ok = await bridge.swipe(x1, y1, x2, y2)
        return {"success": ok, "data": {"direction": direction}}

    hub.transport.register_handler(node_id, "swipe", swipe)

    # 按键
    async def press_key(params: Dict) -> Dict:
        key = params.get("key", "back")
        ok = await bridge.press_key(key)
        return {"success": ok, "data": {"key": key}}

    hub.transport.register_handler(node_id, "press_key", press_key)

    # 启动应用
    async def launch_app(params: Dict) -> Dict:
        package = params.get("package", "")
        if not package:
            return {"success": False, "error": "未提供 package"}
        ok = await bridge.launch_app(package)
        return {"success": ok, "data": {"package": package}}

    hub.transport.register_handler(node_id, "launch_app", launch_app)

    # 震动
    async def vibrate(params: Dict) -> Dict:
        ok = await bridge.vibrate(params.get("duration_ms", 300))
        return {"success": ok, "data": {"vibrated": ok}}

    hub.transport.register_handler(node_id, "vibrate", vibrate)
    hub.transport.register_handler(node_id, "display", vibrate)  # 用震动提示

    # 电量
    async def battery(params: Dict) -> Dict:
        return {"success": True, "data": await bridge.get_battery()}

    hub.transport.register_handler(node_id, "battery", battery)

    return {
        "success": True,
        "node_id": node_id,
        "serial": bridge.serial,
        "adb": bridge.adb_path,
        "screen": f"{bridge._screen_size[0]}x{bridge._screen_size[1]}",
        "handlers": [
            "screenshot", "ui_dump", "tap", "click", "type",
            "swipe", "press_key", "launch_app", "vibrate", "display", "battery",
        ],
        "bridge": bridge,
    }


def get_android_status() -> Dict:
    """安卓环境状态（不连接）"""
    adb = find_adb()
    return {
        "adb_available": adb is not None,
        "adb_path": adb,
        "hint": (
            "adb 就绪"
            if adb
            else "未找到 adb。下载 Android Platform Tools 或设置 ADB_PATH"
        ),
    }