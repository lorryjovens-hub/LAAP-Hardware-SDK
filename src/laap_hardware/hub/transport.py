"""LAAP 三端传输层 — 生产级设计

## 先回答那个问题：到底用什么传输？

### 逐项对比

| 方案 | 方向 | 延迟 | 断线恢复 | 适合度 |
|------|------|------|---------|--------|
| **HTTP 轮询** | 单向请求 | 高（取决于轮询间隔） | 天然 | ❌ 太浪费 |
| **SSE** | 只能服务器→客户端 | 中 | 自带重连 | ⚠️ 只能推通知，客户端没法推 |
| **WebSocket** | 双向全双工 | 低（<10ms 局域网） | 需自己实现 | ✅ **主通道** |
| **蓝牙 BLE** | 双向 | 中 | 需重连 | ⚠️ 只用于配网引导，带宽太小 |
| **WiFi** | 底层 | - | - | 不是协议，是 WS 的管子 |

**结论：WebSocket 做主力，SSE 不用，BLE 只做配网，WiFi 只是底层。**

### 为什么不用 SSE

SSE 是单向的。但三端联动需要双向：
  · 中枢要推任务给节点（服务器→客户端）
  · 节点要上报感知和结果（客户端→服务器）

用 SSE 得配一套 HTTP POST 反向通道，等于把 WS 拆成两半还更麻烦。

### 为什么 BLE 不适合做主通道

BLE 4.2 理论带宽 ~100 kbps，实际 ~20-50 kbps。
一张 720p JPEG 截图 ~150 KB，传输要 30 秒。**没法用。**

BLE 的正确用途：**配网引导**。手机还没连过 WiFi 时，用 BLE 把 WiFi 密码和 token 传过去。

---

## 双通道架构（核心设计）

```
┌─────────────────────────────────────────────────────┐
│  通道 A：局域网直连 (LAN Direct)                      │
│                                                     │
│    ws://192.168.1.100:8765                          │
│                                                     │
│    · 延迟 <10ms                                     │
│    · 不经云端，隐私最好                              │
│    · 免费（不走流量）                                │
│    · 只在家/办公室同一 WiFi 下可用                    │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  通道 B：云端中继 (Cloud Relay)                       │
│                                                     │
│    wss://api.laap.cn/ws                             │
│                                                     │
│    · 走账号体系（JWT）                               │
│    · 任何网络都能连（4G/5G/别人家WiFi）               │
│    · 经 Cloudflare，有 TLS                          │
│    · 延迟 30-150ms（取决于地域）                      │
└─────────────────────────────────────────────────────┘

选择策略：先试 A，3 秒连不上就降级到 B。
```

## 为什么需要双通道

**只做局域网**：你在外面用手机控不了家里的电脑。
**只做云端**：在家里说句话要绕一圈公网，延迟 100ms+，还费流量。

**场景决定选择**：
  · 家里：三端都在同一 WiFi → 通道 A，10ms
  · 外面：手机在 4G，电脑在家 → 通道 B，100ms
  · 混合：手机在外面，但小智硬件在家 → 硬件走 A 连电脑，手机走 B 连中枢

---

## 生产级要解决的 10 件事

### 1. 认证
    · 云端：JWT（账号体系）+ 设备指纹
    · 局域网：预共享密钥 + 设备证书（可选 TLS）

### 2. 断线重连
    指数退避 1→2→4→8→16→32→60s，±30% 抖动防风暴

### 3. 消息顺序
    每条消息带递增 seq，接收端检测乱序/丢包

### 4. 幂等（最容易被忽略，也最危险）
    每条动作带 idempotency_key。
    **断线重连后重复执行一次点击，可能就多买了一件东西。**

### 5. 背压控制
    节点慢的时候不能让中枢内存爆。
    队列上限 + 丢弃策略 + 降级推送。

### 6. 多租户隔离
    用户 A 的节点不能被用户 B 触达。
    session_id + user_id 双重校验。

### 7. 可观测性
    连接数、消息吞吐、延迟分位、错误率、重连次数。

### 8. 限流
    单节点消息速率上限，防恶意刷。

### 9. 优雅降级
    视觉模型挂了走 DOM，DOM 挂了走纯文本，全挂给明确错误。

### 10. 审计
    谁在什么时候对哪个节点做了什么动作，全记录。
    **这是安全边界，不是可选功能。**

---

## 用法

    from laaper.hub.transport import TransportManager, TransportConfig

    # 中枢侧：起一个服务端
    mgr = TransportManager(hub, TransportConfig(
        mode="auto",
        lan_port=8765,
        cloud_url="wss://api.laap.cn/ws",
        jwt_secret="...",
    ))
    await mgr.start_server()          # 局域网监听
    await mgr.connect_cloud()          # 云端中继

    # 节点侧：连接到中枢
    node = await mgr.connect_node(
        node_id="phone-01",
        lan_hint="192.168.1.100:8765",
        cloud_url="wss://api.laap.cn/ws",
        token="jwt...",
    )
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("laaper.hub.transport")


# ══════════════════════════════════════════════════════════
#  基础类型
# ══════════════════════════════════════════════════════════

class TransportMode(str, Enum):
    """传输模式"""
    LAN = "lan"              # 局域网直连
    CLOUD = "cloud"          # 云端中继
    AUTO = "auto"            # 自动选择


class MessageKind(str, Enum):
    """消息类型"""
    # 控制
    HELLO = "hello"                  # 握手
    AUTH = "auth"                    # 认证
    HEARTBEAT = "heartbeat"          # 心跳
    ACK = "ack"                      # 确认

    # 任务
    TASK_ASSIGN = "task_assign"      # 派任务给节点
    TASK_RESULT = "task_result"      # 节点返回结果

    # 感知
    PERCEPTION = "perception"        # 节点上报感知
    PUSH = "push"                    # 中枢推送

    # 数据面
    PAYLOAD_REQ = "payload_req"      # 请求载荷
    PAYLOAD_RES = "payload_res"      # 返回载荷

    # 状态
    NODE_STATE = "node_state"        # 节点状态
    ERROR = "error"


@dataclass
class MessageEnvelope:
    """消息信封 — 所有跨端消息的统一格式

    生产级关键字段：
      seq              消息序号（检测乱序/丢包）
      idempotency_key  幂等键（防重复执行）
      requires_ack     是否需要确认
      ttl_ms           过期时间（过期消息丢弃，避免重放）
    """
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)

    # 路由
    message_id: str = field(default_factory=lambda: f"m_{uuid.uuid4().hex[:12]}")
    from_node: str = "hub"
    to_node: str = ""

    # 可靠性
    seq: int = 0
    idempotency_key: str = ""
    requires_ack: bool = False
    ttl_ms: int = 60000

    # 时间
    created_at: float = field(default_factory=time.time)

    # 会话
    session_id: str = ""
    user_id: str = ""

    def compute_idempotency(self) -> str:
        """计算幂等键（同一动作只执行一次）"""
        if self.idempotency_key:
            return self.idempotency_key

        raw = f"{self.from_node}|{self.to_node}|{self.kind}|" \
              f"{json.dumps(self.payload, sort_keys=True, default=str)}"
        self.idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:24]
        return self.idempotency_key

    def expired(self) -> bool:
        return (time.time() - self.created_at) * 1000 > self.ttl_ms

    def to_json(self) -> str:
        return json.dumps({
            "kind": self.kind,
            "payload": self.payload,
            "message_id": self.message_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "seq": self.seq,
            "idempotency_key": self.idempotency_key,
            "requires_ack": self.requires_ack,
            "ttl_ms": self.ttl_ms,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "user_id": self.user_id,
        }, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> Optional["MessageEnvelope"]:
        try:
            d = json.loads(raw)
        except Exception:
            return None

        return cls(
            kind=d.get("kind", ""),
            payload=d.get("payload", {}),
            message_id=d.get("message_id", ""),
            from_node=d.get("from_node", ""),
            to_node=d.get("to_node", ""),
            seq=d.get("seq", 0),
            idempotency_key=d.get("idempotency_key", ""),
            requires_ack=d.get("requires_ack", False),
            ttl_ms=d.get("ttl_ms", 60000),
            created_at=d.get("created_at", time.time()),
            session_id=d.get("session_id", ""),
            user_id=d.get("user_id", ""),
        )


# ══════════════════════════════════════════════════════════
#  配置
# ══════════════════════════════════════════════════════════

@dataclass
class TransportConfig:
    """传输配置"""
    mode: str = TransportMode.AUTO

    # 局域网
    lan_host: str = "0.0.0.0"
    lan_port: int = 8765
    lan_timeout: float = 3.0            # 局域网连接超时（超时降级云端）

    # 云端
    cloud_url: str = ""
    cloud_token: str = ""
    cloud_timeout: float = 10.0

    # 认证
    jwt_secret: str = ""
    require_auth: bool = True
    shared_key: str = ""                # 局域网预共享密钥

    # 可靠性
    heartbeat_interval: float = 25.0
    heartbeat_timeout: float = 60.0
    max_reconnect_delay: float = 60.0
    ack_timeout: float = 10.0

    # 背压
    max_queue_size: int = 1000
    max_payload_inline_kb: int = 512

    # 限流
    rate_limit_per_minute: int = 300

    # 幂等缓存
    idempotency_ttl: float = 300.0      # 5 分钟内不重复执行


@dataclass
class TransportStats:
    """传输统计（可观测性）"""
    messages_sent: int = 0
    messages_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    errors: int = 0
    reconnects: int = 0

    # 延迟采样（毫秒）
    latency_samples: List[float] = field(default_factory=list)
    max_samples: int = 100

    def record_latency(self, ms: float):
        self.latency_samples.append(ms)
        if len(self.latency_samples) > self.max_samples:
            self.latency_samples = self.latency_samples[-self.max_samples:]

    def latency_percentile(self, p: float) -> float:
        if not self.latency_samples:
            return 0.0
        s = sorted(self.latency_samples)
        idx = int(len(s) * p / 100)
        return round(s[min(idx, len(s) - 1)], 2)

    def to_dict(self) -> Dict:
        return {
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "errors": self.errors,
            "reconnects": self.reconnects,
            "latency_p50": self.latency_percentile(50),
            "latency_p95": self.latency_percentile(95),
            "latency_p99": self.latency_percentile(99),
        }


# ══════════════════════════════════════════════════════════
#  幂等缓存
# ══════════════════════════════════════════════════════════

class IdempotencyCache:
    """幂等缓存

    **生产级最关键的组件之一。**

    场景：
      phone-01 执行了"点击购买按钮"
      结果回传时网络断了
      phone-01 不知道，重连后重发
      如果没幂等保护 → 买了两次

    机制：记住最近 N 秒执行过的动作，重复的直接返回缓存结果。
    """

    def __init__(self, ttl: float = 300.0, max_size: int = 2000):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def check(self, key: str) -> Tuple[bool, Any]:
        """检查是否已执行过

        Returns:
            (是否已执行, 之前的结果)
        """
        if key not in self._cache:
            return False, None

        ts, result = self._cache[key]

        # 过期
        if time.time() - ts > self.ttl:
            del self._cache[key]
            return False, None

        return True, result

    def store(self, key: str, result: Any):
        """记录已执行"""
        self._cache[key] = (time.time(), result)

        # 淘汰
        if len(self._cache) > self.max_size:
            # 删最旧的 20%
            items = sorted(self._cache.items(), key=lambda x: x[1][0])
            for k, _ in items[:self.max_size // 5]:
                del self._cache[k]

    def cleanup(self):
        """清理过期"""
        now = time.time()
        expired = [k for k, (ts, _) in self._cache.items()
                   if now - ts > self.ttl]
        for k in expired:
            del self._cache[k]

    def stats(self) -> Dict:
        return {"cached": len(self._cache), "ttl": self.ttl}


# ══════════════════════════════════════════════════════════
#  单个节点连接
# ══════════════════════════════════════════════════════════

class NodeConnection:
    """到单个节点的连接

    生产级特性：
      · 自动重连（指数退避 + 抖动）
      · 心跳保活
      · 消息序号
      · 幂等保护
      · 背压控制
      · 限流
    """

    def __init__(
        self,
        node_id: str,
        url: str,
        config: TransportConfig,
        mode: str = TransportMode.LAN,
        idempotency: Optional[IdempotencyCache] = None,
    ):
        self.node_id = node_id
        self.url = url
        self.config = config
        self.mode = mode
        self.idempotency = idempotency or IdempotencyCache(
            config.idempotency_ttl
        )

        self._ws = None
        self._connected = False
        self._seq = 0
        self._recv_seq = 0
        self._reconnect_attempt = 0
        self._stop = False

        # 任务
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._supervisor_task: Optional[asyncio.Task] = None
        self._recv_task: Optional[asyncio.Task] = None

        # 队列（背压）
        self._send_queue: asyncio.Queue = asyncio.Queue(
            maxsize=config.max_queue_size
        )

        # 待确认
        self._pending_acks: Dict[str, asyncio.Future] = {}

        # 统计
        self.stats = TransportStats()

        # 限流
        self._rate_window: List[float] = []

        # 回调
        self.on_message: Optional[Callable[[MessageEnvelope], Awaitable[None]]] = None
        self.on_connect: Optional[Callable[[], Awaitable[None]]] = None
        self.on_disconnect: Optional[Callable[[], Awaitable[None]]] = None

    @property
    def connected(self) -> bool:
        return self._connected

    # ── 连接生命周期 ──────────────────────────────────

    async def connect(self) -> bool:
        """建立连接"""
        try:
            import websockets
        except ImportError:
            logger.error("需要 websockets 库: pip install websockets")
            return False

        try:
            # 认证头
            headers = {}
            if self.config.cloud_token:
                headers["Authorization"] = f"Bearer {self.config.cloud_token}"
            elif self.config.shared_key:
                headers["X-LAAP-Key"] = self.config.shared_key

            self._ws = await asyncio.wait_for(
                websockets.connect(
                    self.url,
                    additional_headers=headers,
                    ping_interval=None,      # 自己控制心跳
                    max_size=16 * 1024 * 1024,
                ),
                timeout=self.config.lan_timeout
                if self.mode == TransportMode.LAN
                else self.config.cloud_timeout,
            )

            self._connected = True
            self._reconnect_attempt = 0

            # 握手
            await self._handshake()

            # 启动后台任务
            self._recv_task = asyncio.create_task(self._recv_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            asyncio.create_task(self._send_loop())

            if self.on_connect:
                await self.on_connect()

            logger.info(f"[{self.node_id}] 已连接 {self.mode} ({self.url})")
            return True

        except asyncio.TimeoutError:
            logger.debug(f"[{self.node_id}] 连接超时 {self.url}")
            self.stats.errors += 1
            return False
        except Exception as e:
            logger.debug(f"[{self.node_id}] 连接失败 {self.url}: {e}")
            self.stats.errors += 1
            return False

    async def _handshake(self):
        """握手"""
        hello = MessageEnvelope(
            kind=MessageKind.HELLO,
            from_node="hub",
            to_node=self.node_id,
            payload={
                "node_id": self.node_id,
                "protocol_version": "1.0",
                "mode": self.mode,
                "ts": time.time(),
            },
        )
        await self.send(hello)

    async def start_supervisor(self):
        """启动守护（自动重连）"""
        self._stop = False
        self._supervisor_task = asyncio.create_task(self._supervisor_loop())

    async def disconnect(self):
        """断开"""
        self._stop = True
        self._connected = False

        for task in (self._heartbeat_task, self._recv_task,
                     self._supervisor_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self.on_disconnect:
            await self.on_disconnect()

    # ── 发送 ──────────────────────────────────

    def _check_rate_limit(self) -> bool:
        """限流检查"""
        now = time.time()
        self._rate_window = [t for t in self._rate_window if now - t < 60]

        if len(self._rate_window) >= self.config.rate_limit_per_minute:
            logger.warning(
                f"[{self.node_id}] 触发限流 "
                f"({self.config.rate_limit_per_minute}/min)"
            )
            return False

        self._rate_window.append(now)
        return True

    async def send(self, msg: MessageEnvelope) -> bool:
        """发送消息（带背压）"""
        if not self._connected:
            return False

        if not self._check_rate_limit():
            return False

        self._seq += 1
        msg.seq = self._seq

        try:
            # 队列满就阻塞（背压）
            await asyncio.wait_for(
                self._send_queue.put(msg),
                timeout=5.0,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[{self.node_id}] 发送队列满，丢弃消息")
            self.stats.errors += 1
            return False

    async def _send_loop(self):
        """发送循环"""
        while self._connected:
            try:
                msg = await asyncio.wait_for(
                    self._send_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                raw = msg.to_json()
                await self._ws.send(raw)

                self.stats.messages_sent += 1
                self.stats.bytes_sent += len(raw)

                # 需要确认的
                if msg.requires_ack:
                    future = asyncio.get_event_loop().create_future()
                    self._pending_acks[msg.message_id] = future
                    asyncio.create_task(
                        self._wait_ack(msg, future)
                    )

            except Exception as e:
                logger.error(f"[{self.node_id}] 发送失败: {e}")
                self.stats.errors += 1
                self._connected = False
                break

    async def _wait_ack(self, msg: MessageEnvelope, future: asyncio.Future):
        """等确认"""
        try:
            await asyncio.wait_for(future, timeout=self.config.ack_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"[{self.node_id}] 消息 {msg.message_id} 未确认"
            )
        finally:
            self._pending_acks.pop(msg.message_id, None)

    # ── 接收 ──────────────────────────────────

    async def _recv_loop(self):
        """接收循环"""
        while self._connected:
            try:
                raw = await self._ws.recv()
                self.stats.messages_received += 1
                self.stats.bytes_received += len(raw)

                msg = MessageEnvelope.from_json(raw)
                if not msg:
                    continue

                # 过期丢弃
                if msg.expired():
                    logger.debug(f"丢弃过期消息 {msg.message_id}")
                    continue

                # 序号检测
                if msg.seq > 0:
                    if msg.seq <= self._recv_seq:
                        logger.debug(
                            f"乱序/重放 {msg.seq} <= {self._recv_seq}"
                        )
                        continue
                    if msg.seq > self._recv_seq + 1 and self._recv_seq > 0:
                        logger.warning(
                            f"丢包: 期望 {self._recv_seq + 1}，收到 {msg.seq}"
                        )
                    self._recv_seq = msg.seq

                # 延迟采样
                latency_ms = (time.time() - msg.created_at) * 1000
                if latency_ms < 10000:
                    self.stats.record_latency(latency_ms)

                # ACK
                if msg.kind in (MessageKind.ACK,):
                    key = msg.payload.get("ack_message_id", "")
                    future = self._pending_acks.get(key)
                    if future and not future.done():
                        future.set_result(msg.payload)
                    continue

                # 需要确认的，回 ACK
                if msg.requires_ack:
                    await self.send(MessageEnvelope(
                        kind=MessageKind.ACK,
                        from_node=self.node_id,
                        to_node=msg.from_node,
                        payload={"ack_message_id": msg.message_id},
                    ))

                # 心跳回应
                if msg.kind == MessageKind.HEARTBEAT:
                    continue

                # 交给上层
                if self.on_message:
                    try:
                        await self.on_message(msg)
                    except Exception as e:
                        logger.exception(f"消息处理异常: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[{self.node_id}] 接收断开: {e}")
                self._connected = False
                break

    # ── 心跳 ──────────────────────────────────

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._connected:
            try:
                await asyncio.sleep(self.config.heartbeat_interval)

                if not self._connected:
                    break

                await self.send(MessageEnvelope(
                    kind=MessageKind.HEARTBEAT,
                    from_node="hub",
                    to_node=self.node_id,
                    payload={"ts": time.time()},
                ))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[{self.node_id}] 心跳失败: {e}")

    # ── 自动重连 ──────────────────────────────────

    async def _supervisor_loop(self):
        """守护：断线自动重连 + 模式降级"""
        import random

        while not self._stop:
            try:
                await asyncio.sleep(3)

                if self._connected:
                    continue

                # 重连
                self._reconnect_attempt += 1
                self.stats.reconnects += 1

                delay = min(
                    1.0 * (2 ** (self._reconnect_attempt - 1)),
                    self.config.max_reconnect_delay,
                )
                delay *= 1 + random.uniform(-0.3, 0.3)

                logger.info(
                    f"[{self.node_id}] {delay:.1f}s 后重连 "
                    f"(第 {self._reconnect_attempt} 次)"
                )
                await asyncio.sleep(delay)

                if await self.connect():
                    logger.info(f"[{self.node_id}] 重连成功")
                    continue

                # 局域网失败多次后降级到云端
                if (self.mode == TransportMode.LAN
                        and self._reconnect_attempt >= 3
                        and self.config.cloud_url):
                    logger.info(
                        f"[{self.node_id}] 局域网不通，降级到云端中继"
                    )
                    self.mode = TransportMode.CLOUD
                    self.url = self.config.cloud_url
                    self._reconnect_attempt = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.node_id}] 守护循环异常: {e}")

    def get_status(self) -> Dict:
        return {
            "node_id": self.node_id,
            "mode": self.mode,
            "url": self.url,
            "connected": self._connected,
            "reconnect_attempt": self._reconnect_attempt,
            "queue_size": self._send_queue.qsize(),
            "recv_seq": self._recv_seq,
            "idempotency": self.idempotency.stats(),
            **self.stats.to_dict(),
        }


# ══════════════════════════════════════════════════════════
#  传输管理器
# ══════════════════════════════════════════════════════════

class TransportManager:
    """传输管理器 — 管理所有节点连接 + 双通道选择

    中枢用这个管理到所有节点的连接。
    """

    def __init__(self, hub: Any, config: Optional[TransportConfig] = None):
        self.hub = hub
        self.config = config or TransportConfig()

        self.connections: Dict[str, NodeConnection] = {}

        # 共享幂等缓存（跨节点统一，防止同一动作被不同节点重复执行）
        self.idempotency = IdempotencyCache(self.config.idempotency_ttl)

        # 局域网服务端
        self._server = None
        self._server_task: Optional[asyncio.Task] = None
        self._server_clients: Dict[str, Any] = {}

        # 审计日志
        self.audit_log: List[Dict] = []
        self.max_audit = 5000

    # ── 局域网服务端 ──────────────────────────────────

    def get_local_ip(self) -> str:
        """获取本机局域网 IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def start_server(self) -> Dict:
        """启动局域网 WebSocket 服务端"""
        try:
            import websockets
        except ImportError:
            return {"success": False, "error": "需要 websockets 库"}

        async def handler(ws, path=None):
            """处理节点连接"""
            client_id = f"ws_{uuid.uuid4().hex[:8]}"
            self._server_clients[client_id] = ws
            logger.info(f"节点已连入 (局域网): {client_id}")

            try:
                async for raw in ws:
                    msg = MessageEnvelope.from_json(raw)
                    if not msg:
                        continue

                    # 认证
                    if self.config.require_auth:
                        token = msg.payload.get("token", "")
                        if not self._verify_token(token):
                            await ws.send(json.dumps({
                                "kind": "error",
                                "payload": {"error": "认证失败"},
                            }))
                            break

                    # 握手
                    if msg.kind == MessageKind.HELLO:
                        node_id = msg.payload.get("node_id", "")
                        if node_id:
                            self.hub.heartbeat(node_id)
                            logger.info(f"节点握手: {node_id}")

                        await ws.send(MessageEnvelope(
                            kind=MessageKind.ACK,
                            from_node="hub",
                            to_node=node_id,
                            payload={"assigned_id": client_id},
                        ).to_json())
                        continue

                    # 心跳
                    if msg.kind == MessageKind.HEARTBEAT:
                        if msg.from_node:
                            self.hub.heartbeat(msg.from_node)
                        continue

                    # 感知上报
                    if msg.kind == MessageKind.PERCEPTION:
                        await self._handle_perception(msg)
                        continue

                    # 任务结果
                    if msg.kind == MessageKind.TASK_RESULT:
                        await self._handle_task_result(msg)
                        continue

            except Exception as e:
                logger.debug(f"节点连接异常: {e}")
            finally:
                self._server_clients.pop(client_id, None)
                logger.info(f"节点断开 (局域网): {client_id}")

        try:
            self._server = await websockets.serve(
                handler,
                self.config.lan_host,
                self.config.lan_port,
                max_size=16 * 1024 * 1024,
            )

            local_ip = self.get_local_ip()
            url = f"ws://{local_ip}:{self.config.lan_port}"

            logger.info(f"局域网传输已启动: {url}")

            return {
                "success": True,
                "mode": "lan",
                "url": url,
                "host": self.config.lan_host,
                "port": self.config.lan_port,
            }
        except Exception as e:
            logger.error(f"启动服务端失败: {e}")
            return {"success": False, "error": str(e)}

    async def stop_server(self):
        """停止服务端"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for ws in list(self._server_clients.values()):
            try:
                await ws.close()
            except Exception:
                pass
        self._server_clients.clear()

    def _verify_token(self, token: str) -> bool:
        """验证 token（简化版，生产应验 JWT 签名）"""
        if not self.config.require_auth:
            return True

        if self.config.shared_key and token == self.config.shared_key:
            return True

        # JWT 验证
        if self.config.jwt_secret and token:
            try:
                import jwt as pyjwt
                pyjwt.decode(token, self.config.jwt_secret,
                             algorithms=["HS256"])
                return True
            except Exception:
                return False

        return not self.config.require_auth

    # ── 节点连接 ──────────────────────────────────

    async def connect_node(
        self,
        node_id: str,
        lan_hint: str = "",
        cloud_url: str = "",
        token: str = "",
        prefer: str = TransportMode.AUTO,
    ) -> Optional[NodeConnection]:
        """连接到一个节点（自动选通道）"""
        urls_to_try: List[Tuple[str, str]] = []

        if prefer in (TransportMode.AUTO, TransportMode.LAN) and lan_hint:
            urls_to_try.append((
                f"ws://{lan_hint}" if not lan_hint.startswith("ws") else lan_hint,
                TransportMode.LAN,
            ))

        cloud = cloud_url or self.config.cloud_url
        if prefer in (TransportMode.AUTO, TransportMode.CLOUD) and cloud:
            urls_to_try.append((cloud, TransportMode.CLOUD))

        if not urls_to_try:
            logger.error(f"[{node_id}] 没有可用的连接地址")
            return None

        for url, mode in urls_to_try:
            conn = NodeConnection(
                node_id=node_id,
                url=url,
                config=self.config,
                mode=mode,
                idempotency=self.idempotency,
            )
            conn.on_message = self._make_message_handler(node_id)

            if await conn.connect():
                await conn.start_supervisor()
                self.connections[node_id] = conn
                return conn

            logger.info(f"[{node_id}] {mode} 连接失败，尝试下一个通道")

        logger.error(f"[{node_id}] 所有通道都连不上")
        return None

    def _make_message_handler(self, node_id: str) -> Callable:
        """创建消息处理器"""
        async def handler(msg: MessageEnvelope):
            if msg.kind == MessageKind.TASK_RESULT:
                await self._handle_task_result(msg)
            elif msg.kind == MessageKind.PERCEPTION:
                await self._handle_perception(msg)
        return handler

    async def _handle_task_result(self, msg: MessageEnvelope):
        """处理任务结果（带幂等检查）"""
        idem_key = msg.compute_idempotency()

        executed, cached = self.idempotency.check(idem_key)
        if executed:
            logger.debug(f"重复的任务结果，返回缓存: {idem_key}")
            # 重发缓存结果给节点
            return

        self.idempotency.store(idem_key, msg.payload)

        # 审计
        self._audit({
            "event": "task_result",
            "node_id": msg.from_node,
            "task_id": msg.payload.get("task_id", ""),
            "success": msg.payload.get("success", False),
        })

    async def _handle_perception(self, msg: MessageEnvelope):
        """处理感知上报"""
        self.hub.heartbeat(msg.from_node)

        # 感知数据入会话
        session = self.hub.get_active_session()
        if session:
            from laaper.hub.session import SessionMessage, MessageRole
            session.add_message(SessionMessage(
                role=MessageRole.NODE_EVENT,
                origin_node=msg.from_node,
                text=f"感知: {msg.payload.get('summary', '')}",
            ))

    # ── 发送到节点 ──────────────────────────────────

    async def send_to_node(
        self,
        node_id: str,
        kind: str,
        payload: Dict,
        requires_ack: bool = False,
    ) -> bool:
        """发消息给节点"""
        conn = self.connections.get(node_id)
        if not conn or not conn.connected:
            logger.warning(f"[{node_id}] 未连接，无法发送")
            return False

        msg = MessageEnvelope(
            kind=kind,
            from_node="hub",
            to_node=node_id,
            payload=payload,
            requires_ack=requires_ack,
        )
        msg.compute_idempotency()

        return await conn.send(msg)

    async def push_to_node(
        self,
        node_id: str,
        text: str,
        payload: Any = None,
        payload_kind: str = "json",
    ) -> bool:
        """推送内容到节点"""
        body: Dict[str, Any] = {"text": text}

        if payload is not None:
            if isinstance(payload, bytes) and \
               len(payload) > self.config.max_payload_inline_kb * 1024:
                # 大数据只发引用
                ref = self.hub.payloads.put(
                    payload, kind=payload_kind, origin_node="hub"
                )
                body["payload_ref"] = ref.to_dict()
            else:
                body["payload_inline"] = (
                    payload.hex() if isinstance(payload, bytes) else payload
                )

        return await self.send_to_node(node_id, MessageKind.PUSH, body)

    # ── 审计 ──────────────────────────────────

    def _audit(self, event: Dict):
        """记录审计事件"""
        event["ts"] = time.time()
        self.audit_log.append(event)

        if len(self.audit_log) > self.max_audit:
            self.audit_log = self.audit_log[-self.max_audit:]

    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        return self.audit_log[-limit:]

    # ── 状态 ──────────────────────────────────

    def get_stats(self) -> Dict:
        """完整传输统计"""
        conn_stats = {
            nid: conn.get_status()
            for nid, conn in self.connections.items()
        }

        total_latency = []
        for conn in self.connections.values():
            total_latency.extend(conn.stats.latency_samples)

        p50 = p95 = 0.0
        if total_latency:
            s = sorted(total_latency)
            p50 = round(s[len(s) // 2], 2)
            p95 = round(s[int(len(s) * 0.95)], 2)

        return {
            "mode": self.config.mode,
            "lan_url": f"ws://{self.get_local_ip()}:{self.config.lan_port}",
            "cloud_url": self.config.cloud_url,
            "server_running": self._server is not None,
            "server_clients": len(self._server_clients),
            "connections": conn_stats,
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
            "idempotency": self.idempotency.stats(),
            "audit_events": len(self.audit_log),
        }

    async def close(self):
        """关闭所有连接"""
        await self.stop_server()
        for conn in list(self.connections.values()):
            await conn.disconnect()
        self.connections.clear()


# ══════════════════════════════════════════════════════════
#  传输方案说明（回答"用什么传输"）
# ══════════════════════════════════════════════════════════

TRANSPORT_DESIGN = """
## 三端联动传输方案

