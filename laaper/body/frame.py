"""LBP/1.0 链路层 — 帧编解码、CRC、分片重组

## 帧格式（medium-independent）

```
偏移  长度  字段      说明
─────────────────────────────────────────────────────────
0     1     SOF       0x4C ('L')
1     1     VER       [7:4]major [3:0]minor → 0x10 = 1.0
2     1     TYPE      消息类型
3     1     FLAGS     [7]分片 [6:5]优先级 [4]需应答
4     1     SRC       源模块 ID（1-254，0=未分配，255=广播）
5     1     DST       目标模块 ID
6     2     SEQ       序号（LE）
8     1     TTL       跳数限制
9     3     RSVD      保留
12    4     T_EXEC    执行时间戳（µs, LE）
16    2     LEN       载荷长度（0-1024）
18    N     PAYLOAD
18+N  4     CRC32     CRC-32/ISO-HDLC，覆盖 VER..PAYLOAD
22+N  1     EOF       0xAA
─────────────────────────────────────────────────────────
```

## 两个关键设计

**1. T_EXEC 执行时间戳**

不是"立即执行"，是"在全局时刻 T 执行"。所有模块收到同一批指令，
各自等到 T 那一刻同时动作。这是分布式多关节协同的基础 ——
没有它，CAN 总线的传输延迟会让 20 个关节出现 1-2ms 相位差。

**2. 优先级在帧头里，不在软件队列里**

SAFE_STOP 必须在链路层就能插队。等它排到软件队列前面，
关节已经撞上了。

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple

# ══════════════════════════════════════════════════════════
#  常量
# ══════════════════════════════════════════════════════════

SOF = 0x4C          # 'L'
EOF = 0xAA
VER_MAJOR = 1
VER_MINOR = 0
VER_BYTE = (VER_MAJOR << 4) | VER_MINOR

HDR_SIZE = 18       # SOF..LEN
TRAILER_SIZE = 5    # CRC32 + EOF
MIN_FRAME = HDR_SIZE + TRAILER_SIZE

MAX_PAYLOAD = 1024
MAX_CAN_PAYLOAD = 64        # CAN FD 单帧上限

ADDR_UNASSIGNED = 0
ADDR_BROADCAST = 0xFF


class MsgType(IntEnum):
    """LBP 消息类型"""
    ENUM_REQ = 0x01         # 主机→广播：枚举，分配地址
    ENUM_ACK = 0x02         # 模块→主机：应答 + 完整 BMD
    CAPS = 0x03             # 模块→主机：能力上报
    CMD = 0x04              # 主机→模块：运动指令（带 T_EXEC）
    TELEM = 0x05            # 模块→主机：遥测
    CLOCK_SYNC = 0x06       # 主机→广播：时钟同步
    TOPO_REQ = 0x07         # 主机→模块：查询端口连接
    TOPO_ACK = 0x08         # 模块→主机：端口连接应答
    BODY_SCHEMA = 0x09      # 主机→广播：广播身体图式
    REFLEX = 0x0A           # 模块→主机：反射事件
    SAFE_STOP = 0x0B        # 任意→广播：最高优先级停止
    FRAG = 0x0C             # 双向：分片
    HEARTBEAT = 0x0D        # 双向：心跳
    OTA = 0x0E              # 主机→模块：固件升级


class Priority(IntEnum):
    """帧优先级 —— 0 最高。

    高优先级在链路仲裁时抢占总线（CAN 的 ID 仲裁天然支持，
    以太网靠 Q-Tag / 时间片）。
    """
    SAFETY = 0      # SAFE_STOP / REFLEX：< 100µs 必须送达
    CONTROL = 1     # CMD / TELEM：技能层 10Hz
    CONFIG = 2      # ENUM / TOPO / BODY_SCHEMA
    BULK = 3        # OTA / 大载荷分片


class Flags(IntEnum):
    NONE = 0
    FRAGMENT = 1 << 7       # 是分片
    ACK_REQ = 1 << 4        # 需要应答


# ══════════════════════════════════════════════════════════
#  帧
# ══════════════════════════════════════════════════════════

@dataclass
class LBPFrame:
    """一个 LBP 帧"""
    type: MsgType
    src: int
    dst: int
    payload: bytes = b""
    seq: int = 0
    ttl: int = 8
    t_exec_us: int = 0                      # 0 = 立即执行
    priority: Priority = Priority.CONTROL
    flags: int = 0

    def __post_init__(self):
        if not (0 <= self.src <= 255):
            raise ValueError(f"src 越界: {self.src}")
        if not (0 <= self.dst <= 255):
            raise ValueError(f"dst 越界: {self.dst}")
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError(
                f"载荷 {len(self.payload)} > {MAX_PAYLOAD}，需分片")

    # ── 编码 ──
    def encode(self) -> bytes:
        fl = (int(self.flags) & 0xF0) | ((int(self.priority) & 0x03) << 5)
        hdr = struct.pack(
            "<BBBBBBHB3xIH",
            SOF,
            VER_BYTE,
            int(self.type),
            fl & 0xFF,
            self.src,
            self.dst,
            self.seq & 0xFFFF,
            self.ttl & 0xFF,
            self.t_exec_us & 0xFFFFFFFF,
            len(self.payload),
        )
        body = hdr + self.payload
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return body + struct.pack("<I", crc) + bytes([EOF])

    @property
    def wire_size(self) -> int:
        return HDR_SIZE + len(self.payload) + TRAILER_SIZE

    # ── 解码 ──
    @classmethod
    def decode(cls, data: bytes) -> "LBPFrame":
        if len(data) < MIN_FRAME:
            raise ValueError(f"帧太短: {len(data)} < {MIN_FRAME}")
        if data[0] != SOF:
            raise ValueError(f"SOF 错误: 0x{data[0]:02X}")
        if data[-1] != EOF:
            raise ValueError(f"EOF 错误: 0x{data[-1]:02X}")

        (sof, ver, typ, fl, src, dst, seq, ttl,
         t_exec, length) = struct.unpack("<BBBBBBHB3xIH", data[:HDR_SIZE])

        expect_len = HDR_SIZE + length + TRAILER_SIZE
        if len(data) != expect_len:
            raise ValueError(
                f"长度不符: 声明 {length}B → 期望 {expect_len}，实际 {len(data)}")

        payload = data[HDR_SIZE:HDR_SIZE + length]
        crc_recv = struct.unpack("<I", data[HDR_SIZE + length:HDR_SIZE + length + 4])[0]
        crc_calc = zlib.crc32(data[:HDR_SIZE + length]) & 0xFFFFFFFF
        if crc_recv != crc_calc:
            raise ValueError(
                f"CRC 校验失败: 收到 0x{crc_recv:08X} 计算 0x{crc_calc:08X}")

        try:
            mtype = MsgType(typ)
        except ValueError:
            raise ValueError(f"未知消息类型: 0x{typ:02X}")

        return cls(
            type=mtype, src=src, dst=dst, payload=payload, seq=seq,
            ttl=ttl, t_exec_us=t_exec,
            priority=Priority((fl >> 5) & 0x03),
            flags=fl & 0xF0,
        )

    def describe(self) -> str:
        return (f"{self.type.name} {self.src}→{self.dst} "
                f"seq={self.seq} {len(self.payload)}B "
                f"t_exec={self.t_exec_us}us prio={self.priority.name}")


# ══════════════════════════════════════════════════════════
#  分片（CAN FD 载荷只有 64B，大 BMD 必须分片）
# ══════════════════════════════════════════════════════════

@dataclass
class Fragment:
    """分片头（放在 FRAG 帧载荷前 4 字节）"""
    group_id: int       # 分片组标识
    index: int          # 第几片
    total: int          # 共几片

    HEADER_SIZE = 4

    def pack(self) -> bytes:
        return struct.pack("<HBB", self.group_id & 0xFFFF,
                           self.index & 0xFF, self.total & 0xFF)

    @classmethod
    def unpack(cls, data: bytes) -> Tuple["Fragment", bytes]:
        if len(data) < cls.HEADER_SIZE:
            raise ValueError("分片头不完整")
        gid, idx, tot = struct.unpack("<HBB", data[:4])
        return cls(gid, idx, tot), data[4:]


class Fragmenter:
    """把大载荷拆成多帧，接收侧重组

    ## 参数语义（容易搞错，所以写清楚）

    `max_frame_bytes` 是**整个 LBP 帧在线上的字节数**，不是载荷：
      · CAN FD：64 字节（ISO 11898-2 的 data field 上限）
      · 以太网：1500 字节（MTU）

    所以实际载荷 = max_frame_bytes - LBP头(18) - LBP尾(5) - 分片头(4)
    CAN FD → 64 - 18 - 5 - 4 = 37 字节

    之前把 max_payload 当载荷长，算出来一帧 82 字节，CAN 上根本发不出。

    用法：
        frag = Fragmenter(max_frame_bytes=64)      # CAN FD
        frames = frag.split(proto, big_data)
        data = frag.receive(frame)                 # 集齐才非 None
    """

    def __init__(self, max_frame_bytes: int = MAX_CAN_PAYLOAD):
        self.max_frame_bytes = max_frame_bytes
        self._next_gid = 1
        self._rx: Dict[Tuple[int, int], Dict] = {}
        self._stats = {"sent_groups": 0, "recv_groups": 0,
                       "dropped_groups": 0, "detected_loss": 0}

    @property
    def max_chunk(self) -> int:
        """单片能装的真实数据量"""
        return self.max_frame_bytes - HDR_SIZE - TRAILER_SIZE - Fragment.HEADER_SIZE

    # ── 发送侧 ──
    def split(self, proto: LBPFrame, data: bytes) -> List[LBPFrame]:
        """拆分。data 长度必须 > max_chunk 才值得分片"""
        chunk = self.max_chunk
        if chunk <= 0:
            raise ValueError(
                f"max_frame_bytes={self.max_frame_bytes} 太小，"
                f"装不下帧头({HDR_SIZE})+尾({TRAILER_SIZE})+分片头({Fragment.HEADER_SIZE})")

        n = (len(data) + chunk - 1) // chunk
        if n > 255:
            raise ValueError(f"需要 {n} 片，超过上限 255（增大 max_frame_bytes）")

        gid = self._next_gid
        self._next_gid = (self._next_gid % 0xFFFE) + 1
        self._stats["sent_groups"] += 1

        out = []
        for i in range(n):
            frag = Fragment(gid, i, n)
            piece = data[i * chunk:(i + 1) * chunk]
            out.append(LBPFrame(
                type=MsgType.FRAG,
                src=proto.src, dst=proto.dst,
                payload=frag.pack() + piece,
                seq=(proto.seq + i) & 0xFFFF,
                ttl=proto.ttl,
                t_exec_us=proto.t_exec_us,
                priority=proto.priority,
                flags=Flags.FRAGMENT,
            ))
        return out

    # ── 接收侧 ──
    def receive(self, frame: LBPFrame) -> Optional[Tuple[LBPFrame, bytes]]:
        """收到一个 FRAG 帧。

        返回 (原始帧头模板, 完整数据) 当集齐时；否则 None。
        """
        if frame.type != MsgType.FRAG:
            return None

        frag, piece = Fragment.unpack(frame.payload)
        key = (frame.src, frag.group_id)

        if frag.index == 0:
            self._rx[key] = {"total": frag.total, "parts": {}, "hdr": frame}

        state = self._rx.get(key)
        if state is None:
            # 首片丢了，后续片无处安放
            self._stats["detected_loss"] += 1
            return None

        state["parts"][frag.index] = piece

        if len(state["parts"]) < state["total"]:
            return None

        # 齐了
        try:
            data = b"".join(state["parts"][i] for i in range(state["total"]))
        except KeyError:
            self._stats["dropped_groups"] += 1
            del self._rx[key]
            return None

        hdr = state["hdr"]
        del self._rx[key]
        self._stats["recv_groups"] += 1
        return hdr, data

    @property
    def stats(self) -> dict:
        return dict(self._stats, pending_groups=len(self._rx))


# ══════════════════════════════════════════════════════════
#  优先级调度（发送侧）
# ══════════════════════════════════════════════════════════

class PriorityQueue:
    """按优先级出队的发送队列

    SAFETY 队永远先出。这不是优化，是安全要求：
    SAFE_STOP 排在 20 个 CMD 后面送达，关节已经撞上了。
    """

    def __init__(self, capacity: int = 256):
        self.capacity = capacity
        self._q: Dict[Priority, List[LBPFrame]] = {p: [] for p in Priority}
        self.dropped = 0

    def push(self, frame: LBPFrame) -> bool:
        q = self._q[frame.priority]
        if len(q) >= self.capacity // 4:
            if frame.priority == Priority.SAFETY:
                q.pop(0)          # 挤掉最旧的 SAFETY（极少发生）
            else:
                self.dropped += 1
                return False
        q.append(frame)
        return True

    def pop(self) -> Optional[LBPFrame]:
        for p in Priority:
            if self._q[p]:
                return self._q[p].pop(0)
        return None

    def __len__(self) -> int:
        return sum(len(v) for v in self._q.values())

    def by_priority(self) -> Dict[str, int]:
        return {p.name: len(self._q[p]) for p in Priority if self._q[p]}


# ══════════════════════════════════════════════════════════
#  时钟同步（简化 PTP）
# ══════════════════════════════════════════════════════════

@dataclass
class ClockSync:
    """主从时钟偏移估计

    实际实现走 PTP 四时间戳（t1 t2 t3 t4），这里给出偏移估计部分。
    精度目标：
      · 以太网骨干：< 1µs（gPTP）
      · CAN 关节：< 10µs（硬件时间戳 + 周期 SYNC）
    1kHz 反射周期 = 1000µs，10µs 抖动是 1%，可接受。
    """
    offset_us: float = 0.0
    drift_ppm: float = 0.0
    last_sync_us: int = 0
    synced: bool = False

    def update(self, t1: int, t2: int, t3: int, t4: int) -> None:
        """PTP 四时间戳
        t1: 主时钟发出 Sync 的本地时刻
        t2: 从时钟收到 Sync 的本地时刻
        t3: 从时钟发出 Delay_Req 的本地时刻
        t4: 主时钟收到 Delay_Req 的时刻
        """
        # 往返延迟与偏移
        delay = ((t2 - t1) + (t4 - t3)) / 2.0
        offset = ((t2 - t1) - (t4 - t3)) / 2.0
        self.offset_us = offset
        self.last_sync_us = t4
        self.synced = True
        # 往返延迟可用于判断链路质量（delay 突然变大 = 拥塞/丢线）

    def to_global(self, local_us: int) -> int:
        """本地时钟 → 全局时钟"""
        return int(local_us - self.offset_us)

    def to_local(self, global_us: int) -> int:
        """全局时钟 → 本地时钟"""
        return int(global_us + self.offset_us)


def bandwidth_estimate(joints: int, telem_hz: float, cmd_hz: float,
                       telem_bytes: int = 40, cmd_bytes: int = 32,
                       bitrate_bps: int = 5_000_000) -> dict:
    """带宽核算 —— 判断一套配置能否跑在给定总线上

    这个函数存在的意义：反射层 1kHz 到底能不能走总线？
    算完就知道答案，不用猜。
    """
    overhead = HDR_SIZE + TRAILER_SIZE
    cmd_bits = (cmd_bytes + overhead) * 8
    telem_bits = (telem_bytes + overhead) * 8

    cmd_total = joints * cmd_hz * cmd_bits
    telem_total = joints * telem_hz * telem_bits
    total = cmd_total + telem_total

    return {
        "cmd_bps": round(cmd_total),
        "telem_bps": round(telem_total),
        "total_bps": round(total),
        "bitrate_bps": bitrate_bps,
        "utilization": round(total / bitrate_bps, 4),
        "fits": total <= bitrate_bps * 0.7,   # 70% 是工程安全线
    }