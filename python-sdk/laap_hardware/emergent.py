"""LAAP Hardware Emergent Capability — 涌现能力层

设备组合后产生新能力。像细胞自组织、乐高组合。

核心洞察：
- 温度计 + 继电器 = 恒温器
- 麦克风 + 扬声器 = 语音助手
- 传感器 + 执行器 + 规则 = 智能系统

涌现能力不是预设的，是从设备组合中"长"出来的。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum

logger = logging.getLogger("laap_hardware.emergent")


class CapabilityType(str, Enum):
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    PROCESSOR = "processor"
    BRIDGE = "bridge"


@dataclass
class DeviceComponent:
    """设备组件"""
    device_id: str
    name: str
    capability_type: CapabilityType
    capabilities: List[str]
    tools: List[Dict]
    is_available: bool = True


@dataclass
class EmergentCapability:
    """涌现能力"""
    id: str
    name: str
    description: str
    required_components: List[str]  # 需要的设备能力
    combined_tools: List[Dict]  # 组合后的新工具
    confidence: float = 0.0  # 组合置信度

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "required_components": self.required_components,
            "combined_tools": self.combined_tools,
            "confidence": self.confidence,
        }


class EmergenceEngine:
    """涌现能力引擎

    检测设备组合，自动发现新能力。

    用法：
        engine = EmergenceEngine()
        engine.register_device(device1)
        engine.register_device(device2)
        capabilities = engine.discover_emergent_capabilities()
    """

    # 预定义的涌现模式
    EMERGENCE_PATTERNS = [
        {
            "name": "恒温器",
            "description": "温度控制",
            "required": ["sensor.temperature", "actuator.relay"],
            "emergent_tools": [
                {
                    "name": "thermostat.control",
                    "description": "恒温控制",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target_temp": {"type": "number"},
                            "tolerance": {"type": "number"},
                        },
                    },
                },
            ],
        },
        {
            "name": "语音助手",
            "description": "语音交互",
            "required": ["audio.mic", "audio.speaker"],
            "emergent_tools": [
                {
                    "name": "voice.converse",
                    "description": "语音对话",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"audio_input": {"type": "string"}},
                    },
                },
            ],
        },
        {
            "name": "安防监控",
            "description": "安全监控",
            "required": ["sensor.motion", "actuator.alarm", "display.screen"],
            "emergent_tools": [
                {
                    "name": "security.monitor",
                    "description": "安防监控",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ],
        },
        {
            "name": "环境调控",
            "description": "综合环境控制",
            "required": ["sensor.temperature", "sensor.humidity", "actuator.fan", "actuator.relay"],
            "emergent_tools": [
                {
                    "name": "environment.regulate",
                    "description": "环境调控",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target_temp": {"type": "number"},
                            "target_humidity": {"type": "number"},
                        },
                    },
                },
            ],
        },
        {
            "name": "智能照明",
            "description": "灯光智能控制",
            "required": ["sensor.light", "sensor.motion", "actuator.light"],
            "emergent_tools": [
                {
                    "name": "lighting.auto",
                    "description": "智能照明",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ],
        },
    ]

    def __init__(self):
        self._devices: Dict[str, DeviceComponent] = {}
        self._emergent_capabilities: List[EmergentCapability] = []

    def register_device(self, device_id: str, name: str,
                       capability_type: CapabilityType,
                       capabilities: List[str],
                       tools: List[Dict]):
        """注册设备组件"""
        self._devices[device_id] = DeviceComponent(
            device_id=device_id,
            name=name,
            capability_type=capability_type,
            capabilities=capabilities,
            tools=tools,
        )
        logger.info(f"Registered device: {device_id} ({len(capabilities)} capabilities)")

    def discover_emergent_capabilities(self) -> List[EmergentCapability]:
        """检测涌现能力"""
        # 收集所有可用能力
        all_capabilities: Set[str] = set()
        for device in self._devices.values():
            if device.is_available:
                all_capabilities.update(device.capabilities)

        # 匹配涌现模式
        discovered = []
        for pattern in self.EMERGENCE_PATTERNS:
            required = set(pattern["required"])
            if required.issubset(all_capabilities):
                capability = EmergentCapability(
                    id=f"emergent_{pattern['name']}",
                    name=pattern["name"],
                    description=pattern["description"],
                    required_components=pattern["required"],
                    combined_tools=pattern["emergent_tools"],
                    confidence=0.9,
                )
                discovered.append(capability)

        self._emergent_capabilities = discovered
        logger.info(f"Discovered {len(discovered)} emergent capabilities")
        return discovered

    def get_all_tools(self) -> List[Dict]:
        """获取所有工具（包括涌现能力的工具）"""
        tools = []
        # 原始设备工具
        for device in self._devices.values():
            tools.extend(device.tools)
        # 涌现能力工具
        for cap in self._emergent_capabilities:
            tools.extend(cap.combined_tools)
        return tools

    def call_emergent_tool(self, tool_name: str, args: Dict) -> Any:
        """调用涌现能力工具"""
        # 查找工具
        for cap in self._emergent_capabilities:
            for tool in cap.combined_tools:
                if tool["name"] == tool_name:
                    return self._execute_emergent(tool_name, cap, args)

        raise ValueError(f"Unknown emergent tool: {tool_name}")

    def _execute_emergent(self, tool_name: str, capability: EmergentCapability,
                          args: Dict) -> Any:
        """执行涌现能力（组合多个设备）"""
        if tool_name == "thermostat.control":
            return self._run_thermostat(args)
        elif tool_name == "voice.converse":
            return self._run_voice_converse(args)
        elif tool_name == "security.monitor":
            return self._run_security(args)
        else:
            return {"status": "simulated", "tool": tool_name}

    def _run_thermostat(self, args: Dict) -> Dict:
        """恒温控制：读温度 + 控制继电器"""
        # 这里模拟组合两个设备
        return {
            "status": "controlled",
            "action": "thermostat",
            "target_temp": args.get("target_temp", 22),
            "devices_used": ["sensor.temperature", "actuator.relay"],
        }

    def _run_voice_converse(self, args: Dict) -> Dict:
        """语音对话：麦克风 + 扬声器"""
        return {
            "status": "conversing",
            "action": "voice_converse",
            "devices_used": ["audio.mic", "audio.speaker"],
        }

    def _run_security(self, args: Dict) -> Dict:
        """安防监控：运动 + 警报 + 显示"""
        return {
            "status": "monitoring",
            "action": "security",
            "devices_used": ["sensor.motion", "actuator.alarm", "display.screen"],
        }

    def get_emergence_report(self) -> Dict:
        """涌现能力报告"""
        return {
            "total_devices": len(self._devices),
            "available_devices": sum(1 for d in self._devices.values() if d.is_available),
            "emergent_capabilities": len(self._emergent_capabilities),
            "capabilities": [c.to_dict() for c in self._emergent_capabilities],
            "potential_emergences": self._find_potential(),
        }

    def _find_potential(self) -> List[Dict]:
        """发现潜在的涌现组合（缺少一个组件）"""
        all_capabilities: Set[str] = set()
        for device in self._devices.values():
            if device.is_available:
                all_capabilities.update(device.capabilities)

        potential = []
        for pattern in self.EMERGENCE_PATTERNS:
            required = set(pattern["required"])
            missing = required - all_capabilities
            if 0 < len(missing) <= 1:  # 只差一个组件
                potential.append({
                    "name": pattern["name"],
                    "description": pattern["description"],
                    "missing": list(missing),
                    "current_match": list(required & all_capabilities),
                })
        return potential