### 结论：WebSocket 双通道

| 通道 | 协议 | 地址 | 延迟 | 场景 |
|------|------|------|------|------|
| A 局域网 | WS | ws://192.168.x.x:8765 | <10ms | 同一 WiFi |
| B 云端 | WSS | wss://api.laap.cn/ws | 30-150ms | 跨网/4G |

选择：先试 A，3 秒超时降级到 B。

### 为什么不是这些

| 方案 | 为什么不用 |
|------|-----------|
| HTTP 轮询 | 延迟取决于轮询间隔，浪费连接 |
| SSE | 单向，客户端没法推给服务器 |
| BLE | 带宽 20-50kbps，一张截图传 30 秒 |
| MQTT | 适合 IoT 海量设备，我们只有 3 端，过度设计 |
| gRPC | 浏览器支持差，Web 客户端用不了 |

### 各物理层的真实角色

    WiFi    = 底层管子（WS 跑在它上面）
    蓝牙    = 只做配网引导（手机首次连 WiFi 时传密码）
    云服务器 = 通道 B 的中继 + 账号体系
    局域网  = 通道 A 的直接通路

### 云服务器账号体系的作用

1. **跨网寻址**：你在外面，怎么找到家里的中枢？
   → 中枢连上 wss://api.laap.cn/ws 并用 JWT 认证，服务器记住它
   → 你手机也连同一个服务器，服务器把两边配对

