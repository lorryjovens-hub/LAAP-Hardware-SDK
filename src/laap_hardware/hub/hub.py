"""LAAP 三端联动总线 — 电脑 / 手机 / 小智硬件

## 一个真实场景

你在小智硬件上说：
  「帮我在电脑上打开 LAAP 官网，截个图发到我手机」

这句话要经过：

    小智硬件（耳朵听到）
        ↓ 语音转文字
    中枢（理解意图 + 拆解任务）
        ↓ 步骤1：需要浏览器能力 → 派给电脑
    电脑（打开网页）
        ↓ 步骤2：需要截图 → 电脑自己截
        ↓ 步骤3：需要把图送到手机
    手机（收到截图显示）
        ↓ 步骤4：结果回到说话的人
    小智硬件（"已经打开了，截图发到你手机了"）

这一整套，就是本模块干的事。

## 架构

    ┌────────────────────────────────────────────┐
    │  TriNodeHub                                 │
    │  ┌──────────────┬──────────────┬─────────┐ │
    │  │ NodeRegistry │ SessionStore │ Payloads│ │
    │  │  节点注册     │  统一会话     │ 数据面   │ │
    │  └──────────────┴──────────────┴─────────┘ │
    │  ┌──────────────────────────────────────┐  │
    │  │  TaskOrchestrator                     │  │
    │  │  任务拆解 → 节点路由 → 跨端接力 → 汇总  │  │
    │  └──────────────────────────────────────┘  │
    └───────┬──────────────┬──────────────┬──────┘
            ↓              ↓              ↓
        ┌───────┐     ┌───────┐     ┌────────┐
        │  PC   │     │ Phone │     │Xiaozhi │
        └───────┘     └───────┘     └────────┘
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from laaper.hub.node import (
    ActuatorKind, NodeInfo, NodeKind, RoutingDecision,
    SensorKind, TaskRequirement, route_task,
    make_pc_node, make_phone_node, make_hardware_node,
)
from laaper.hub.session import (
    MessageRole, PayloadStore, SessionMessage, UnifiedSession,
)

logger = logging.getLogger("laaper.hub")


# ══════════════════════════════════════════════════════════
#  任务
# ══════════════════════════════════════════════════════════

class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_NODE = "waiting_node"      # 等某端响应
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskStep:
    """任务步骤 — 一个步骤派给一个节点"""
    step_id: str = field(default_factory=lambda: f"st_{uuid.uuid4().hex[:6]}")
    order: int = 0
    description: str = ""

    # 需要什么
    requirement: TaskRequirement = field(default_factory=TaskRequirement)

    # 派给谁
    assigned_node: str = ""
    routing: Optional[RoutingDecision] = None

    # 执行
    action: str = ""                                   # 动作名
    params: Dict[str, Any] = field(default_factory=dict)

    # 状态
    state: str = StepState.PENDING
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "order": self.order,
            "description": self.description,
            "assigned_node": self.assigned_node,
            "action": self.action,
            "state": self.state.value if hasattr(self.state, "value") else self.state,
            "error": self.error,
            "duration_ms": round((self.finished_at - self.started_at) * 1000, 1)
            if self.started_at else 0,
        }


@dataclass
class CrossNodeTask:
    """跨节点任务"""
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    session_id: str = ""
    instruction: str = ""
    origin_node: str = ""              # 谁发起的

    steps: List[TaskStep] = field(default_factory=list)

    state: str = TaskState.PENDING
    result: str = ""
    error: str = ""

    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0

    def add_step(self, step: TaskStep) -> TaskStep:
        step.order = len(self.steps)
        self.steps.append(step)
        return step

    @property
    def progress(self) -> str:
        done = sum(1 for s in self.steps if s.state == StepState.COMPLETED)
        return f"{done}/{len(self.steps)}"

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "instruction": self.instruction,
            "origin_node": self.origin_node,
            "state": self.state.value if hasattr(self.state, "value") else self.state,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "steps": [s.to_dict() for s in self.steps],
            "duration_s": round(
                (self.finished_at or time.time()) - (self.started_at or time.time()),
                1,
            ),
        }


# ══════════════════════════════════════════════════════════
#  节点传输层抽象
# ══════════════════════════════════════════════════════════

# 节点动作处理器签名
NodeHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class NodeTransport:
    """节点传输层

    负责把任务真正送到节点。具体怎么送（WebSocket / MCP / HTTP）
    由注入的 handler 决定。
    """

    def __init__(self):
        # node_id -> {action_name: handler}
        self._handlers: Dict[str, Dict[str, NodeHandler]] = {}
        # node_id -> send 函数（发消息给节点）
        self._senders: Dict[str, Callable[[Dict], Awaitable[None]]] = {}

    def register_handler(
        self,
        node_id: str,
        action: str,
        handler: NodeHandler,
    ):
        """注册节点能执行的动作"""
        self._handlers.setdefault(node_id, {})[action] = handler

    def register_sender(
        self,
        node_id: str,
        sender: Callable[[Dict], Awaitable[None]],
    ):
        """注册给节点发消息的函数（用于推送）"""
        self._senders[node_id] = sender

    def can_handle(self, node_id: str, action: str) -> bool:
        return action in self._handlers.get(node_id, {})

    async def execute(
        self,
        node_id: str,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """在节点上执行动作"""
        handler = self._handlers.get(node_id, {}).get(action)

        if not handler:
            # 退化：尝试用 sender 发消息
            sender = self._senders.get(node_id)
            if sender:
                await sender({"action": action, "params": params})
                return {"success": True, "sent": True}
            return {
                "success": False,
                "error": f"节点 {node_id} 不支持动作 {action}",
            }

        try:
            result = await handler(params)
            return result if isinstance(result, dict) else {"success": True, "data": result}
        except Exception as e:
            logger.exception(f"节点 {node_id} 执行 {action} 失败")
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    async def push(self, node_id: str, message: Dict) -> bool:
        """向节点推送消息（不需要返回）"""
        sender = self._senders.get(node_id)
        if not sender:
            return False
        try:
            await sender(message)
            return True
        except Exception as e:
            logger.error(f"推送到 {node_id} 失败: {e}")
            return False


# ══════════════════════════════════════════════════════════
#  三端联动中枢
# ══════════════════════════════════════════════════════════

class TriNodeHub:
    """三端联动中枢

    用法:
        hub = TriNodeHub(laaper_id="aris")

        # 注册三端
        hub.register_pc("pc-01")
        hub.register_phone("phone-01")
        hub.register_hardware("xiaozhi-01")

        # 心跳
        hub.heartbeat("pc-01")

        # 注册节点能力处理器
        hub.transport.register_handler("pc-01", "browse",
            lambda p: open_browser(p["url"]))
        hub.transport.register_handler("phone-01", "display",
            lambda p: show_image(p))

        # 处理一次用户输入（从任意端）
        result = await hub.handle_input(
            text="帮我打开 LAAP 官网截图发到手机",
            origin_node="xiaozhi-01",
        )
    """

    def __init__(
        self,
        laaper_id: str = "aris",
        payload_dir: Optional[str] = None,
    ):
        self.laaper_id = laaper_id

        # 节点
        self.nodes: Dict[str, NodeInfo] = {}
        self.transport = NodeTransport()

        # 会话
        self.sessions: Dict[str, UnifiedSession] = {}
        self.active_session_id: str = ""

        # 数据面
        self.payloads = PayloadStore(payload_dir)

        # 任务
        self.tasks: Dict[str, CrossNodeTask] = {}

        # 回调
        self._on_task_event: Optional[Callable] = None
        self._on_message: Optional[Callable] = None

        # 任务规划器（可注入 LLM 规划）
        self._planner: Optional[Callable] = None

    # ── 节点管理 ──────────────────────────────────

    def register_node(self, node: NodeInfo) -> NodeInfo:
        """注册节点"""
        self.nodes[node.node_id] = node
        logger.info(
            f"节点已注册: {node.node_id} ({node.kind.value}) "
            f"感知={len(node.capabilities.sensors)} "
            f"行动={len(node.capabilities.actuators)}"
        )
        return node

    def register_pc(self, node_id: str = "pc-01") -> NodeInfo:
        return self.register_node(make_pc_node(node_id))

    def register_phone(self, node_id: str = "phone-01") -> NodeInfo:
        return self.register_node(make_phone_node(node_id))

    def register_hardware(self, node_id: str = "xiaozhi-01") -> NodeInfo:
        return self.register_node(make_hardware_node(node_id))

    def unregister_node(self, node_id: str):
        self.nodes.pop(node_id, None)

    def heartbeat(self, node_id: str) -> bool:
        """节点心跳"""
        node = self.nodes.get(node_id)
        if not node:
            return False
        was_offline = not node.online
        node.heartbeat()

        if was_offline:
            logger.info(f"节点上线: {node_id}")
            asyncio.create_task(self._emit_node_event(node, "online"))

        return True

    def go_offline(self, node_id: str):
        """节点离线"""
        node = self.nodes.get(node_id)
        if node:
            node.online = False
            logger.info(f"节点离线: {node_id}")
            asyncio.create_task(self._emit_node_event(node, "offline"))

    async def _emit_node_event(self, node: NodeInfo, event: str):
        """发节点事件到会话"""
        session = self.get_active_session()
        if not session:
            return

        msg = SessionMessage(
            role=MessageRole.NODE_EVENT,
            origin_node=node.node_id,
            origin_node_kind=node.kind.value,
            text=f"{node.name} {event}",
        )
        session.add_message(msg)

        if self._on_message:
            try:
                await self._on_message(msg)
            except Exception:
                pass

    def online_nodes(self) -> List[NodeInfo]:
        return [n for n in self.nodes.values() if n.online and not n.stale]

    # ── 会话管理 ──────────────────────────────────

    def create_session(self, session_id: Optional[str] = None) -> UnifiedSession:
        """创建会话"""
        session = UnifiedSession(
            laaper_id=self.laaper_id,
            **({"session_id": session_id} if session_id else {}),
        )
        self.sessions[session.session_id] = session
        self.active_session_id = session.session_id
        return session

    def get_active_session(self) -> Optional[UnifiedSession]:
        if not self.active_session_id:
            return None
        return self.sessions.get(self.active_session_id)

    def use_session(self, session_id: str) -> Optional[UnifiedSession]:
        """切换活动会话"""
        session = self.sessions.get(session_id)
        if session:
            self.active_session_id = session_id
        return session

    # ── 核心：处理用户输入 ──────────────────────────────────

    async def handle_input(
        self,
        text: str,
        origin_node: str,
        session_id: Optional[str] = None,
        emotion: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """处理来自任意端的用户输入

        这是三端联动的入口。无论话是从电脑、手机还是小智说的，
        都从这里进。

        Returns:
            {
                "success": bool,
                "reply": str,              # 要回给用户的话
                "reply_to": str,           # 回给哪个节点（通常是发起端）
                "task": dict,              # 任务详情
                "session": dict,
            }
        """
        # 会话
        session = (self.sessions.get(session_id) if session_id
                   else self.get_active_session())
        if not session:
            session = self.create_session(session_id)

        # 记录用户消息
        node = self.nodes.get(origin_node)
        user_msg = SessionMessage(
            role=MessageRole.USER,
            text=text,
            origin_node=origin_node,
            origin_node_kind=node.kind.value if node else "",
            emotion=emotion or {},
        )
        session.add_message(user_msg)

        if self._on_message:
            try:
                await self._on_message(user_msg)
            except Exception:
                pass

        # 规划任务
        task = await self._plan_task(text, origin_node, session)
        if not task:
            reply = "我没理解要做什么，能再说一次吗？"
            return {
                "success": False,
                "reply": reply,
                "reply_to": origin_node,
                "task": None,
                "session": session.stats(),
            }

        self.tasks[task.task_id] = task
        session.active_task = task.task_id

        # 执行
        await self._execute_task(task, session)

        # 生成回复
        reply = task.result or task.error or "任务已处理"

        # 记录 LAAPer 回复
        reply_msg = SessionMessage(
            role=MessageRole.LAAPER,
            text=reply,
            origin_node=origin_node,
            intent=task.instruction,
        )
        session.add_message(reply_msg)

        if self._on_message:
            try:
                await self._on_message(reply_msg)
            except Exception:
                pass

        return {
            "success": task.state == TaskState.COMPLETED,
            "reply": reply,
            "reply_to": origin_node,
            "task": task.to_dict(),
            "session": session.stats(),
        }

    # ── 任务规划 ──────────────────────────────────

    async def _plan_task(
        self,
        text: str,
        origin_node: str,
        session: UnifiedSession,
    ) -> Optional[CrossNodeTask]:
        """把一句话拆成跨节点步骤

        优先用注入的 planner（LLM 规划），否则用规则匹配。
        """
        task = CrossNodeTask(
            session_id=session.session_id,
            instruction=text,
            origin_node=origin_node,
        )

        # 自定义 planner
        if self._planner:
            try:
                plan = await self._planner(text, session.context_for_llm())
                if plan:
                    for s in plan:
                        task.add_step(TaskStep(
                            description=s.get("description", ""),
                            requirement=TaskRequirement(
                                needs_sensors=set(s.get("needs_sensors", [])),
                                needs_actuators=set(s.get("needs_actuators", [])),
                                min_compute=s.get("min_compute", 0.0),
                                payload_kb=s.get("payload_kb", 0),
                            ),
                            action=s.get("action", ""),
                            params=s.get("params", {}),
                        ))
                    return task
            except Exception:
                logger.exception("自定义 planner 失败，回退规则匹配")

        # ── 规则匹配 planner ──
        steps = self._rule_plan(text, origin_node)
        if not steps:
            return None

        for s in steps:
            task.add_step(s)

        return task

    def _rule_plan(self, text: str, origin_node: str) -> List[TaskStep]:
        """规则任务规划

        识别常见意图，拆成步骤。
        """
        t = text.lower()
        steps: List[TaskStep] = []

        # 打开网页
        if any(k in t for k in ("打开", "访问", "open")) and (
            "http" in t or "网页" in t or "网站" in t or "页面" in t
        ):
            # 提取网址
            import re
            urls = re.findall(r"https?://[^\s，,。]+", text)
            url = urls[0] if urls else ""

            step = TaskStep(
                description=f"在电脑上打开网页 {url or '(未指定)'}",
                requirement=TaskRequirement(
                    needs_actuators={ActuatorKind.BROWSE},
                    min_compute=0.5,
                ),
                action="browse",
                params={"url": url},
            )
            steps.append(step)

            # 如果需要截图
            if any(k in t for k in ("截图", "截屏", "screenshot", "拍")):
                steps.append(TaskStep(
                    description="截取页面截图",
                    requirement=TaskRequirement(
                        needs_sensors={SensorKind.SCREEN},
                        payload_kb=5000,
                    ),
                    action="screenshot",
                    params={"full_page": False},
                ))

                # 如果提到发到手机
                if any(k in t for k in ("手机", "发到", "发我", "推")):
                    steps.append(TaskStep(
                        description="把截图显示到手机",
                        requirement=TaskRequirement(
                            needs_actuators={ActuatorKind.DISPLAY},
                        ),
                        action="display",
                        params={"payload_from": "prev"},
                    ))

            return steps

        # 截图
        if any(k in t for k in ("截图", "截屏", "screenshot")):
            return [TaskStep(
                description="截屏",
                requirement=TaskRequirement(needs_sensors={SensorKind.SCREEN}),
                action="screenshot",
                params={},
            )]

        # 手机相关
        if any(k in t for k in ("手机", "拍照", "摄像头")):
            return [TaskStep(
                description="用手机摄像头拍照",
                requirement=TaskRequirement(
                    needs_sensors={SensorKind.CAMERA},
                ),
                action="camera_capture",
                params={},
            )]

        # 语音播报
        if any(k in t for k in ("说给", "告诉我", "播报", "念一下")):
            return [TaskStep(
                description="语音播报",
                requirement=TaskRequirement(
                    needs_actuators={ActuatorKind.SPEAK},
                ),
                action="speak",
                params={"text": text},
            )]

        # 文件 / 命令
        if any(k in t for k in ("执行", "命令", "shell", "运行", "跑一下")):
            import re
            # 从指令里抽出真正的命令，不要把中文描述一起丢给 shell
            cmd = self._extract_command(text)
            if cmd:
                return [TaskStep(
                    description=f"执行命令: {cmd[:60]}",
                    requirement=TaskRequirement(
                        needs_actuators={ActuatorKind.SHELL},
                        min_compute=0.5,
                    ),
                    action="shell",
                    params={"command": cmd},
                )]

        return []

    @staticmethod
    def _extract_command(text: str) -> str:
        """从中文指令里抽出真正的命令

        "执行命令 dir"          -> "dir"
        "帮我运行 ipconfig /all" -> "ipconfig /all"
        "跑一下 ls -la"         -> "ls -la"
        "执行命令：tasklist"      -> "tasklist"
        """
        import re

        # 去掉引导词
        prefixes = (
            "帮我", "请", "麻烦", "执行命令", "执行", "命令",
            "运行", "跑一下", "跑", "shell",
        )

        s = text.strip()

        # 先处理“执行命令：xxx” / “执行命令: xxx”
        m = re.search(r"(?:执行命令|命令|运行|shell)\s*[:：]\s*(.+)$", s,
                      re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate and not re.search(r"[\u4e00-\u9fff]", candidate[:1]):
                return candidate

        # 去掉开头引导词
        changed = True
        while changed:
            changed = False
            for p in prefixes:
                if s.startswith(p):
                    s = s[len(p):].strip(" ：:，,")
                    changed = True
                    break

        # 剩下如果开头是 ASCII 可打印字符，当命令用
        if s and re.match(r"^[A-Za-z0-9_./\\:~\-\"]", s):
            return s

        # 从中间抓英文字符串（如 “帮我跑一下 dir 看看” -> “dir 看看”）
        m = re.search(r"([A-Za-z][A-Za-z0-9_./\\ \-:*]{1,200})", s)
        if m:
            return m.group(1).strip()

        return ""

    # ── 任务执行（跨节点接力） ──────────────────────────────────

    async def _execute_task(
        self,
        task: CrossNodeTask,
        session: UnifiedSession,
    ):
        """执行跨节点任务"""
        task.state = TaskState.RUNNING
        task.started_at = time.time()

        prev_result: Any = None

        try:
            for step in task.steps:
                # 路由
                decision = route_task(self.online_nodes(), step.requirement)
                if not decision:
                    step.state = StepState.FAILED
                    step.error = (
                        "没有节点满足要求 "
                        f"(感知={sorted(step.requirement.needs_sensors)} "
                        f"行动={sorted(step.requirement.needs_actuators)})"
                    )
                    task.state = TaskState.FAILED
                    task.error = step.error
                    logger.warning(f"步骤失败: {step.error}")
                    break

                step.assigned_node = decision.node_id
                step.routing = decision
                session.active_node = decision.node_id

                logger.info(
                    f"[{task.task_id}] 步骤 {step.order + 1}/{len(task.steps)}: "
                    f"{step.description} → {decision.node_id} "
                    f"(得分 {decision.score:.2f})"
                )

                # 补全参数（跨步骤数据传递）
                params = dict(step.params)
                if params.get("payload_from") == "prev" and prev_result is not None:
                    params["payload"] = prev_result
                    params.pop("payload_from", None)

                # 执行
                step.state = StepState.RUNNING
                step.started_at = time.time()

                result = await self.transport.execute(
                    decision.node_id, step.action, params
                )

                step.finished_at = time.time()
                step.result = result

                if result.get("success", True):
                    step.state = StepState.COMPLETED
                    prev_result = result.get("data", result)
                else:
                    step.state = StepState.FAILED
                    step.error = result.get("error", "未知错误")

                    # 尝试备用节点
                    if decision.fallback_nodes:
                        logger.info(
                            f"尝试备用节点: {decision.fallback_nodes[0]}"
                        )
                        fb = decision.fallback_nodes[0]
                        fb_result = await self.transport.execute(
                            fb, step.action, params
                        )
                        if fb_result.get("success", True):
                            step.state = StepState.COMPLETED
                            step.assigned_node = fb
                            step.result = fb_result
                            step.error = ""          # 备用节点成功，清掉错误
                            prev_result = fb_result.get("data", fb_result)
                            logger.info(f"备用节点 {fb} 成功完成")
                        else:
                            task.state = TaskState.FAILED
                            task.error = step.error
                            break
                    else:
                        task.state = TaskState.FAILED
                        task.error = step.error
                        break

            # 汇总
            if all(s.state == StepState.COMPLETED for s in task.steps):
                task.state = TaskState.COMPLETED
                task.result = self._summarize(task)
            elif task.state != TaskState.FAILED:
                task.state = TaskState.FAILED
                task.error = task.error or "部分步骤未完成"

        except Exception as e:
            logger.exception("任务执行异常")
            task.state = TaskState.FAILED
            task.error = f"{type(e).__name__}: {e}"

        finally:
            task.finished_at = time.time()
            session.active_node = ""
            session.active_task = ""

            if self._on_task_event:
                try:
                    await self._on_task_event(task)
                except Exception:
                    pass

    def _summarize(self, task: CrossNodeTask) -> str:
        """任务完成摘要（这是要回给用户的话）"""
        parts = []

        for step in task.steps:
            if step.state != StepState.COMPLETED:
                continue

            action = step.action
            node = step.assigned_node
            data = step.result.get("data", {}) if step.result else {}

            if action == "browse":
                url = data.get("url", "") if isinstance(data, dict) else ""
                parts.append(f"已在电脑上打开 {url}")
            elif action == "screenshot":
                parts.append("截了图")
            elif action == "display":
                parts.append("发到你手机了")
            elif action == "speak":
                parts.append("已播报")
            elif action == "shell":
                parts.append("命令执行完成")
            elif action == "camera_capture":
                parts.append("用手机拍了照")
            else:
                parts.append(step.description)

        if not parts:
            return "任务完成"

        return "，".join(parts) + "。"

    # ── 主动推送（中枢 → 节点） ──────────────────────────────────

    async def push_to_node(
        self,
        node_id: str,
        text: str,
        payload: Any = None,
        payload_kind: str = "json",
        summary: str = "",
    ) -> bool:
        """把内容推送到指定节点

        典型用法：把电脑截图推到手机显示。
        """
        message: Dict[str, Any] = {
            "type": "push",
            "text": text,
            "timestamp": time.time(),
            "session_id": self.active_session_id,
        }

        # 大数据转引用
        if payload is not None:
            ref = self.payloads.put(
                payload,
                kind=payload_kind,
                origin_node="hub",
                summary=summary,
            )
            message["payload_ref"] = ref.to_dict()

            # 小载荷直接带上
            if ref.size_bytes <= 512 * 1024:
                message["payload_inline"] = (
                    payload.hex() if isinstance(payload, bytes)
                    else payload if isinstance(payload, str)
                    else str(payload)
                )

        ok = await self.transport.push(node_id, message)

        # 记录到会话
        session = self.get_active_session()
        if session and ok:
            msg = SessionMessage(
                role=MessageRole.SYSTEM,
                text=f"[推送到 {node_id}] {text}",
                origin_node="hub",
            )
            if payload is not None:
                msg.payload_refs.append(ref)
            session.add_message(msg)

        return ok

    async def broadcast(
        self,
        text: str,
        exclude: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """广播到所有在线节点"""
        exclude = exclude or []
        results = {}

        for node in self.online_nodes():
            if node.node_id in exclude:
                continue
            results[node.node_id] = await self.push_to_node(
                node.node_id, text
            )

        return results

    # ── 状态 ──────────────────────────────────

    def get_state(self) -> Dict:
        """中枢完整状态"""
        session = self.get_active_session()

        by_kind: Dict[str, List[str]] = {}
        for node in self.nodes.values():
            by_kind.setdefault(node.kind.value, []).append(node.node_id)

        return {
            "laaper_id": self.laaper_id,
            "nodes": {
                "total": len(self.nodes),
                "online": len(self.online_nodes()),
                "by_kind": by_kind,
                "detail": {
                    nid: n.to_dict() for nid, n in self.nodes.items()
                },
            },
            "session": session.stats() if session else None,
            "sessions_total": len(self.sessions),
            "tasks": {
                "total": len(self.tasks),
                "running": sum(1 for t in self.tasks.values()
                               if t.state == TaskState.RUNNING),
                "completed": sum(1 for t in self.tasks.values()
                                 if t.state == TaskState.COMPLETED),
            },
            "payloads": self.payloads.stats(),
        }

    # ── 回调注册 ──────────────────────────────────

    def on_message(self, callback: Callable):
        """注册消息回调（async）"""
        self._on_message = callback

    def on_task_event(self, callback: Callable):
        """注册任务事件回调（async）"""
        self._on_task_event = callback

    def set_planner(self, planner: Callable):
        """注入 LLM 任务规划器

        planner(text, context) -> List[Dict]:
            [{
                "description": "打开网页",
                "needs_sensors": [],
                "needs_actuators": ["browse"],
                "action": "browse",
                "params": {"url": "..."},
            }]
        """
        self._planner = planner

    # ── 清理 ──────────────────────────────────

    async def close(self):
        """关闭中枢，释放资源（浏览器、连接）"""
        # 关闭共享浏览器（含 playwright 本身）
        try:
            import laaper.hub.voice_bridge as vb

            browser = getattr(vb, "_pc_browser", None)
            pw = getattr(vb, "_pc_pw", None)

            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
                vb._pc_browser = None
                vb._pc_page = None

            if pw is not None:
                try:
                    await pw.stop()
                except Exception:
                    pass
                vb._pc_pw = None

            if browser is not None or pw is not None:
                logger.info("共享浏览器已关闭")
                # 给子进程一点时间退出，避免 transport warning
                await asyncio.sleep(0.2)

        except Exception as e:
            logger.debug(f"关闭浏览器失败: {e}")

        # 注销所有节点
        for node_id in list(self.nodes.keys()):
            self.go_offline(node_id)

        logger.info("三端中枢已关闭")