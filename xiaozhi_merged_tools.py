"""
xiaozhi_merged_tools.py — 两套工具合并注册表

把两套能力并到一张表上，让一台小智硬件同时拥有：
  · 生产版 25 个（ask_aris / tell_hana / pc_run / recall / kemo_music / dev_task ...）
  · LAAP-Agent-Kit 13 个（voice_command / pc_click / pc_type / 浏览器视觉 / 多步任务）

═══════════════════════════════════════════════════════════
名字冲突：pc_status / pc_windows 两边都有，语义不同
═══════════════════════════════════════════════════════════
  生产版  pc_status   = LAAP 服务健康（走 LAAP HTTP /health/all）
  kit 版  pc_status   = 本机状态（屏幕/窗口，走 pyautogui/uiautomation）
  生产版  pc_windows  = 经 LAAP HTTP 查窗口
  kit 版  pc_windows  = 本机窗口枚举

MCP 工具名必须唯一，所以四种解法（CollisionStrategy）：
  PREFER_PROD   生产版占原名，kit 版改名 pc_local_status / pc_local_windows
  PREFER_KIT    kit 版占原名，生产版改名 laap_status_x / laap_windows_x
  MERGE_SEMANTIC 一个工具同时返回两边结果（信息最全，但返回变长）
  ALL_RENAME    两边都加前缀，38 个名字完全独立（最清晰，名字最长）
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── 位置 ────────────────────────────────────────────────
PROD_PATH = Path(r"D:\LAAP\scripts\xiaozhi_mcp_server.py")
KIT_ROOT = Path(r"C:\Users\user\Desktop\LAAP-Agent-Kit")

# 生产版与 kit 版都有的名字
COLLIDING = ("pc_status", "pc_windows")


class CollisionStrategy(str, Enum):
    PREFER_PROD = "prefer_prod"
    PREFER_KIT = "prefer_kit"
    MERGE_SEMANTIC = "merge_semantic"
    ALL_RENAME = "all_rename"


@dataclass
class ToolEntry:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Any]
    origin: str                      # "prod" | "kit" | "merged"
    renamed_from: Optional[str] = None

    def to_mcp(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class MergeResult:
    tools: List[ToolEntry] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    prod_count: int = 0
    kit_count: int = 0

    @property
    def count(self) -> int:
        return len(self.tools)

    def by_name(self) -> Dict[str, ToolEntry]:
        return {t.name: t for t in self.tools}


# ── 载入生产版 ──────────────────────────────────────────
def _load_prod():
    """把 xiaozhi_mcp_server.py 当模块载入，取 TOOLS 与 HANDLERS。"""
    if not PROD_PATH.exists():
        raise FileNotFoundError(f"找不到生产版服务端: {PROD_PATH}")
    spec = importlib.util.spec_from_file_location("xz_prod_server", PROD_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法载入 {PROD_PATH}")
    mod = importlib.util.module_from_spec(spec)
    # 避免它自己的 __main__ 副作用
    sys.modules["xz_prod_server"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 载入 kit 版 ─────────────────────────────────────────
def _load_kit():
    """载入 LAAP-Agent-Kit 的 13 个工具与处理器。"""
    if str(KIT_ROOT) not in sys.path:
        sys.path.insert(0, str(KIT_ROOT))
    from laaper.hub.xiaozhi_voice_link import COMPUTER_TOOLS, XiaozhiVoiceLink
    from laaper.hub.computer_use import ComputerUse
    from laaper.hub.voice_computer import VoiceComputerAgent
    from laaper.hub.action_journal import ActionJournal

    cu = ComputerUse(safe_mode=True)
    voice_agent = VoiceComputerAgent(cu=cu)
    journal = ActionJournal(cu=cu, persist_path=str(
        Path.home() / ".laap" / "agent-kit" / "action_journal.json"))
    try:
        from laaper.hub.multi_step import MultiStepComputerAgent
        multistep = MultiStepComputerAgent(cu=cu, locator=voice_agent.locator)
        multistep.set_journal(journal)
    except Exception:
        multistep = None

    link = XiaozhiVoiceLink(voice_agent=voice_agent,
                            multistep_agent=multistep, journal=journal)
    return COMPUTER_TOOLS, link


# ── 合并主逻辑 ──────────────────────────────────────────
def build_merged_tools(strategy: CollisionStrategy = CollisionStrategy.PREFER_PROD) -> MergeResult:
    out = MergeResult()

    # 1) 生产版
    prod = _load_prod()
    prod_tools: Dict[str, Dict[str, Any]] = {}
    for t in getattr(prod, "TOOLS", []) or []:
        if isinstance(t, dict) and t.get("name"):
            prod_tools[t["name"]] = t
    prod_handlers: Dict[str, Callable] = dict(getattr(prod, "HANDLERS", {}) or {})
    out.prod_count = len(prod_tools)

    # 2) kit 版
    kit_tools, link = _load_kit()
    kit_map: Dict[str, Dict[str, Any]] = {t["name"]: t for t in kit_tools}
    # kit 的 handler 在 XiaozhiVoiceLink._handlers 里
    kit_handlers: Dict[str, Callable] = {}
    handler_map = getattr(link, "_handlers", {}) or {}
    for name in kit_map:
        if name in handler_map:
            kit_handlers[name] = handler_map[name]
    out.kit_count = len(kit_map)

    # 3) 按策略决定冲突怎么办
    used: set = set()

    def add(name: str, schema: Dict[str, Any], handler: Callable,
            origin: str, renamed_from: Optional[str] = None) -> None:
        if name in used:
            out.warnings.append(f"重名被跳过: {name}")
            return
        used.add(name)
        out.tools.append(ToolEntry(
            name=name,
            description=schema.get("description", ""),
            input_schema=schema.get("inputSchema", {"type": "object", "properties": {}}),
            handler=handler, origin=origin, renamed_from=renamed_from,
        ))

    for name, schema in prod_tools.items():
        handler = prod_handlers.get(name)
        if handler is None:
            out.warnings.append(f"生产版 {name} 无处理器，跳过")
            continue
        if name in COLLIDING:
            if strategy == CollisionStrategy.PREFER_PROD:
                add(name, schema, handler, "prod")
            elif strategy == CollisionStrategy.ALL_RENAME:
                add(f"laap_{name}", schema, handler, "prod", renamed_from=name)
            elif strategy == CollisionStrategy.PREFER_KIT:
                add(f"laap_{name}", schema, handler, "prod", renamed_from=name)
            # MERGE_SEMANTIC 稍后统一处理
            continue
        add(name, schema, handler, "prod")

    for name, schema in kit_map.items():
        handler = kit_handlers.get(name)
        if handler is None:
            out.warnings.append(f"kit 版 {name} 无处理器，跳过")
            continue
        if name in COLLIDING:
            if strategy == CollisionStrategy.PREFER_PROD:
                add(f"pc_local_{name[3:]}", schema, handler, "kit", renamed_from=name)
            elif strategy == CollisionStrategy.PREFER_KIT:
                add(name, schema, handler, "kit")
            elif strategy == CollisionStrategy.ALL_RENAME:
                add(f"kit_{name}", schema, handler, "kit", renamed_from=name)
            continue
        add(name, schema, handler, "kit")

    # MERGE_SEMANTIC：一个工具同时报两边
    if strategy == CollisionStrategy.MERGE_SEMANTIC:
        for name in COLLIDING:
            p_schema = prod_tools.get(name, {})
            k_schema = kit_map.get(name, {})
            p_h = prod_handlers.get(name)
            k_h = kit_handlers.get(name)
            if not (p_h and k_h):
                continue

            def make_combined(a=p_h, b=k_h):
                async def _combined(args: Dict[str, Any]) -> str:
                    """同时跑两边。两边都可能是 async（kit 的 handler 全是协程），
                    必须 await；用同步包装接协程会得到 'never awaited' 且半边为空。"""
                    parts = []
                    for label, fn in (("LAAP", a), ("本机", b)):
                        try:
                            r = fn(args or {})
                            if asyncio.iscoroutine(r):
                                r = await r
                            if not isinstance(r, str):
                                r = json.dumps(r, ensure_ascii=False)
                            parts.append(f"[{label}] {r}")
                        except Exception as e:
                            parts.append(f"[{label}] 失败: {type(e).__name__}: {e}")
                    return "\n".join(parts)
                return _combined

            add(name, p_schema or k_schema, make_combined(), "merged")

    return out
