"""Phone Bridge — 与 ESP32 手机代理固件通信

支持两种传输路线：
1. HID 路线：ESP32 当 USB 鼠标键盘，通过 TCP/WebSocket 发命令
2. NCM 路线：ESP32 当 USB 网卡，提供到手机 CoreDevice 的网络通路

协议参考：
- actell USB 输入协议（ASCII，LF 结尾）
    S -> C: PA3 READY 1        (READY 1 = 有 HID，READY 0 = 仅 NCM)
    C -> S: 1 PING
    S -> C: 1 executed
    C -> S: 2 TAP 1 32768 16384
    S -> C: 2 received
    S -> C: 2 executed
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from phone.types import (
    ActionType,
    PhoneInfo,
    PhoneOS,
    ScreenFrame,
    TouchAction,
    TransportRoute,
)

logger = logging.getLogger("laap.phone.bridge")


@dataclass
class BridgeConfig:
    """桥接配置"""
    host: str = "192.168.7.1"       # ESP32 默认地址（NCM 路线）
    port: int = 28766               # USB 输入协议端口
    route: TransportRoute = TransportRoute.HID

    connect_timeout: float = 5.0
    command_timeout: float = 1.0
    drag_timeout: float = 3.0
    ping_interval: float = 0.2      # 200ms 心跳

    # 屏幕
    screen_width: int = 1170
    screen_height: int = 2532

    # 安全
    require_hid: bool = True


class BridgeTransport:
    """桥接传输层 — 管理到 ESP32 的 TCP 连接"""

    def __init__(self, config: BridgeConfig):
        self.config = config
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

        # HID 状态
        self._hid_available = False
        self._generation = 1
        self._command_id = 0

        # 待确认命令
        self._pending: Dict[int, asyncio.Future] = {}

        # 后台任务
        self._ping_task: Optional[asyncio.Task] = None
        self._read_task: Optional[asyncio.Task] = None

        # 屏幕帧回调
        self._on_frame: Optional[Callable] = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def hid_available(self) -> bool:
        return self._hid_available

    @property
    def generation(self) -> int:
        return self._generation

    async def connect(self) -> bool:
        """连接到 ESP32"""
        try:
            logger.info(
                f"正在连接 ESP32: {self.config.host}:{self.config.port} "
                f"({self.config.route.value})"
            )
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.config.host, self.config.port),
                timeout=self.config.connect_timeout,
            )
            self._connected = True

            # 等待 greeting（最多 3 秒）
            greeting = await asyncio.wait_for(
                self._reader.readline(),
                timeout=3.0,
            )
            line = greeting.decode("ascii", errors="replace").strip()
            logger.info(f"ESP32 greeting: {line}")

            # 解析 PA3 READY N
            if line.startswith("PA3 READY"):
                parts = line.split()
                if len(parts) >= 3:
                    self._hid_available = parts[2] == "1"

            # 验证双向通信
            if not await self._ping():
                logger.warning("ESP32 PING 失败")
                await self.disconnect()
                return False

            # 启动后台任务
            self._read_task = asyncio.create_task(self._read_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())

            logger.info(
                f"ESP32 已连接 (HID: {'可用' if self._hid_available else '不可用'})"
            )
            return True

        except asyncio.TimeoutError:
            logger.error(f"连接 ESP32 超时: {self.config.host}")
            return False
        except Exception as e:
            logger.error(f"连接 ESP32 失败: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        self._connected = False
        for task in (self._ping_task, self._read_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        logger.info("ESP32 已断开")

    async def _ping(self) -> bool:
        """心跳验证"""
        self._command_id += 1
        cmd = f"{self._command_id} PING"
        return await self._send_and_wait(cmd, self._command_id, timeout=1.0)

    async def _ping_loop(self):
        """200ms 心跳循环（保持 HID 就绪状态）"""
        while self._connected:
            try:
                await asyncio.sleep(self.config.ping_interval)
                await self._ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"心跳失败: {e}")

    async def _read_loop(self):
        """读取 ESP32 响应"""
        while self._connected and self._reader:
            try:
                line = await self._reader.readline()
                if not line:
                    break
                text = line.decode("ascii", errors="replace").strip()
                if not text:
                    continue
                await self._handle_line(text)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"读取循环异常: {e}")
                break
        self._connected = False

    async def _handle_line(self, line: str):
        """处理响应行

        格式: <id> <status> [args]
        status: received / executed / cancelled / pushed
        """
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            return

        # 处理推送消息（屏幕帧等）
        if parts[0] == "PUSH":
            await self._handle_push(line)
            return

        try:
            cmd_id = int(parts[0])
        except ValueError:
            return

        status = parts[1]

        future = self._pending.get(cmd_id)
        if not future or future.done():
            return

        if status == "received":
            # 动作已接受，继续等 executed
            return
        elif status in ("executed", "cancelled"):
            future.set_result(status == "executed")

    async def _handle_push(self, line: str):
        """处理设备推送（屏幕帧）"""
        if self._on_frame:
            try:
                await self._on_frame(line)
            except Exception as e:
                logger.error(f"帧回调异常: {e}")

    async def _send_and_wait(
        self,
        command: str,
        cmd_id: int,
        timeout: float = 1.0,
    ) -> bool:
        """发送命令并等待结果"""
        if not self._writer or not self._connected:
            return False

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = future

        try:
            self._writer.write((command + "\n").encode("ascii"))
            await self._writer.drain()

            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"命令超时: {command}")
            return False
        except Exception as e:
            logger.error(f"命令失败: {command} — {e}")
            return False
        finally:
            self._pending.pop(cmd_id, None)

    async def send_action(self, action: TouchAction) -> bool:
        """发送触摸动作"""
        self._command_id += 1
        action.action_id = self._command_id
        action.generation = self._generation

        command = action.to_protocol()
        timeout = (
            self.config.drag_timeout
            if action.action_type in (ActionType.DRAG, ActionType.SWIPE)
            else self.config.command_timeout
        )

        logger.debug(f"发送动作: {command}")
        return await self._send_and_wait(command, self._command_id, timeout)

    async def stop(self) -> bool:
        """停止当前动作（安全释放 HID）"""
        self._command_id += 1
        command = f"{self._command_id} STOP {self._generation}"
        ok = await self._send_and_wait(command, self._command_id, timeout=1.0)
        if ok:
            self._generation += 1
        return ok

    def on_frame(self, callback: Callable):
        """注册屏幕帧回调"""
        self._on_frame = callback


class PhoneBridge:
    """手机桥接 — 高层接口

    封装传输层，提供简洁的 API。
    """

    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config = config or BridgeConfig()
        self.transport = BridgeTransport(self.config)
        self._phone_info = PhoneInfo()
        self._last_frame: Optional[ScreenFrame] = None

    async def connect(self) -> bool:
        """连接设备"""
        ok = await self.transport.connect()
        if ok and self.config.require_hid and not self.transport.hid_available:
            logger.warning("HID 不可用，触摸控制将无法工作")
        return ok

    async def disconnect(self):
        await self.transport.disconnect()

    async def tap(self, x: float, y: float) -> bool:
        """点击（归一化坐标）

        Args:
            x: 0-1 之间的相对横坐标
            y: 0-1 之间的相对纵坐标
        """
        action = TouchAction(
            action_type=ActionType.TAP,
            x=x,
            y=y,
        )
        return await self.transport.send_action(action)

    async def drag(
        self,
        x: float,
        y: float,
        to_x: float,
        to_y: float,
        duration_ms: int = 300,
    ) -> bool:
        """拖拽/滑动"""
        action = TouchAction(
            action_type=ActionType.DRAG,
            x=x,
            y=y,
            to_x=to_x,
            to_y=to_y,
            duration_ms=duration_ms,
        )
        return await self.transport.send_action(action)

    async def swipe(
        self,
        direction: str = "up",
        distance: float = 0.5,
    ) -> bool:
        """方向滑动

        Args:
            direction: up / down / left / right
            distance: 0-1 之间的滑动距离
        """
        cx, cy = 0.5, 0.5
        d = distance / 2

        coords = {
            "up": (cx, cy + d, cx, cy - d),
            "down": (cx, cy - d, cx, cy + d),
            "left": (cx + d, cy, cx - d, cy),
            "right": (cx - d, cy, cx + d, cy),
        }
        if direction not in coords:
            return False

        x, y, tx, ty = coords[direction]
        return await self.drag(x, y, tx, ty, duration_ms=300)

    async def type_text(self, text: str) -> bool:
        """输入文字"""
        action = TouchAction(
            action_type=ActionType.TYPE,
            text=text,
        )
        return await self.transport.send_action(action)

    async def press_key(self, key: str) -> bool:
        """按键（如 enter / escape / home）"""
        action = TouchAction(
            action_type=ActionType.KEY,
            key=key,
        )
        return await self.transport.send_action(action)

    async def go_home(self) -> bool:
        """回到主屏幕"""
        action = TouchAction(action_type=ActionType.HOME)
        return await self.transport.send_action(action)

    async def stop(self) -> bool:
        """紧急停止"""
        return await self.transport.stop()

    def get_info(self) -> PhoneInfo:
        return self._phone_info

    @property
    def last_frame(self) -> Optional[ScreenFrame]:
        return self._last_frame

    @property
    def connected(self) -> bool:
        return self.transport.connected