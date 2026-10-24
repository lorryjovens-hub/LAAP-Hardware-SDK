"""LBP/1.0 载荷编解码

## 为什么载荷必须是紧凑二进制，不能是 JSON

实测踩到的：用 JSON 编 TOPO_ACK（`{"addr":2,"mount_port":0,"children":[]}`），
整帧 **67 字节**，超过 CAN 2.0B 的 64 字节上限，直接发不出去。

同样的信息用二进制只要 **3 字节**。

在 5 Mbps 总线、20 关节、100 Hz 的场景下，这个差距是
「跑得动」和「跑不动」的区别：

    JSON  CMD  约 30B 载荷 → 帧 53B → 20 关节 100Hz = 848 kbps
    二进制 CMD 12B 载荷  → 帧 35B → 20 关节 100Hz = 560 kbps   ← 省 34%

所以 LBP 的所有载荷统一用**小端二进制**，字段顺序和长度固定。

## 与 C 实现的对应

每个编解码函数的布局直接对应 C 的 struct，无对齐填充：

    #pragma pack(push, 1)
    typedef struct { uint8_t addr, mount_port, child_count; } lbp_topo_ack_t;
    #pragma pack(pop)

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import struct
from typing import List, Tuple

# ══════════════════════════════════════════════════════════
#  TOPO_ACK — 端口连接表
# ══════════════════════════════════════════════════════════

def encode_topo_ack(addr: int, mount_port: int,
                    children: List[Tuple[int, int]]) -> bytes:
    """children = [(port_id, child_addr), ...]

    布局：addr(1) mount_port(1) child_count(1) [port(1) child(1)] × N
    空子表 → 3 字节
    """
    if len(children) > 127:
        raise ValueError("子模块数超过 127")
    buf = struct.pack("<BBB", addr & 0xFF, mount_port & 0xFF, len(children))
    for port, child in children:
        buf += struct.pack("<BB", port & 0xFF, child & 0xFF)
    return buf


def decode_topo_ack(data: bytes) -> Tuple[int, int, List[Tuple[int, int]]]:
    if len(data) < 3:
        raise ValueError(f"TOPO_ACK 太短: {len(data)}B")
    addr, mount_port, n = struct.unpack("<BBB", data[:3])
    if len(data) < 3 + n * 2:
        raise ValueError(f"TOPO_ACK 长度不符: 声明 {n} 个子模块，"
                         f"实际只有 {len(data) - 3}B")
    children = []
    off = 3
    for _ in range(n):
        port, child = struct.unpack("<BB", data[off:off + 2])
        children.append((port, child))
        off += 2
    return addr, mount_port, children


# ══════════════════════════════════════════════════════════
#  CMD — 关节目标
# ══════════════════════════════════════════════════════════

def encode_cmd(q: List[float], flags: int = 0) -> bytes:
    """布局：flags(1) dof(1) q(float32 LE) × dof

    3 DOF → 2 + 12 = 14 字节（JSON 要 30 字节）
    """
    if len(q) > 32:
        raise ValueError("单条 CMD 最多 32 个关节")
    buf = struct.pack("<BB", flags & 0xFF, len(q))
    for v in q:
        buf += struct.pack("<f", float(v))
    return buf


def decode_cmd(data: bytes) -> Tuple[int, List[float]]:
    if len(data) < 2:
        raise ValueError("CMD 太短")
    flags, dof = struct.unpack("<BB", data[:2])
    need = 2 + dof * 4
    if len(data) < need:
        raise ValueError(f"CMD 长度不符: 需要 {need}B，实际 {len(data)}B")
    q = list(struct.unpack(f"<{dof}f", data[2:need]))
    return flags, q


# ══════════════════════════════════════════════════════════
#  TELEM — 遥测
# ══════════════════════════════════════════════════════════

def encode_telem(addr: int, q: List[float],
                 torque: List[float] | None = None,
                 temp_c: float | None = None) -> bytes:
    """布局：addr(1) flags(1) dof(1) q(float32)×dof [torque(float32)×dof] [temp(i8)]

    flags: bit0 = 带力矩，bit1 = 带温度
    """
    flags = 0
    if torque:
        flags |= 0x01
    if temp_c is not None:
        flags |= 0x02

    buf = struct.pack("<BBB", addr & 0xFF, flags, len(q))
    for v in q:
        buf += struct.pack("<f", float(v))
    if torque:
        for v in torque:
            buf += struct.pack("<f", float(v))
    if temp_c is not None:
        buf += struct.pack("<b", max(-128, min(127, int(temp_c))))
    return buf


def decode_telem(data: bytes) -> dict:
    if len(data) < 3:
        raise ValueError("TELEM 太短")
    addr, flags, dof = struct.unpack("<BBB", data[:3])
    off = 3
    need = off + dof * 4
    if len(data) < need:
        raise ValueError("TELEM 位置数据不完整")
    q = list(struct.unpack(f"<{dof}f", data[off:need]))
    off = need

    out = {"addr": addr, "q": q, "torque": None, "temp_c": None}

    if flags & 0x01:
        need = off + dof * 4
        if len(data) >= need:
            out["torque"] = list(struct.unpack(f"<{dof}f", data[off:need]))
            off = need
    if flags & 0x02 and len(data) > off:
        out["temp_c"] = struct.unpack("<b", data[off:off + 1])[0]

    return out


# ══════════════════════════════════════════════════════════
#  REFLEX — 反射事件
# ══════════════════════════════════════════════════════════

class ReflexCode:
    OVER_CURRENT = 0x01
    STALL = 0x02
    OVER_TEMP = 0x03
    COLLISION = 0x04
    LOST_SYNC = 0x05
    POSITION_ERROR = 0x06


def encode_reflex(addr: int, code: int, joint: int,
                  value: float = 0.0) -> bytes:
    """布局：addr(1) code(1) joint(1) value(float32) → 7 字节"""
    return struct.pack("<BBBf", addr & 0xFF, code & 0xFF,
                       joint & 0xFF, float(value))


def decode_reflex(data: bytes) -> dict:
    if len(data) < 7:
        raise ValueError("REFLEX 太短")
    addr, code, joint, value = struct.unpack("<BBBf", data[:7])
    return {"addr": addr, "code": code, "joint": joint, "value": value}


# ══════════════════════════════════════════════════════════
#  CLOCK_SYNC
# ══════════════════════════════════════════════════════════

def encode_clock_sync(t1_us: int) -> bytes:
    """主机发出时刻（8 字节，µs）"""
    return struct.pack("<Q", int(t1_us))


def decode_clock_sync(data: bytes) -> int:
    if len(data) < 8:
        raise ValueError("CLOCK_SYNC 太短")
    return struct.unpack("<Q", data[:8])[0]


# ══════════════════════════════════════════════════════════
#  尺寸参考（写固件时对照用）
# ══════════════════════════════════════════════════════════

def size_reference() -> dict:
    """各消息在典型参数下的载荷/整帧大小"""
    from .frame import HDR_SIZE, TRAILER_SIZE

    def frame(payload: int) -> int:
        return HDR_SIZE + payload + TRAILER_SIZE

    rows = [
        ("TOPO_ACK（无子模块）", len(encode_topo_ack(2, 0, []))),
        ("TOPO_ACK（2 子模块）", len(encode_topo_ack(2, 0, [(0, 3), (1, 4)]))),
        ("CMD（3 DOF）", len(encode_cmd([0.0, 0.0, 0.0]))),
        ("CMD（12 DOF）", len(encode_cmd([0.0] * 12))),
        ("TELEM（3 DOF 纯位置）", len(encode_telem(2, [0.0] * 3))),
        ("TELEM（3 DOF +力矩+温度）",
         len(encode_telem(2, [0.0] * 3, [0.0] * 3, 45))),
        ("REFLEX", len(encode_reflex(2, ReflexCode.OVER_CURRENT, 1, 2.5))),
        ("CLOCK_SYNC", len(encode_clock_sync(1_000_000))),
    ]
    return {
        r[0]: {"payload": r[1], "frame": frame(r[1]),
               "fits_can": frame(r[1]) <= 64}
        for r in rows
    }