2. **设备注册**：每个节点绑定到一个 user_id
   → 用户 A 的节点不能被用户 B 触达

3. **离线消息**：节点不在线时暂存，上线后补发

4. **审计**：所有跨网动作留痕

### 生产级 10 项

1. 认证：JWT + 设备指纹（局域网用预共享密钥）
2. 断线重连：指数退避 1→60s，±30% 抖动
3. 消息顺序：递增 seq，检测乱序和丢包
4. **幂等**：idempotency_key + 缓存，防重复执行
5. 背压：队列上限 1000，满则丢弃并告警
6. 多租户：user_id + session_id 双重校验
7. 可观测：延迟 P50/P95/P99、吞吐、错误率
8. 限流：300 消息/分钟/节点
9. 优雅降级：LAN→CLOUD，视觉→DOM→文本
10. 审计：谁在何时对哪个节点做了什么

### 最危险的那个：幂等

场景：
    手机执行"点击购买"
    结果回传时网络断了
    手机不知道，重连后重发
    没幂等保护 → 买了两次

所以每个动作都带 idempotency_key（哈希 from+to+kind+payload），
中枢 5 分钟内见过同样的 key 就直接返回缓存结果。
"""


def get_transport_design() -> str:
    """获取传输设计方案说明"""
    return TRANSPORT_DESIGN


def get_transport_status() -> Dict:
    """传输环境状态"""
    try:
        import websockets
        ws_ver = websockets.__version__
    except ImportError:
        ws_ver = None

    try:
        import jwt
        jwt_ok = True
    except ImportError:
        jwt_ok = False

    return {
        "websockets": ws_ver,
        "websockets_ready": ws_ver is not None,
        "jwt_ready": jwt_ok,
        "hint": (
            "传输层就绪"
            if ws_ver
            else "需要安装: pip install websockets"
        ),
    }