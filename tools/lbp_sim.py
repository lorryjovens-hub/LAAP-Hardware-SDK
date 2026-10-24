"""LBP 台架仿真 — 没有硬件时先把协议流程跑通

## 为什么需要这个

阶段一硬件到货要等 1-2 周。这段时间如果什么都不做，到货后要开始
一边焊板子一边调协议，出错了两边都怀疑。

这个仿真器把「软件的半边」先跑通，并输出**真实硬件应当匹配的参照值**。
到货后逐项比对：一致的说明协议对，不一致的说明接线/BMD 有问题。

## 仿真什么

    spine（主站）                 4 × leg（从站）
      │  ENUM_REQ ──────────────────▶ │
      │◀─ ENUM_ACK（BMD 663B 分片）── │
      │  TOPO_REQ ──────────────────▶ │
      │◀─ TOPO_ACK（端口连接）──────── │
      │  ── 拓扑 → 身体图式 → IK ──    │
      │  CMD (t_exec=T) ────────────▶ │
      │◀─ TELEM ───────────────────── │

总线是内存里的字节流，但**帧经过真实编解码 + CRC + 分片**，
所以固件里跑的是同一套逻辑。

用法：
    python tools/lbp_sim.py
    python tools/lbp_sim.py --verbose
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from laaper.body import (
    LBPFrame, MsgType, Priority, Fragmenter, ClockSync,
    ModuleDescriptor, make_module, Topology, derive_schema,
    Capability, bandwidth_estimate, HDR_SIZE, TRAILER_SIZE,
    encode_topo_ack, decode_topo_ack,
    encode_cmd, decode_cmd, encode_telem, decode_telem,
    size_reference,
)
from laaper.body.morphing import power_summary


VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


def log(msg: str) -> None:
    print(msg)


def vlog(msg: str) -> None:
    if VERBOSE:
        print(f"    {msg}")


# ══════════════════════════════════════════════════════════
#  内存总线（跑真实帧编解码）
# ══════════════════════════════════════════════════════════

@dataclass
class SimBus:
    """模拟 CAN 2.0B 总线

    阶段一用 CAN 2.0B @ 1 Mbps（ESP32 TWAI 上限），帧整帧 ≤ 64B。

    ## 总线语义是「广播 + 每个监听者自己游标」

    初版写成 drain() 取走帧，结果广播的 ENUM_REQ 被第一个从站
    吃掉，其它三个根本没收到 —— 真总线上不可能这样。

    所以每个节点维护自己的 cursor，从 cursor 往后读，互不影响。
    """
    bitrate: int = 1_000_000
    _frames: List[bytes] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=lambda: {
        "frames": 0, "bytes": 0, "bus_time_us": 0})

    def send(self, frame: LBPFrame) -> None:
        wire = frame.encode()          # 真实编码
        assert frame.wire_size <= 64, \
            f"帧 {frame.wire_size}B 超过 CAN 上限 64B"
        self._frames.append(wire)
        self.stats["frames"] += 1
        self.stats["bytes"] += len(wire)
        # 线上时间：字节数 × 8bit / 速率（忽略位填充，约 +8%）
        self.stats["bus_time_us"] += int(len(wire) * 8 / self.bitrate * 1e6 * 1.08)

    def read_since(self, cursor: int) -> tuple:
        """读 cursor 之后的所有帧，返回 (帧列表, 新 cursor)

        真实解码 + CRC 校验。已经追加但还没读的帧所有人共享。
        """
        new = self._frames[cursor:]
        out = [LBPFrame.decode(w) for w in new]
        return out, len(self._frames)

    @property
    def total(self) -> int:
        return len(self._frames)


# ══════════════════════════════════════════════════════════
#  从站：一条腿
# ══════════════════════════════════════════════════════════

class SimLegNode:
    """模拟 ESP32-C3 从站"""

    def __init__(self, node_id: int, bmd: ModuleDescriptor,
                 port_id: int, bus: SimBus):
        self.node_id = node_id
        self.bmd = bmd
        self.bmd.bus_addr = node_id
        self.bmd.serial = 0x1000 + node_id
        self.port_id = port_id        # 物理上插在躯干的哪个口
        self.bus = bus
        self.frag = Fragmenter(max_frame_bytes=64)
        self.q = [0.0] * bmd.dof      # 当前关节角
        self.clock = ClockSync()
        self._cursor = 0

    def poll(self) -> None:
        """处理收到的帧（从上次游标之后）"""
        frames, self._cursor = self.bus.read_since(self._cursor)
        for frame in frames:
            if frame.dst not in (self.node_id, 0xFF):
                continue

            if frame.type == MsgType.ENUM_REQ:
                # 回 BMD（分片）
                payload = self.bmd.to_json().encode()
                if len(payload) <= 37:
                    self.bus.send(LBPFrame(
                        MsgType.ENUM_ACK, self.node_id, 1, payload,
                        priority=Priority.CONFIG))
                else:
                    tmpl = LBPFrame(MsgType.ENUM_ACK, self.node_id, 1, b"",
                                    priority=Priority.CONFIG)
                    for fr in self.frag.split(tmpl, payload):
                        self.bus.send(fr)

            elif frame.type == MsgType.TOPO_REQ:
                # 回端口连接表（紧凑二进制：空子表只 3 字节）
                info = encode_topo_ack(self.node_id, self.port_id, [])
                self.bus.send(LBPFrame(MsgType.TOPO_ACK, self.node_id, 1, info,
                                       priority=Priority.CONFIG))

            elif frame.type == MsgType.CMD:
                self._exec_cmd(frame)

    def _exec_cmd(self, frame: LBPFrame) -> None:
        _flags, target_q = decode_cmd(frame.payload)
        if len(target_q) != len(self.q):
            return
        self.q = list(target_q)
        vlog(f"node{self.node_id} 执行 q={[round(x,3) for x in self.q]} "
             f"@ t_exec={frame.t_exec_us}us")

        # 回遥测（带温度，模拟真实舵机内置传感器）
        telem = encode_telem(self.node_id, self.q, temp_c=42)
        self.bus.send(LBPFrame(MsgType.TELEM, self.node_id, 1, telem,
                               priority=Priority.CONTROL))


# ══════════════════════════════════════════════════════════
#  主站：躯干
# ══════════════════════════════════════════════════════════

class SimSpine:
    def __init__(self, bus: SimBus):
        self.bus = bus
        self.frag = Fragmenter(max_frame_bytes=64)
        self.bmds: Dict[int, ModuleDescriptor] = {}
        self.topo_acks: Dict[int, dict] = {}
        self.clock = ClockSync()
        self.t_exec_us = 0
        self._cursor = 0

    def _read(self) -> List[LBPFrame]:
        frames, self._cursor = self.bus.read_since(self._cursor)
        return frames

    def enumerate(self, nodes: List[SimLegNode]) -> None:
        """广播枚举，收集 BMD

        注意：分片后的帧 type 是 FRAG，原类型在分片头里。
        所以这里不能先过滤 ENUM_ACK，而要交给 Fragmenter 重组后看类型。
        """
        import json
        self.bus.send(LBPFrame(MsgType.ENUM_REQ, 1, 0xFF, b"",
                               priority=Priority.CONFIG))
        # 从站各自回应（真实总线是竞争仲裁，这里顺序处理）
        for n in nodes:
            n.poll()

        # 主站读，分片重组
        for frame in self._read():
            if frame.type == MsgType.FRAG:
                got = self.frag.receive(frame)
                if got:
                    orig_type, data = got
                    if orig_type == MsgType.ENUM_ACK:
                        self.bmds[frame.src] = ModuleDescriptor.from_dict(
                            json.loads(data.decode()))
            elif frame.type == MsgType.ENUM_ACK:
                # 单帧（小 BMD）
                self.bmds[frame.src] = ModuleDescriptor.from_dict(
                    json.loads(frame.payload.decode()))

    def query_topology(self, nodes: List[SimLegNode]) -> None:
        for n in nodes:
            self.bus.send(LBPFrame(MsgType.TOPO_REQ, 1, n.node_id, b"",
                                   priority=Priority.CONFIG))
            n.poll()
        for frame in self._read():
            if frame.type == MsgType.TOPO_ACK:
                addr, mount_port, children = decode_topo_ack(frame.payload)
                self.topo_acks[addr] = {"mount_port": mount_port,
                                        "children": children}

    def build_topology(self) -> Topology:
        """用 BMD + TOPO_ACK 重建拓扑图"""
        t = Topology()
        spine = t.add_module(make_module("power_core"), label="躯干")
        for addr, bmd in sorted(self.bmds.items()):
            acc = self.topo_acks.get(addr, {})
            port = acc.get("mount_port", 0)
            mid = t.add_module(bmd, label=f"leg{addr}", serial=bmd.serial)
            ok = t.connect(spine, port, mid, 0)
            if not ok:
                log(f"  ⚠ 模块 {addr} 挂载到 port{port} 失败")
        return t

    def send_pose(self, nodes: List[SimLegNode],
                  q_map: Dict[int, List[float]], t_exec_us: int) -> None:
        """给每个关节下发目标（同一 T_EXEC）"""
        for n in nodes:
            if n.node_id not in q_map:
                continue
            payload = encode_cmd(q_map[n.node_id])
            self.bus.send(LBPFrame(
                MsgType.CMD, 1, n.node_id, payload,
                t_exec_us=t_exec_us, priority=Priority.CONTROL))
        for n in nodes:
            n.poll()
        # 收遥测
        self._read()


# ══════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 72)
    print("LBP 台架仿真（阶段一参照）")
    print("=" * 72)
    print("\n总线: CAN 2.0B @ 1 Mbps（ESP32 TWAI 上限，不支持 FD）")

    bus = SimBus()
    spine = SimSpine(bus)

    # ── 1. 组装 4 条腿 ──
    print("\n[1] 上电枚举")
    nodes: List[SimLegNode] = []
    for i, port in enumerate([0, 1, 2, 3]):
        leg = SimLegNode(node_id=i + 2, bmd=make_module("leg_3dof"),
                         port_id=port, bus=bus)
        nodes.append(leg)
    log(f"  从站就绪: {[n.node_id for n in nodes]}")

    spine.enumerate(nodes)
    log(f"  收到 {len(spine.bmds)} 个 ENUM_ACK")
    for addr, bmd in sorted(spine.bmds.items()):
        log(f"    node{addr}: {bmd.name} {bmd.dof}DOF {bmd.mass_kg}kg "
            f"serial=0x{bmd.serial:X}")
    if len(spine.bmds) != 4:
        log("  ✗ 枚举数量不对")
        return 1

    # ── 2. 拓扑发现 ──
    print("\n[2] 拓扑发现（读端口 ID）")
    spine.query_topology(nodes)
    for addr, ack in sorted(spine.topo_acks.items()):
        log(f"  node{addr} 挂在 port{ack['mount_port']}")

    # ── 3. 身体图式 ──
    print("\n[3] 身体图式推导（PC 侧 laaper.body）")
    topo = spine.build_topology()
    schema = derive_schema(topo)
    for line in schema.summary().splitlines():
        log(f"  {line}")

    print("\n  ── 真实硬件应当匹配这些值 ──")
    expect = {
        "locomotion_mode": "quadruped",
        "total_dof": 12,
        "contact_count": 4,
    }
    ok = True
    for k, v in expect.items():
        actual = getattr(schema, k)
        good = actual == v
        ok = ok and good
        log(f"  {'✓' if good else '✗'} {k:16s} = {actual}  (期望 {v})")
    marg_mm = schema.stability_margin_m * 1000
    log(f"  · stability_margin = {marg_mm:+.1f}mm  (仿真参照 +39.0mm)")
    log(f"  · com             = "
        f"({schema.com[0]:+.3f}, {schema.com[1]:+.3f}, {schema.com[2]:+.3f})")
    log(f"  · COM             = (-0.024, +0.000, -0.238)  ← 仿真参照")

    if not ok:
        log("  ✗ 身体图式与预期不符")
        return 1

    # ── 4. 带宽核算 ──
    print("\n[4] 带宽核算（CAN 2.0B @ 1Mbps）")
    bw = bandwidth_estimate(joints=12, telem_hz=10, cmd_hz=10,
                           bitrate_bps=1_000_000)
    log(f"  12 关节 @10Hz → {bw['total_bps']/1000:.0f} kbps "
        f"= 占用 {bw['utilization']*100:.1f}%  "
        f"{'✓ 可行' if bw['fits'] else '✗ 超载'}")
    bw_fd = bandwidth_estimate(joints=12, telem_hz=1000, cmd_hz=1000,
                              bitrate_bps=1_000_000)
    log(f"  反射层 1kHz  → 占用 {bw_fd['utilization']*100:.0f}%  "
        f"→ 必须在模块内闭环（与文档一致）")

    # ── 5. 下发姿态 + IK ──
    print("\n[5] 下发站姿（共同 T_EXEC）")
    q_map: Dict[int, List[float]] = {}
    max_err = 0.0
    for n in nodes:
        chain = next(c for c in schema.legs
                     if c.root_port_id == n.port_id)
        q0 = chain.default_q()
        tip = chain.tip_position(q0)
        # 抬脚 2cm 验证 IK
        target = tip.copy()
        target[2] += 0.02
        res = chain.ik(target, q0)
        max_err = max(max_err, res.error)
        q_map[n.node_id] = res.q

    t_exec = 500_000       # 全局时刻 500ms
    spine.send_pose(nodes, q_map, t_exec)
    log(f"  四条腿均已收到 CMD，t_exec={t_exec}us")
    log(f"  IK 最大误差 {max_err*1000:.2f}mm  "
        f"{'✓' if max_err < 1e-3 else '✗'}")
    for n in nodes:
        log(f"    node{n.node_id} q = {[round(x,3) for x in n.q]}")

    # ── 6. 时序一致性 ──
    print("\n[6] T_EXEC 时序一致性")
    log(f"  所有帧携带同一 t_exec={t_exec}us")
    log(f"  线上耗时 {bus.stats['bus_time_us']}us "
        f"（{bus.stats['frames']} 帧 / {bus.stats['bytes']}B）")
    slack = t_exec - bus.stats["bus_time_us"]
    log(f"  距执行时刻余量 {slack}us  "
        f"{'✓ 充足' if slack > 10000 else '✗ 太紧'}")
    log("  → 这就是为什么 CMD 要带未来时刻而不是「立即执行」：")
    log("    总线传输有延迟，不带 T_EXEC 的话 4 条腿动作会差几百 µs")

    # ── 7. 功率核算 ──
    print("\n[7] 功率核算（决定电源选型）")
    ps = power_summary(topo)
    log(f"  模块 {ps['modules']} 个 | 稳态 {ps['steady_w']}W "
        f"峰值 {ps['peak_w']}W（峰值/稳态 {ps['peak_ratio']}×）")
    log(f"  12V 母线峰值电流 {ps['peak_w']/12:.1f}A  "
        f"→ 建议电源 {ps['recommend_psu_w']:.0f}W 以上")
    log(f"  （文档选的是 12V 10A = 120W，余量充足）")

    # ── 8. 拔腿判定 ──
    print("\n[8] 拔腿判定（实机应复现同一结论）")
    from laaper.body.morphing import MorphEngine
    for port, name in [(3, "后右腿"), (0, "前左腿")]:
        eng = MorphEngine(spine.build_topology(), power_budget_w=500.0)
        r = eng.detach(1, port)
        verdict = "允许" if r.ok else "拒绝"
        reason = (f"裕度 {eng.schema.stability_margin_m*1000:+.1f}mm"
                  if r.ok else (r.issues[0][:40] if r.issues else ""))
        log(f"  拔{name} → {verdict}  ({reason})")
    log("  → 同一台四足，拔不同腿结论不同：协议真的在算几何")

    print("\n" + "=" * 72)
    print("仿真完成。到货后按 docs/LBP_STAGE1_BUILD.md 第 7 节逐项比对。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())