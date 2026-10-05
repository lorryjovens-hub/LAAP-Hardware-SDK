"""LHP 消息格式与协议"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional
from enum import Enum


class LHPMethod(str, Enum):
    # 设备生命周期
    DEVICE_REGISTER = "device.register"
    DEVICE_HEARTBEAT = "device.heartbeat"
    DEVICE_HEALTH = "device.health"
    DEVICE_OFFLINE = "device.offline"

    # 工具调用
    TOOLS_LIST = "tools.list"
    TOOLS_CALL = "tools.call"
    TOOLS_RESULT = "tools.result"

    # 消息传递
    MESSAGE_SEND = "message.send"
    MESSAGE_RECEIVE = "message.receive"

    # 配对与安全
    PAIRING_START = "pairing.start"
    PAIRING_CONFIRM = "pairing.confirm"
    SESSION_ROTATE = "session.rotate"

    # 心跳
    PING = "ping"
    PONG = "pong"


@dataclass
class LHPMessage:
    """LHP JSON-RPC 消息"""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        data = {"jsonrpc": self.jsonrpc}
        if self.id is not None:
            data["id"] = self.id
        if self.method:
            data["method"] = self.method
        if self.params is not None:
            data["params"] = self.params
        if self.result is not None:
            data["result"] = self.result
        if self.error is not None:
            data["error"] = self.error
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "LHPMessage":
        data = json.loads(raw)
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            method=data.get("method"),
            params=data.get("params"),
            result=data.get("result"),
            error=data.get("error"),
        )

    def is_request(self) -> bool:
        return self.method is not None and self.id is not None

    def is_notification(self) -> bool:
        return self.method is not None and self.id is None

    def is_response(self) -> bool:
        return self.method is None and self.id is not None


class LHPProtocol:
    """LHP 协议处理器"""

    @staticmethod
    def create_request(id: int, method: str, params: Optional[Dict] = None) -> LHPMessage:
        return LHPMessage(id=id, method=method, params=params or {})

    @staticmethod
    def create_notification(method: str, params: Optional[Dict] = None) -> LHPMessage:
        return LHPMessage(method=method, params=params or {})

    @staticmethod
    def create_response(id: int, result: Any = None) -> LHPMessage:
        return LHPMessage(id=id, result=result)

    @staticmethod
    def create_error(id: int, code: int, message: str) -> LHPMessage:
        return LHPMessage(id=id, error={"code": code, "message": message})