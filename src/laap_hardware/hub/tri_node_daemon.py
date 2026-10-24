"""三端守护节点 — 电脑端中枢，接入云端中继、局域网、小智、手机

## 角色

电脑 = 中枢（hub）。手机、小智硬件、其他电脑都是 node。

    ┌─────────────────────────────────────────────┐
    │  TriNodeDaemon (电脑)                        │
    │  · TriNodeHub（注册表/会话/任务编排）          │
    │  · ComputerUse + MultiStep（手）             │
    │  · ActionJournal（撤销）                     │
    │  · TransportManager（网络）                  │
    │     ├─ LAN server  ws://<ip>:8765            │
    │     └─ Cloud client wss://api.laap.cn/ws     │
    └───────┬──────────────┬──────────────┬────────┘
            ↓              ↓              ↓
      {phone-01}      {xiaozhi-01}    {pc-02}

## 三端相互的三种消息

1. 注册 register  —— 上报 node_id + role + capabilities（sensors/actuators）
2. 感知 perceive —— 上报传感器/状态（GPS/电量/窗口/温度）
3. 操纵 task     —— 派活给任意节点（task_assign → task_result）

中继负责路由，中枢维护注册表，任何节点都能互相操纵。

## 用法

    from laaper.hub.tri_node_daemon import TriNodeDaemon, DaemonConfig

    d = TriNodeDaemon(DaemonConfig(
        cloud_url="wss://api.laap.cn/ws",
        cloud_token="<jwt>",
    ))
    await d.start()          # LAN + Cloud 全起来
    await d.broadcast("大家好")
    await d.assign("phone-01", "open_app", {"package": "com.tencent.mm"})
    await d.stop()
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laaper.hub.daemon")

from laaper.hub.node import (
    NodeKind, NodeInfo, NodeCapabilities,
    SensorKind, ActuatorKind, make_pc_node,
)
from laaper.hub.session import MessageRole, SessionMessage
from laaper.hub.hub import TriNodeHub, TaskState
from laaper.hub.transport import (
    TransportMode, MessageKind, MessageEnvelope, TransportConfig,
    IdempotencyCache, NodeConnection, TransportManager,
)


@dataclass
class DaemonConfig:
    """守护节点配置"""
    laaper_id: str = "aris"
    node_id: str = "pc-hub"
    node_name: str = "LAAP 电脑"

    # 云端中继
    cloud_url: str = ""
    cloud_token: str = ""
    connect_cloud: bool = True

    # 局域网
    lan_port: int = 8765
    start_lan: bool = True
    shared_key: str = ""

    # 功能开关
    enable_computer: bool = True
    enable_multistep: bool = True
    enable_journal: bool = True
    enable_browser: bool = True
    browser_headless: bool = True

    # 自动注册的能力
    auto_register: bool = True

    # 指令超时
    task_timeout: float = 120.0


@dataclass
class PeerInfo:
    """已注册的远端节点"""
    node_id: str = ""
    role: str = ""
    capabilities: Dict[str, Any] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    online: bool = False

    def touch(self):
        self.last_seen = time.time()
        self.online = True

    @property
    def stale(self) -> bool:
        return (time.time() - self.last_seen) > 45

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "capabilities": self.capabilities,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "online": self.online and not self.stale,
        }


class TriNodeDaemon:
    """三端守护节点（电脑中枢）

    组装：TriNodeHub + ComputerUse + MultiStep + Journal + Transport。
    """

    def __init__(self, config: Optional[DaemonConfig] = None):
        self.config = config or DaemonConfig()
        self.laaper_id = self.config.laaper_id
        self.node_id = self.config.node_id

        # ── 中枢 ——
        self.hub = TriNodeHub(laaper_id=self.laaper_id)
        self.hub.register_pc(self.config.node_id)

        # ── 电脑能力 ——
        self.cu = None
        self.voice_agent = None
        self.multistep = None
        self.journal = None
        self.link = None
        self.browser_agent = None

        # ── 传输 ——
        self.transport = TransportManager(
            self.hub,
            TransportConfig(
                mode=TransportMode.AUTO,
                lan_port=self.config.lan_port,
                cloud_url=self.config.cloud_url,
                cloud_token=self.config.cloud_token,
                shared_key=self.config.shared_key,
                require_auth=bool(self.config.shared_key),
            ),
        )

        # ── 云端连接 ——
        self._cloud_conn: Optional[NodeConnection] = None
        self._lan_server: Dict = {}

        # ── 远端节点注册表 ——
        self.peers: Dict[str, PeerInfo] = {}

        # ── 回调 ——
        self._on_peer_event: Optional[Callable] = None
        self._on_assign: Optional[Callable] = None

        # 统计
        self.stats = {
            "started_at": 0.0,
            "assignments": 0,
            "assign_ok": 0,
            "assign_fail": 0,
            "percepts": 0,
            "bytes_relayed": 0,
        }

    # ─────────────────────── 启动 ───────────────────────

    async def start(self) -> Dict:
        """启动守护节点"""
        self.stats["started_at"] = time.time()

        # 1. 电脑能力
        if self.config.enable_computer:
            self._setup_computer()

        # 2. 局域网服务
        if self.config.start_lan:
            self._lan_server = await self.transport.start_server()
            logger.info(f"局域网: {self._lan_server.get('url')}")

        # 3. 云端中继
        if self.config.connect_cloud and self.config.cloud_url:
            await self._connect_cloud()

        # 4. 注册自己
        if self.config.auto_register:
            await self._register_self()

        self.hub.create_session()
        logger.info(
            f"三端守护节点就绪 node={self.node_id} "
            f"lan={'on' if self._lan_server.get('success') else 'off'} "
            f"cloud={'on' if self._cloud_conn and self._cloud_conn.connected else 'off'}"
        )

        return {
            "success": True,
            "node_id": self.node_id,
            "lan": self._lan_server.get("url", ""),
            "cloud": self.config.cloud_url,
            "cloud_connected": bool(self._cloud_conn and self._cloud_conn.connected),
            "peers": self.list_peers(),
        }

    def _setup_computer(self):
        """装配电脑能力"""
        from laaper.hub.computer_use import ComputerUse
        from laaper.hub.voice_computer import (
            VoiceComputerAgent, register_computer_use_handlers,
        )
        from laaper.hub.action_journal import ActionJournal, register_journal_handlers

        self.cu = ComputerUse(safe_mode=True)
        self.voice_agent = VoiceComputerAgent(cu=self.cu)
        self.journal = ActionJournal(cu=self.cu)
        self.voice_agent.journal = self.journal

        if self.config.enable_multistep:
            try:
                from laaper.hub.multi_step import (
                    MultiStepComputerAgent, register_multistep_handlers,
                )
                self.multistep = MultiStepComputerAgent(
                    cu=self.cu, locator=self.voice_agent.locator,
                )
                self.multistep.set_journal(self.journal)
            except Exception as e:
                logger.warning(f"多步任务不可用: {e}")

        # 挂到中枢（电脑节点的处理器表）
        register_computer_use_handlers(
            self.hub, self.config.node_id, self.voice_agent,
        )
        register_journal_handlers(
            self.hub, self.config.node_id, self.journal, self.cu,
        )
        if self.multistep:
            register_multistep_handlers(
                self.hub, self.config.node_id, self.multistep,
            )

        # 浏览器（网页感知/点击）——小智语音能"看网页、点网页"的关键
        if self.config.enable_browser:
            try:
                from laaper.hub.browser_agent import (
                    BrowserVoiceAgent, register_browser_handlers,
                )
                self.browser_agent = BrowserVoiceAgent(
                    headless=self.config.browser_headless,
                )
                register_browser_handlers(
                    self.hub, self.config.node_id, self.browser_agent,
                )
                logger.info(f"浏览器代理已启用 (headless={self.config.browser_headless})")
            except Exception as e:
                logger.warning(f"浏览器代理不可用: {e}")

    async def _connect_cloud(self) -> bool:
        """连云端中继，处理远端消息

        注意：relay worker 从 URL query 参数读 token/node_id/role，
        不放 header。
        """
        # 拼接认证信息到 URL
        from urllib.parse import urlencode
        params = urlencode({
            "token": self.config.cloud_token or "",
            "node_id": self.node_id,
            "role": "hub",
        })
        sep = "&" if "?" in self.config.cloud_url else "?"
        url = f"{self.config.cloud_url}{sep}{params}"

        conn = NodeConnection(
            node_id=self.node_id,
            url=url,
            config=TransportConfig(
                mode=TransportMode.CLOUD,
                cloud_token=self.config.cloud_token,
                cloud_url=self.config.cloud_url,
            ),
            mode=TransportMode.CLOUD,
            idempotency=IdempotencyCache(),
        )
        conn.on_message = self._handle_cloud_message
        conn.on_connect = self._on_cloud_connect
        conn.on_disconnect = self._on_cloud_disconnect

        # 等待连接成功或超时（relay 冷启动 / DNS 可能稍慢）
        ok = await conn.connect()
        if not ok:
            for attempt in range(4):
                await asyncio.sleep(1.0)
                if conn.connected:
                    ok = True
                    break
                ok = await conn.connect()
                if ok:
                    break

        await conn.start_supervisor()
        self._cloud_conn = conn
        return ok

    async def _on_cloud_connect(self):
        logger.info(f"[cloud] 已连接 {self.config.cloud_url}")
        # 重连后重新注册 + 广播上线
        await self._register_self()
        self.hub.heartbeat(self.node_id)

    async def _on_cloud_disconnect(self):
        logger.warning("[cloud] 连接断开")
        for pid in self.peers:
            self.peers[pid].online = False

    # ─────────────────────── 注册 ───────────────────────

    async def _register_self(self):
        """把电脑自己的能力广播给所有节点看"""
        caps = {
            "sensors": ["screen", "keyboard", "mouse", "microphone", "speaker"],
            "actuators": ["click", "type", "shell", "file", "browse",
                          "speak", "display", "scroll", "hotkey"],
            "resources": {"compute": 1.0, "always_on": True},
        }

        msg = MessageEnvelope(
            kind="register",
            from_node=self.node_id,
            to_node="*",
            payload={
                "node_id": self.node_id,
                "name": self.config.node_name,
                "role": "hub",
                "capabilities": caps,
                "ts": time.time(),
            },
        )

        if self._cloud_conn:
            await self._cloud_conn.send(msg)
        # 局域网客户端也会收到（server handler 不转发广播，这里只发云端）

    async def _handle_cloud_message(self, msg: MessageEnvelope):
        """处理云端来的所有消息"""
        kind = msg.kind
        self.stats["bytes_relayed"] += len(msg.to_json())

        if kind == "node_state":
            await self._handle_node_state(msg)
        elif kind == "register":
            await self._handle_register(msg)
        elif kind == "perception":
            await self._handle_perception(msg)
        elif kind == "task_assign":
            await self._handle_assignment(msg)
        elif kind == "task_result":
            await self._handle_task_result(msg)
        elif kind == "push":
            await self._handle_push(msg)
        else:
            logger.debug(f"[cloud] 未知消息 {kind} from {msg.from_node}")

    async def _handle_node_state(self, msg: MessageEnvelope):
        """节点上线/下线事件"""
        payload = msg.payload or {}
        node_id = payload.get("node_id", msg.from_node)
        event = payload.get("event", "online")

        peer = self.peers.setdefault(
            node_id, PeerInfo(node_id=node_id, role=payload.get("role", "node"))
        )
        if event == "online":
            peer.touch()
            self.hub.heartbeat(node_id)
            logger.info(f"[peer] {node_id} 上线")
            # 节点上线 → 回应欢迎 + 我们的注册信息
            if self._cloud_conn:
                await self._register_self()
        else:
            peer.online = False
            self.hub.go_offline(node_id)
            logger.info(f"[peer] {node_id} 离线")

        if self._on_peer_event:
            try:
                await self._on_peer_event(peer, event)
            except Exception:
                pass

    async def _handle_register(self, msg: MessageEnvelope):
        """节点注册（带能力声明）"""
        payload = msg.payload or {}
        node_id = payload.get("node_id", msg.from_node)
        role = payload.get("role", "node")

        peer = self.peers.setdefault(node_id, PeerInfo(node_id=node_id, role=role))
        peer.role = role
        peer.capabilities = payload.get("capabilities", {})
        peer.touch()
        self.hub.heartbeat(node_id)

        logger.info(
            f"[peer] 注册 {node_id} role={role} "
            f"caps={json.dumps(peer.capabilities, ensure_ascii=False)[:120]}"
        )

        if self._on_peer_event:
            try:
                await self._on_peer_event(peer, "registered")
            except Exception:
                pass

    async def _handle_perception(self, msg: MessageEnvelope):
        """节点感知上报"""
        self.stats["percepts"] += 1
        payload = msg.payload or {}
        node_id = msg.from_node

        peer = self.peers.setdefault(node_id, PeerInfo(node_id=node_id))
        peer.touch()
        self.hub.heartbeat(node_id)

        # 入会话
        session = self.hub.get_active_session()
        if session:
            sensor = payload.get("sensor", "state")
            data = payload.get("data", {})
            session.add_message(SessionMessage(
                role=MessageRole.NODE_EVENT,
                origin_node=node_id,
                text=f"{node_id} 感知[{sensor}]: {json.dumps(data, ensure_ascii=False)[:80]}",
            ))

    async def _handle_assignment(self, msg: MessageEnvelope):
        """远端节点派活给电脑"""
        self.stats["assignments"] += 1
        payload = msg.payload or {}
        action = payload.get("action", "")
        params = payload.get("params", {})
        request_id = payload.get("request_id", msg.message_id)
        from_node = msg.from_node

        logger.info(f"[assign] {from_node} → {action} {params}")

        try:
            result = await asyncio.wait_for(
                self._execute_action(action, params),
                timeout=self.config.task_timeout,
            )
            ok = result.get("success", True)
            self.stats["assign_ok" if ok else "assign_fail"] += 1

            reply = MessageEnvelope(
                kind="task_result",
                from_node=self.node_id,
                to_node=from_node,
                payload={
                    "request_id": request_id,
                    "action": action,
                    "success": ok,
                    "result": result,
                    "ts": time.time(),
                },
            )
            if self._cloud_conn:
                await self._cloud_conn.send(reply)

        except asyncio.TimeoutError:
            self.stats["assign_fail"] += 1
            reply = MessageEnvelope(
                kind="task_result",
                from_node=self.node_id,
                to_node=from_node,
                payload={
                    "request_id": request_id,
                    "success": False,
                    "result": {"error": "执行超时"},
                },
            )
            if self._cloud_conn:
                await self._cloud_conn.send(reply)

        if self._on_assign:
            try:
                await self._on_assign(action, params, from_node)
            except Exception:
                pass

    async def _execute_action(self, action: str, params: Dict) -> Dict:
        """执行电脑端动作

        语音指令分流：
          · 网页意图（打开/看网页/点网页上的X/搜索）→ BrowserVoiceAgent（DOM 精确）
          · 其余桌面意图 → VoiceComputerAgent（pyautogui/UIA）
        """
        # 语音指令（自然语言）优先走 voice_command
        if action in ("voice_command", "voice"):
            text = params.get("text", "")

            # 网页意图判断：交给浏览器层。
            # 浏览器已有页面时，交互类指令（点击/滚动/输入/回车）也优先走浏览器，
            # 因为网页里的元素 UIA 拿不到，只能用 DOM。
            use_browser = self.browser_agent and (
                self._is_web_intent(text)
                or (self.browser_agent.ready and self._is_browser_interaction(text))
            )
            if use_browser:
                result = await self.browser_agent.handle(text)
                return {
                    "success": result.success,
                    "reply": result.reply,
                    "intent": result.intent or {},
                    "action": (result.action_detail or {}).get("url", "")
                        if result.action_detail and "url" in result.action_detail
                        else (result.intent or {}).get("action", ""),
                    "route": "browser",
                }

            if self.voice_agent:
                result = await self.voice_agent.handle(text)
                return {
                    "success": result.success,
                    "reply": result.reply,
                    "intent": (result.intent or {}),
                    "action": (result.action_result or {}).get("action", ""),
                    "route": "desktop",
                }
            return {"success": False, "error": "语音能力未启用"}

        # 明确的浏览器动作
        if action in ("browser_command", "browser", "browser_see",
                      "browser_open", "browser_click"):
            if self.browser_agent:
                return await self.hub.transport.execute(
                    self.node_id, action, params
                )
            return {"success": False, "error": "浏览器能力未启用"}

        # 多步任务
        if action in ("computer_task", "task", "do"):
            task_text = params.get("instruction") or params.get("text") or ""
            if self.multistep:
                run = await self.multistep.run(task_text)
                return {
                    "success": run.success,
                    "message": run.message,
                    "steps": len(run.steps),
                }
            return {"success": False, "error": "多步任务未启用"}

        # 具体动作 → 走电脑处理器
        return await self.hub.transport.execute(self.node_id, action, params)

    @staticmethod
    def _is_web_intent(text: str) -> bool:
        """判断语音指令是否是网页意图（该走浏览器层）"""
        t = text
        tl = t.lower()

        # 明确网址
        if "http://" in tl or "https://" in tl or "www." in tl:
            return True

        # 网页/网站/浏览器/搜索 关键词
        if any(k in t for k in (
            "网页", "网站", "页面", "浏览器", "打开网", "看看有",
            "搜索", "查一下", "找一下",
        )):
            return True

        # 常见站点名 + 打开/上（bilibili/知乎/百度...）
        known_sites = ("bilibili", "哔哩", "知乎", "百度", "淘宝", "京东",
                       "抖音", "微博", "github", "小红书", "新浪", "网易")
        if any(k in t for k in known_sites) and any(
            k in t for k in ("打开", "访问", "去", "上", "搜")
        ):
            return True

        # 明确是网页上的动作
        if any(k in t for k in ("点网页", "网页上", "页面上", "网页里的")):
            return True

        return False

    @staticmethod
    def _is_browser_interaction(text: str) -> bool:
        """交互类指令（浏览器有页面时优先走浏览器）：
        点/滚/输/回车/搜、以及"点xx按钮"这类网页动作。"""
        from laaper.hub.computer_use import VoiceIntentParser

        # 规则层能拆出的交互动作
        intent = VoiceIntentParser.parse(text)
        if intent and intent.action in (
            "click_text", "click", "scroll", "scroll_until",
            "type", "press", "hotkey",
        ):
            return True

        # 兜底关键词
        return any(k in text for k in (
            "点一下", "点击", "点开", "双击", "滚", "翻", "输入", "回车",
            "搜索", "搜一下", "按下",
        ))

    async def _handle_task_result(self, msg: MessageEnvelope):
        """远端节点执行完的返回"""
        payload = msg.payload or {}
        node_id = msg.from_node
        request_id = payload.get("request_id", "")
        success = payload.get("success", False)

        peer = self.peers.setdefault(node_id, PeerInfo(node_id=node_id))
        peer.touch()
        self.hub.heartbeat(node_id)

        logger.info(
            f"[result] {node_id} req={request_id} "
            f"ok={success} -> {json.dumps(payload.get('result', {}), ensure_ascii=False)[:80]}"
        )

    async def _handle_push(self, msg: MessageEnvelope):
        """远端推来的内容（截图/文字）"""
        payload = msg.payload or {}
        text = payload.get("text", "")
        logger.info(f"[push] from {msg.from_node}: {text[:60]}")

        session = self.hub.get_active_session()
        if session and text:
            session.add_message(SessionMessage(
                role=MessageRole.SYSTEM,
                origin_node=msg.from_node,
                text=f"[推送] {text}",
            ))

    # ─────────────────────── 对外操作 ───────────────────────

    async def assign(
        self,
        target: str,
        action: str,
        params: Dict,
        timeout: float = 60.0,
    ) -> Dict:
        """派活给任意节点（互操纵）"""
        if not self._cloud_conn or not self._cloud_conn.connected:
            return {"success": False, "error": "云端未连接"}

        request_id = f"req_{int(time.time() * 1000)}"

        msg = MessageEnvelope(
            kind="task_assign",
            from_node=self.node_id,
            to_node=target,
            payload={
                "request_id": request_id,
                "action": action,
                "params": params,
            },
        )
        msg.requires_ack = False

        # 等待远端 result
        future = asyncio.get_event_loop().create_future()
        wrapper = self._make_result_waiter(request_id, future)
        old_handler = self._cloud_conn.on_message
        self._cloud_conn.on_message = wrapper

        try:
            ok = await self._cloud_conn.send(msg)
            if not ok:
                return {"success": False, "error": "发送失败"}
            try:
                result_payload = await asyncio.wait_for(future, timeout=timeout)
                return {
                    "success": result_payload.get("success", False),
                    "result": result_payload.get("result", {}),
                    "node": target,
                }
            except asyncio.TimeoutError:
                return {"success": False, "error": "对方未在时限内回应"}
        finally:
            self._cloud_conn.on_message = old_handler

    def _make_result_waiter(self, request_id: str, future: asyncio.Future):
        async def handler(msg: MessageEnvelope):
            if msg.kind == "task_result":
                payload = msg.payload or {}
                if payload.get("request_id") == request_id and not future.done():
                    future.set_result(payload)
            # 其他消息继续走原逻辑
        return handler

    async def broadcast(self, text: str, kind: str = "push"):
        """广播给所有在线节点"""
        if not self._cloud_conn or not self._cloud_conn.connected:
            return False
        msg = MessageEnvelope(
            kind=kind,
            from_node=self.node_id,
            to_node="*",
            payload={"text": text, "ts": time.time()},
        )
        return await self._cloud_conn.send(msg)

    async def push_to(self, target: str, text: str, payload: Any = None):
        """推给指定节点"""
        if not self._cloud_conn or not self._cloud_conn.connected:
            return False
        body = {"text": text}
        if payload is not None:
            body["payload"] = payload
        msg = MessageEnvelope(
            kind="push",
            from_node=self.node_id,
            to_node=target,
            payload=body,
        )
        return await self._cloud_conn.send(msg)

    # ─────────────────────── 状态 ───────────────────────

    def list_peers(self, online_only: bool = False) -> List[Dict]:
        peers = [
            p.to_dict() for p in self.peers.values()
        ]
        if online_only:
            peers = [p for p in peers if p["online"]]
        return peers

    def get_peer(self, node_id: str) -> Optional[Dict]:
        peer = self.peers.get(node_id)
        return peer.to_dict() if peer else None

    def get_status(self) -> Dict:
        return {
            "node_id": self.node_id,
            "laaper_id": self.laaper_id,
            "cloud_connected": bool(self._cloud_conn and self._cloud_conn.connected),
            "cloud_url": self.config.cloud_url,
            "lan": self._lan_server.get("url", ""),
            "peers": {
                **{p: self.get_peer(p) for p in self.peers},
            },
            "online_peers": [
                p.to_dict() for p in self.peers.values()
                if p.online and not p.stale
            ],
            "session": (
                self.hub.get_active_session().stats()
                if self.hub.get_active_session() else None
            ),
            "stats": self.stats,
        }

    # ─────────────────────── 停止 ───────────────────────

    async def stop(self):
        if self._cloud_conn:
            await self._cloud_conn.disconnect()
        await self.transport.close()
        await self.hub.close()
        logger.info("三端守护节点已停止")


# ══════════════════════════════════════════════════════════
#  CLI 启动
# ══════════════════════════════════════════════════════════

async def run_daemon(
    cloud_url: str = "",
    cloud_token: str = "",
    lan_port: int = 8765,
    node_id: str = "pc-hub",
    interactive: bool = True,
) -> TriNodeDaemon:
    """启动守护节点（可作为常驻进程）"""
    import os

    cfg = DaemonConfig(
        cloud_url=cloud_url or os.environ.get("LAAP_RELAY_URL", ""),
        cloud_token=cloud_token or os.environ.get("LAAP_RELAY_TOKEN", ""),
        lan_port=lan_port,
        node_id=node_id,
    )

    daemon = TriNodeDaemon(cfg)
    await daemon.start()

    if interactive:
        session = daemon.hub.get_active_session()
        print()
        print(f"  三端守护节点 · {node_id} · {daemon.laaper_id}")
        print(f"  局域网: {daemon.get_status()['lan'] or '(未启动)'}")
        print(f"  云端:   {cfg.cloud_url or '(未配置)'}")
        print(f"  会话:   {session.session_id if session else '-'}")
        print()

    return daemon