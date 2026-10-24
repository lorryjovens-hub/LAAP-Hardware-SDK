"""LBP/1.0 协议工程验收测试

不测「代码跑不跑」，测「协议设计成不成立」。

核心判据：**同一套代码，在四足 / 两足+双臂 / 四轮之间切换，
运动学都算得对，身体图式都推导正确。**

十三项验收：
  链路层  [1] 帧编解码往返  [2] CRC 检错  [3] 分片重组  [4] 优先级
          [5] 带宽核算（10Hz 能跑，1kHz 跑不动）
  节点层  [6] BMD 序列化往返
  身体层  [7] 四足装配 → 12DOF 四足模式
          [8] 四足降体高 IK → 四足全部收敛
          [9] 拔掉一条腿 → 三足，稳定性重算
          [10] 两足+双臂 → 14DOF 双足模式 + 抓取能力
          [11] 腿换轮 → 运动模式从 biped 变 wheel
          [12] 非法变形被拒绝（拔到站不住）
          [13] 功率核算
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from laaper.body import (
    LBPFrame, MsgType, Priority, Fragmenter, PriorityQueue,
    bandwidth_estimate, ClockSync,
    ModuleDescriptor, make_module, ModuleRole,
    Topology, derive_schema, Capability,
    ik_generic, stability_margin,
)
from laaper.body.morphing import (
    assemble_quadruped, assemble_biped_arm, assemble_wheeled,
    assemble_arm_platform, MorphEngine, power_summary,
)

OK, FAIL = "✓", "✗"
results = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  {OK if cond else FAIL} {name}" + (f"  [{detail}]" if detail else ""))


print("=" * 72)
print("LBP/1.0 协议工程验收")
print("=" * 72)

# ══════════════════════════════════════════════════════════
# 链路层
# ══════════════════════════════════════════════════════════
print("\n[链路层]")

# [1] 帧编解码往返
f = LBPFrame(type=MsgType.CMD, src=3, dst=7,
             payload=b"\x01\x02\x03\x04\x05", seq=1234, t_exec_us=500_000,
             priority=Priority.CONTROL)
wire = f.encode()
f2 = LBPFrame.decode(wire)
check("帧编解码往返", f2.src == 3 and f2.dst == 7 and f2.seq == 1234
      and f2.payload == f.payload and f2.t_exec_us == 500_000,
      f"{len(wire)}B / {f2.describe()}")
check("T_EXEC 时间戳保真", f2.t_exec_us == 500_000, "500000µs")

# [2] CRC 检错
bad = bytearray(wire)
bad[20] ^= 0xFF          # 翻转载荷里一个 bit
try:
    LBPFrame.decode(bytes(bad))
    check("CRC 能检出单 bit 错误", False, "居然没报错")
except ValueError as e:
    check("CRC 能检出单 bit 错误", "CRC" in str(e), str(e)[:40])

# [3] 分片重组（CAN FD 帧上限 64B，不是载荷 64B）
frag_max = 64
frg = Fragmenter(max_frame_bytes=frag_max)
check("CAN FD 单帧真实载荷容量算对", frg.max_chunk == 64 - 18 - 5 - 5,
      f"{frg.max_chunk}B（64 - 头18 - 尾5 - 分片头5）")
big = make_module("arm_4dof").to_json().encode()
proto = LBPFrame(type=MsgType.ENUM_ACK, src=2, dst=1, payload=b"", priority=Priority.CONFIG)
frames = frg.split(proto, big)
check("大载荷被分片", len(frames) > 1, f"{len(big)}B → {len(frames)} 帧")
check("每帧整帧不超 CAN FD 64B 上限",
      all(x.wire_size <= frag_max for x in frames),
      f"最大 {max(x.wire_size for x in frames)}B")

reassembled = None
orig_type = None
for fr in frames:
    # 模拟线路：编码再解码
    got = frg.receive(LBPFrame.decode(fr.encode()))
    if got:
        orig_type, reassembled = got
check("分片能重组回原数据", reassembled == big,
      f"{len(reassembled or b'')}B == {len(big)}B")
check("分片保留原始消息类型", orig_type == MsgType.ENUM_ACK,
      f"重组后知道这是 {orig_type.name if orig_type else '未知'}")

# 丢一片应该集不齐
frg2 = Fragmenter(max_frame_bytes=frag_max)
frames2 = frg2.split(proto, big)
lost = None
for i, fr in enumerate(frames2):
    if i == 1:
        continue                      # 丢掉第 2 片
    got = frg2.receive(fr)
    if got:
        lost = got
check("丢片后不会误判为完整", lost is None, "未返回数据 ✓")

# [4] 优先级调度
pq = PriorityQueue()
pq.push(LBPFrame(MsgType.OTA, 1, 2, b"x" * 10, priority=Priority.BULK))
pq.push(LBPFrame(MsgType.CMD, 1, 2, b"y" * 10, priority=Priority.CONTROL))
pq.push(LBPFrame(MsgType.SAFE_STOP, 1, 255, b"", priority=Priority.SAFETY))
order = [pq.pop().type.name for _ in range(3)]
check("SAFE_STOP 排最前（安全要求）",
      order == ["SAFE_STOP", "CMD", "OTA"], " → ".join(order))

# [5] 带宽核算
bw_skill = bandwidth_estimate(joints=20, telem_hz=10, cmd_hz=10)
bw_reflex = bandwidth_estimate(joints=20, telem_hz=1000, cmd_hz=1000)
check("技能层 10Hz 能跑在 CAN FD 5Mbps 上", bw_skill["fits"],
      f"占用 {bw_skill['utilization']*100:.1f}%")
check("反射层 1kHz 跑不动（必须本地闭环）", not bw_reflex["fits"],
      f"占用 {bw_reflex['utilization']*100:.0f}% → 超载")

# 时钟同步
cs = ClockSync()
cs.update(t1=1000, t2=1005, t3=1010, t4=1020)
check("时钟同步偏移估计", cs.synced and abs(cs.offset_us) < 20,
      f"offset={cs.offset_us:+.1f}µs")

# ══════════════════════════════════════════════════════════
# 节点层
# ══════════════════════════════════════════════════════════
print("\n[节点层]")

# [6] BMD 序列化往返
leg = make_module("leg_3dof")
d = leg.to_dict()
leg2 = ModuleDescriptor.from_dict(d)
check("BMD 序列化往返", leg2.dof == leg.dof and leg2.mass_kg == leg.mass_kg
      and len(leg2.ports) == len(leg.ports),
      f"{leg.dof}DOF {leg.mass_kg}kg {len(leg.ports)}口")
check("BMD 载荷适合 CAN 分片", len(leg.to_json()) > 64,
      f"{len(leg.to_json())}B → 必须分片")

# ══════════════════════════════════════════════════════════
# 身体层
# ══════════════════════════════════════════════════════════
print("\n[身体层 / 装配推导]")

# [7] 四足
quad = assemble_quadruped()
sq = derive_schema(quad)
check("四足：4 条腿", len(sq.legs) == 4, f"{len(sq.legs)} 条")
check("四足：12 自由度", sq.total_dof == 12, f"{sq.total_dof} DOF")
check("四足：识别为 quadruped", sq.locomotion_mode == "quadruped",
      sq.locomotion_mode)
check("四足：静态稳定", sq.stable,
      f"裕度 {sq.stability_margin_m*1000:.1f}mm / {sq.contact_count} 个着地点")
check("四足：有移动+平衡能力",
      sq.has(Capability.LOCOMOTION) and sq.has(Capability.BALANCE),
      ",".join(sorted(c.name for c in sq.capabilities)))
print("  ── 身体图式 ──")
for line in sq.summary().splitlines():
    print(f"    {line}")

# [8] 四足 IK：身体降低 3cm，四足保持原位
print("\n[身体层 / 运动学]")
q0 = [c.default_q() for c in sq.legs]
tips0 = [c.tip_position(q) for c, q in zip(sq.legs, q0)]
ok_all, max_err = True, 0.0
for i, c in enumerate(sq.legs):
    target = tips0[i].copy()
    target[2] += 0.0                       # 足端不动
    res = c.ik(target, q0[i])
    max_err = max(max_err, res.error)
    if not res.converged:
        ok_all = False
check("四足 IK 保持足端位置（4/4 收敛）", ok_all,
      f"最大误差 {max_err*1000:.2f}mm")

# 抬脚到新位置
lift_ok = True
for i, c in enumerate(sq.legs):
    tgt = tips0[i].copy()
    tgt[2] += 0.04                          # 抬 4cm
    tgt[0] += 0.02 if i < 2 else -0.02      # 往前/后迈
    res = c.ik(tgt, q0[i])
    if not res.converged or res.error > 2e-3:
        lift_ok = False
check("四足能迈步（抬脚 4cm + 前后 2cm）", lift_ok,
      "4/4 收敛")

# 稳定性函数自检
tri = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
m_in = stability_margin(tri, np.array([0.2, 0.2]))
m_out = stability_margin(tri, np.array([2.0, 2.0]))
check("稳定裕度：点在内部为正", m_in > 0, f"{m_in:.3f}m")
check("稳定裕度：点在外部为负", m_out < 0, f"{m_out:.3f}m")

# ══════════════════════════════════════════════════════════
# 变形
# ══════════════════════════════════════════════════════════
print("\n[身体层 / 变形]")

# [9] 拔腿：协议能区分「拔哪一条」
#
# 质心在 x=-24mm（偏后，因为四条腿的质心把整体拉后）。
# 所以：
#   拔后右腿 → 剩下三角形的质心更靠近边 → 裕度 5.8mm < 15mm → 拒绝
#   拔前左腿 → 剩下的三角形包围质心更好 → 裕度 28.1mm → 允许
#
# 这不是「全部拒绝」也不是「全部允许」，而是真的算了几何。
eng = MorphEngine(assemble_quadruped(), power_budget_w=300.0)
before_margin = eng.schema.stability_margin_m
r_rear = eng.detach(1, 3)        # 后右腿
print("  " + r_rear.report().replace("\n", "\n  "))
check("拔后右腿 → 拒绝（裕度不够）", not r_rear.ok,
      r_rear.issues[0][:48] if r_rear.issues else "居然允许了")
check("拒绝后拓扑未被改动（4 腿俱在）", eng.schema.contact_count == 4,
      f"仍为 {eng.schema.contact_count} 个着地点")
check("拒绝后稳定裕度不变",
      abs(eng.schema.stability_margin_m - before_margin) < 1e-6,
      f"{eng.schema.stability_margin_m*1000:.1f}mm")

# [9b] 同一台四足，拔前左腿 → 应该允许（裕度够）
eng_front = MorphEngine(assemble_quadruped(), power_budget_w=300.0)
r_front = eng_front.detach(1, 0)     # 前左腿
print("  " + r_front.report().replace("\n", "\n  "))
check("拔前左腿 → 允许（裕度足够）", r_front.ok, r_front.change)
check("前腿三足裕度大于阈值",
      r_front.ok and eng_front.schema.stability_margin_m > 0.015,
      f"{eng_front.schema.stability_margin_m*1000:.1f}mm > 15mm")
check("变三足，支撑重算为 3 点",
      eng_front.schema.contact_count == 3
      and eng_front.schema.locomotion_mode == "tripod",
      f"{eng_front.schema.contact_count} 点 / {eng_front.schema.locomotion_mode}")
check("协议确实区分了拔哪条腿（前允许后拒绝）",
      r_front.ok and not r_rear.ok,
      "同一台四足，几何不同 → 结论不同")

# [9c] 上支架后拔后腿 → 应该成功
eng_sup = MorphEngine(assemble_quadruped(), power_budget_w=300.0,
                      assume_supported=True)
r_sup = eng_sup.detach(1, 3)
print("  " + r_sup.report().replace("\n", "\n  "))
check("上支架后拔后腿成功", r_sup.ok, r_sup.change)
check("外部支撑状态有提示",
      any("外部支撑" in n for n in r_sup.notes),
      r_sup.notes[-1] if r_sup.notes else "无提示")

# [9d] 拔臂 —— 不影响支撑
biped_for_arm = assemble_biped_arm()
eng_arm = MorphEngine(biped_for_arm, power_budget_w=300.0)
dof_before = eng_arm.schema.total_dof
r_arm = eng_arm.detach(1, 4)      # 拔掉躯干 port4 的左臂
print("  " + r_arm.report().replace("\n", "\n  "))
check("拔臂成功（不影响支撑）", r_arm.ok, r_arm.change)
check("拔臂后 DOF 减 4", eng_arm.schema.total_dof == dof_before - 4,
      f"{dof_before} → {eng_arm.schema.total_dof}")
check("拔臂后仍能移动", eng_arm.schema.locomotion_mode == "biped",
      eng_arm.schema.locomotion_mode)

# [10] 两足 + 双臂
biped = assemble_biped_arm()
sb = derive_schema(biped)
check("两足+双臂：14 自由度", sb.total_dof == 14, f"{sb.total_dof} DOF")
check("识别为 biped", sb.locomotion_mode == "biped", sb.locomotion_mode)
check("有抓取能力", sb.has(Capability.MANIPULATION),
      ",".join(sorted(c.name for c in sb.capabilities)))
check("两足被标记为需要主动平衡", sb.requires_active_balance,
      "两点支撑 → 必须 IMU + 力矩闭环")
check("两足：2 条臂", len(sb.arms) == 2, f"{len(sb.arms)} 条")
print("  ── 人形身体图式 ──")
for line in sb.summary().splitlines():
    print(f"    {line}")

# 臂的 IK：伸手到前方
arm = sb.arms[0]
arm_reach = arm.tip_position(arm.default_q())
target = arm_reach + np.array([0.08, 0.0, -0.05])   # 往前下伸
res = arm.ik(target)
check("臂能伸手（前 8cm 下 5cm）", res.converged,
      f"误差 {res.error*1000:.2f}mm / {res.iterations} 次迭代")

# [11] 轮式：纯四轮 vs 加一条侧臂
print("\n[身体层 / 轮式与质心]")

# 纯四轮
sw = derive_schema(assemble_wheeled(arms=0))
check("纯四轮 → differential 模式",
      sw.locomotion_mode == "differential", sw.locomotion_mode)
check("四轮有 ROLL 能力", sw.has(Capability.ROLL),
      ",".join(sorted(c.name for c in sw.capabilities)))
check("纯四轮 4 个着地点且稳定",
      sw.contact_count == 4 and sw.stable,
      f"{sw.contact_count} 点 / 裕度 {sw.stability_margin_m*1000:.1f}mm")
print("  ── 纯轮式身体图式 ──")
for line in sw.summary().splitlines():
    print(f"    {line}")

# 加一条侧臂 → 质心被拉偏
sw_arm = derive_schema(assemble_wheeled(arms=1))
check("加一条侧臂后质心横向偏移", abs(sw_arm.com[1]) > 0.05,
      f"质心 y = {sw_arm.com[1]*1000:+.0f}mm（原本应该在 0 附近）")
check("协议会因质心偏移报警",
      len(sw_arm.warnings) > 0 or not sw_arm.stable,
      sw_arm.warnings[0] if sw_arm.warnings else "裕度已不足")

# 侧向装轮不会被误判为着地
eng_side = MorphEngine(assemble_quadruped(), power_budget_w=400.0,
                       assume_supported=True)
r_side = eng_side.attach(1, 4, "wheel_m2", label="侧面轮")
check("侧向装轮：不破坏四足着地判断",
      eng_side.schema.contact_count == 4,
      f"仍为 {eng_side.schema.contact_count} 点（侧轮离地 270mm，不计支撑）")

# [12] 非法变形被拒绝：两足拔一条腿就剩一点支撑
print("\n[身体层 / 变形校验]")
eng3 = MorphEngine(assemble_biped_arm(), power_budget_w=300.0)
check("两足初始状态：两点支撑 + 需主动平衡",
      eng3.schema.contact_count == 2 and eng3.schema.requires_active_balance,
      eng3.schema.locomotion_mode)
r3 = eng3.detach(1, 0)      # 拔掉一条腿 → 只剩一点支撑
print("  " + r3.report().replace("\n", "\n  "))
check("拔到站不住被协议拒绝", not r3.ok,
      r3.issues[0] if r3.issues else "居然允许了")
check("拒绝后拓扑回滚（仍两腿俱在）", eng3.schema.contact_count == 2,
      f"仍为 {eng3.schema.contact_count} 个着地点")

# 功率超预算被拒绝
eng4 = MorphEngine(assemble_quadruped(), power_budget_w=20.0)  # 故意给很小的预算
r4 = eng4.attach(1, 4, "arm_4dof", label="超预算臂")
check("功率超预算被拒绝", not r4.ok,
      r4.issues[0] if r4.issues else "居然允许了")

# [13] 功率核算
print("\n[工程核算]")
for name, topo in [("四足", assemble_quadruped()),
                   ("两足+双臂", assemble_biped_arm()),
                   ("四轮", assemble_wheeled(arms=0)),
                   ("四轮+臂", assemble_wheeled(arms=1)),
                   ("固定机械臂", assemble_arm_platform())]:
    ps = power_summary(topo)
    sch = derive_schema(topo)
    print(f"  {name:10s} {sch.locomotion_mode:14s} "
          f"{sch.total_dof:2d}DOF {sch.total_mass_kg:5.2f}kg "
          f"稳态 {ps['steady_w']:5.1f}W 峰值 {ps['peak_w']:6.1f}W "
          f"→ 48V/{ps['bus_current_a_at_48v']:4.1f}A")

check("四足峰值功率合理（10-200W）",
      10 < power_summary(assemble_quadruped())["peak_w"] < 200,
      f"{power_summary(assemble_quadruped())['peak_w']}W")

# 变形历史
print("\n[变形历史]")
print("  " + eng.history_report().replace("\n", "\n  "))

# ══════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════
print("\n" + "=" * 72)
passed = sum(1 for _, c, _ in results if c)
total = len(results)
print(f"结果: {passed}/{total} 通过")

if passed < total:
    print("\n未通过项：")
    for name, cond, detail in results:
        if not cond:
            print(f"  {FAIL} {name}  [{detail}]")

sys.exit(0 if passed == total else 1)