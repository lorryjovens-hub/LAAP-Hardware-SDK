"""LHP 设备主类 — 让任何设备成为 LAAP 的躯体"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from laap_hardware.protocol import LHPMessage, LHPProtocol, LHPMethod
from laap_hardware.transport import Transport, WebSocketTransport
from laap_hardware.tools import ToolRegistry

logger = logging.getLogger("laap_hardware.device")


class LAAPDevice:
    """LAAP 硬件设备

    将任何设备（ESP32、树莓派、Linux）变成 LAAP 数字生命体的躯体。

    用法：
        device = LAAPDevice(device_id="my-pi", name="我的树莓派")
        device.add_capability("sensor.temperature")
        device.add_tool("read_temp", lambda args: "22.5°C")
        await device.connect("wss://broker.laap.dev/lhp?token=...")
    """

    def __init__(self, device_id: str, name: str = "",
                 device_type: str = "generic",
                 firmware_version: str = "0.1.0"):
        self.device_id = device_id
        self.name = name or device_id
        self.device_type = device_type
        self.firmware_version = firmware_version

        self.capabilities: Dict[str, List[str]] = {
            "sensors": [],
            "actuators": [],
            "display": [],
            "audio": [],
            "io": [],
        }
        self.tools = ToolRegistry()

        self._transport: Optional[Transport] = None
        self._connected = False
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None

        # 回调
        self._on_tool_call: Optional[Callable] = None
        self._on_message: Optional[Callable] = None

    # ── 能力与工具 ──────────────────────────────────────

    def add_capability(self, capability: str):
        """添加设备能力，如 'sensor.temperature'"""
        parts = capability.split(".", 1)
        if len(parts) == 2:
            category, name = parts
            if category in self.capabilities:
                if name not in self.capabilities[category]:
                    self.capabilities[category].append(name)

    def add_tool(self, name: str, handler: Callable,
                 description: str = "", input_schema: Optional[Dict] = None):
        """添加工具"""
        self.tools.register(name, handler, description, input_schema)

    # ── 事件回调 ──────────────────────────────────────

    def on_tool_call(self, callback: Callable):
        self._on_tool_call = callback

    def on_message(self, callback: Callable):
        self._on_message = callback

    # ── 连接 ──────────────────────────────────────

    async def connect(self, url: str, transport: str = "websocket") -> bool:
        """连接到 LAAP Broker"""
        if transport == "websocket":
            self._transport = WebSocketTransport(url)
        else:
            logger.error(f"Unsupported transport: {transport}")
            return False

        self._transport.on_message(self._handle_raw_message)
        ok = await self._transport.connect()
        if ok:
            self._connected = True
            await self._register()
            self._start_heartbeat()
            logger.info(f"Device {self.device_id} connected")
        return ok

    async def disconnect(self):
        self._connected = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._transport:
            await self._transport.close()

    # ── 注册 ──────────────────────────────────────

    async def _register(self):
        """注册设备"""
        self._request_id += 1
        msg = LHPProtocol.create_request(
            id=self._request_id,
            method=LHPMethod.DEVICE_REGISTER,
            params={
                "device_id": self.device_id,
                "name": self.name,
                "device_type": self.device_type,
                "firmware_version": self.firmware_version,
                "capabilities": self.capabilities,
                "tools": self.tools.list_tools(),
            }
        )
        await self._send(msg)

    # ── 心跳 ──────────────────────────────────────

    def _start_heartbeat(self):
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        while self._connected:
            await asyncio.sleep(30)
            self._request_id += 1
            msg = LHPProtocol.create_request(
                id=self._request_id,
                method=LHPMethod.DEVICE_HEARTBEAT,
                params={"device_id": self.device_id, "timestamp": time.time()}
            )
            await self._send(msg)

    # ── 消息处理 ──────────────────────────────────────

    async def _handle_raw_message(self, raw: str):
        try:
            msg = LHPMessage.from_json(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid message: {e}")
            return

        if msg.is_request():
            await self._handle_request(msg)
        elif msg.is_response():
            self._handle_response(msg)
        elif msg.is_notification():
            await self._handle_notification(msg)

    async def _handle_request(self, msg: LHPMessage):
        method = msg.method
        params = msg.params or {}

        if method == LHPMethod.TOOLS_CALL:
            await self._handle_tool_call(msg)
        elif method == LHPMethod.DEVICE_HEALTH:
            await self._handle_health(msg)
        elif method == LHPMethod.MESSAGE_RECEIVE:
            if self._on_message:
                await self._on_message(params.get("content", ""))
        else:
            # 未知请求
            resp = LHPProtocol.create_error(msg.id, -32601, f"Unknown method: {method}")
            await self._send(resp)

    async def _handle_tool_call(self, msg: LHPMessage):
        params = msg.params or {}
        tool_name = params.get("tool_name", "")
        args = params.get("args", {})

        try:
            result = self.tools.call(tool_name, args)
            resp = LHPProtocol.create_response(msg.id, {
                "status": "ok",
                "result": result,
            })
        except Exception as e:
            resp = LHPProtocol.create_response(msg.id, {
                "status": "error",
                "error": str(e),
            })
        await self._send(resp)

    async def _handle_health(self, msg: LHPMessage):
        resp = LHPProtocol.create_response(msg.id, {
            "device_id": self.device_id,
            "status": "online",
            "uptime": time.time(),
            "capabilities": self.capabilities,
            "tool_count": len(self.tools.list_tools()),
        })
        await self._send(resp)

    def _handle_response(self, msg: LHPMessage):
        if msg.id in self._pending_requests:
            future = self._pending_requests.pop(msg.id)
            future.set_result(msg.result)

    async def _handle_notification(self, msg: LHPMessage):
        method = msg.method
        params = msg.params or {}

        if method == LHPMethod.MESSAGE_RECEIVE:
            if self._on_message:
                await self._on_message(params.get("content", ""))

    # ── 发送 ──────────────────────────────────────

    async def _send(self, msg: LHPMessage):
        if self._transport and self._transport.is_connected():
            await self._transport.send(msg.to_json())

    async def send_message(self, content: str):
        """发送消息给 LAAP"""
        self._request_id += 1
        msg = LHPProtocol.create_request(
            id=self._request_id,
            method=LHPMethod.MESSAGE_SEND,
            params={"device_id": self.device_id, "content": content}
        )
        await self._send(msg)

    async def call_remote_tool(self, tool_name: str, args: Dict) -> Any:
        """调用远程工具"""
        self._request_id += 1
        rid = self._request_id
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[rid] = future

        msg = LHPProtocol.create_request(
            id=rid,
            method=LHPMethod.TOOLS_CALL,
            params={"tool_name": tool_name, "args": args}
        )
        await self._send(msg)

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            return {"status": "error", "error": "Timeout"}