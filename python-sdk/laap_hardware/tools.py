"""LHP 工具注册与调用"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap_hardware.tools")


@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str = ""
    input_schema: Dict = field(default_factory=dict)
    handler: Optional[Callable] = None

    def to_mcp(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, name: str, handler: Callable,
                 description: str = "", input_schema: Optional[Dict] = None):
        self._tools[name] = Tool(
            name=name,
            description=description,
            input_schema=input_schema or {},
            handler=handler,
        )

    def list_tools(self) -> List[Dict]:
        return [t.to_mcp() for t in self._tools.values()]

    def call(self, name: str, args: Dict) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        if not tool.handler:
            raise ValueError(f"Tool {name} has no handler")
        return tool.handler(args)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools