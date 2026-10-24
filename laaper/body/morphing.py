"""变形（Morphing）— 装配、重配置、身体图式比对

## 这一层证明协议设计成立

判断标准只有一条：**同一套代码，在「四足」和「两足+双臂」之间切换，
运动学都算得对。** 如果做不到，协议设计就是空话。

## 变形的三个阶段（协议层能保证的）

1. **发现**：拔插后 TOPO_REQ/ACK 重建拓扑图
2. **推导**：derive_schema 重新算自由度/质心/支撑多边形/能力
3. **校验**：功率够不够、会不会倒、剩余链是否还能保持姿态

第 3 步是关键 —— 变形不能把机器人变倒。协议必须在动作之前
就告诉你"这么插会不稳"，而不是插上去之后摔一跤。

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from .module import Capability, make_module
from .topology import BodySchema, KinematicChain, Topology, derive_schema


# ══════════════════════════════════════════════════════════
#  标准装配
# ══════════════════════════════════════════════════════════

def assemble_quadruped() -> Topology:
    """四足：躯干 + 4 条腿（底面四角）"""
    t = Topology()
    body = t.add_module(make_module("power_core"), label="躯干")
    for port, name in [(0, "前左腿"), (1, "前右腿"), (2, "后左腿"), (3, "后右腿")]:
        leg = t.add_module(make_module("leg_3dof"), label=name)
        t.connect(body, port, leg, 0)
    return t


def assemble_biped_arm(head: bool = True) -> Topology:
    """两足 + 双臂（人形基础）"""
    t = Topology()
    body = t.add_module(make_module("power_core"), label="躯干")
    # 底面只有前两个口装腿
    for port, name in [(0, "左腿"), (1, "右腿")]:
        leg = t.add_module(make_module("leg_3dof"), label=name)
        t.connect(body, port, leg, 0)
    # 两侧装臂
    for port, name in [(4, "左臂"), (5, "右臂")]:
        arm = t.add_module(make_module("arm_4dof"), label=name)
        t.connect(body, port, arm, 0)
    return t


def assemble_wheeled(arms: int = 1) -> Topology:
    """四轮 + 可选臂"""
    t = Topology()
    body = t.add_module(make_module("power_core"), label="躯干")
    for port, name in [(0, "前左轮"), (1, "前右轮"), (2, "后左轮"), (3, "后右轮")]:
        w = t.add_module(make_module("wheel_m2"), label=name)
        t.connect(body, port, w, 0)
    for i in range(min(arms, 2)):
        port = 4 if i == 0 else 5
        arm = t.add_module(make_module("arm_4dof"), label=f"臂{i+1}")
        t.connect(body, port, arm, 0)
    return t


def assemble_arm_platform() -> Topology:
    """固定机械臂平台（无移动能力）"""
    t = Topology()
    body = t.add_module(make_module("power_core"), label="底座")
    arm = t.add_module(make_module("arm_4dof"), label="机械臂")
    t.connect(body, 4, arm, 0)
    gripper = t.add_module(make_module("gripper"), label="夹爪")
    t.connect(arm, 0, gripper, 0)
    return t


# ══════════════════════════════════════════════════════════
#  变形
# ══════════════════════════════════════════════════════════

@dataclass
class MorphResult:
    """一次变形的结果"""
    ok: bool
    change: str
    before: Optional[BodySchema] = None
    after: Optional[BodySchema] = None
    issues: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def delta(self) -> dict:
        if not (self.before and self.after):
            return {}
        b, a = self.before, self.after

        def marg(s):
            m = s.stability_margin_m
            # -inf（两点支撑）时不做差值，否则会出 nan
            return m if math.isfinite(m) else None

        bm, am = marg(b), marg(a)
        dm = (round((am - bm) * 1000, 1)
              if (bm is not None and am is not None) else None)

        return {
            "dof": a.total_dof - b.total_dof,
            "mass_kg": round(a.total_mass_kg - b.total_mass_kg, 3),
            "mode": f"{b.locomotion_mode} → {a.locomotion_mode}",
            "margin_mm": dm,
            "cap_added": sorted(c.name for c in (a.capabilities - b.capabilities)),
            "cap_lost": sorted(c.name for c in (b.capabilities - a.capabilities)),
        }

    def report(self) -> str:
        lines = [f"{'✓' if self.ok else '✗'} {self.change}"]
        d = self.delta()
        if d:
            lines.append(
                f"  DOF {d['dof']:+d} | 质量 {d['mass_kg']:+.2f}kg | "
                f"模式 {d['mode']}")
            marg = f"{d['margin_mm']:+.1f}mm" if d["margin_mm"] is not None else "n/a"
            lines.append(
                f"  稳定裕度变化 {marg}"
                + (f" | 新增能力 {','.join(d['cap_added'])}" if d["cap_added"] else "")
                + (f" | 失去能力 {','.join(d['cap_lost'])}" if d["cap_lost"] else ""))
        for n in self.notes:
            lines.append(f"  · {n}")
        for i in self.issues:
            lines.append(f"  ⚠ {i}")
        return "\n".join(lines)


class MorphEngine:
    """变形引擎 —— 在协议层校验和推导

    用法：
        eng = MorphEngine(topo)
        r = eng.remove_module(leg_id)      # 拔掉一条腿
        print(r.report())
        if not r.ok:
            eng.rollback()                 # 协议层面拒绝这次变形
    """

    def __init__(self, topo: Topology, power_budget_w: float = 200.0,
                 min_margin_m: float = 0.015,
                 assume_supported: bool = False):
        """
        @param assume_supported
            是否假设机器人已被外部支撑（趴伏在地 / 上支架）。

            **这是真实换件的必要条件，不是偷懒的开关。**
            四足拆掉一条支撑腿，剩下三点支撑且质心偏移，
            物理上就是会倒。真实机器人换腿时必须先趴下或上支架。

            打开后跳过静态稳定性检查（因为重量已不由腿承担），
            但功率检查和“失去移动能力”检查仍然生效。
        """
        self.topo = topo
        self.power_budget_w = power_budget_w
        self.min_margin_m = min_margin_m
        self.assume_supported = assume_supported
        self.schema = derive_schema(topo)
        self._history: List[Tuple[str, BodySchema]] = [("初始", self.schema)]

    # ── 核心校验 ──
    def _validate(self, new_schema: BodySchema, action: str) -> List[str]:
        issues = []

        # 1. 功率预算
        if new_schema.peak_power_w > self.power_budget_w:
            issues.append(
                f"峰值功率 {new_schema.peak_power_w:.0f}W 超过母线预算 "
                f"{self.power_budget_w:.0f}W")

        was_mobile = self.schema.locomotion_mode not in (
            "immobile", "fixed_manipulator")
        is_mobile = new_schema.locomotion_mode not in (
            "immobile", "fixed_manipulator")

        # 2. 稳定性
        #
        # 三种情况分开处理：
        #   ≥3 点支撑：静态稳定，裕度不足就是真危险 → 硬拒
        #   2 点支撑：两足天生不稳定，靠主动平衡站住 → 只警告
        #   ≤1 点支撑：站不住 → 如果之前能走，硬拒
        if new_schema.contact_count >= 3 and is_mobile and not self.assume_supported:
            if new_schema.stability_margin_m < self.min_margin_m:
                issues.append(
                    f"稳定裕度 {new_schema.stability_margin_m*1000:.1f}mm "
                    f"低于阈值 {self.min_margin_m*1000:.0f}mm（会倒）"
                    f"；若已被外部支撑，请设置 assume_supported=True")
        elif new_schema.contact_count <= 1 and is_mobile and not self.assume_supported:
            issues.append(
                f"只有 {new_schema.contact_count} 个着地点，无法支撑身体"
                f"；若已被外部支撑，请设置 assume_supported=True")

        # 3. 完全失去移动能力
        if was_mobile and not is_mobile:
            issues.append("变形后完全失去移动能力")

        return issues

    def _apply(self, action: str, mutate) -> MorphResult:
        """执行一次变形：改拓扑 → 重推 → 校验 → 失败则回滚"""
        before = self.schema
        backup_modules = dict(self.topo.modules)
        backup_conns = list(self.topo.connections)
        backup_used = set(self.topo._ports_used)

        try:
            mutate()
            after = derive_schema(self.topo)
        except Exception as e:
            # 变形成了非法结构，回滚
            self.topo.modules = backup_modules
            self.topo.connections = backup_conns
            self.topo._ports_used = backup_used
            return MorphResult(False, action, before, before,
                               [f"拓扑变更失败: {e}"])

        issues = self._validate(after, action)
        hard_issues = [i for i in issues]

        if hard_issues:
            # 回滚 —— 协议层拒绝这次变形
            self.topo.modules = backup_modules
            self.topo.connections = backup_conns
            self.topo._ports_used = backup_used
            return MorphResult(False, action, before, after, hard_issues)

        self.schema = after
        self._history.append((action, after))
        notes = list(after.warnings)
        if self.assume_supported:
            notes.append("⚠ 本次变形在外部支撑状态下完成，完成后需重新校验能否自主站立")
        return MorphResult(True, action, before, after, [], notes)

    # ── 变形操作 ──

    def attach(self, parent: int, port: int, module_name: str,
               label: str = "") -> MorphResult:
        """插上一个模块"""
        def _do():
            mid = self.topo.add_module(make_module(module_name), label=label)
            if not self.topo.connect(parent, port, mid, 0):
                raise RuntimeError(f"端口 {port} 无法连接（已占用或不存在）")

        return self._apply(f"插上 {module_name}@{parent}.p{port}", _do)

    def detach(self, parent: int, port: int) -> MorphResult:
        """拔掉某个端口上的模块（含子树）"""
        victim = None
        for c in self.topo.connections:
            if c.parent == parent and c.parent_port == port:
                victim = self.topo.modules[c.child].label or self.topo.modules[c.child].desc.name
                break
        if victim is None:
            return MorphResult(False, f"拔掉 {parent}.p{port}", self.schema, self.schema,
                               ["该端口上没有模块"])

        def _do():
            if self.topo.disconnect(parent, port) is None:
                raise RuntimeError("断开失败")

        return self._apply(f"拔掉 {victim}@{parent}.p{port}", _do)

    def replace(self, parent: int, port: int, module_name: str,
                label: str = "") -> MorphResult:
        """换件：拔掉原模块，插上新模块"""
        def _do():
            self.topo.disconnect(parent, port)
            mid = self.topo.add_module(make_module(module_name), label=label)
            if not self.topo.connect(parent, port, mid, 0):
                raise RuntimeError("新模块连接失败")

        return self._apply(f"把 {parent}.p{port} 换成 {module_name}", _do)

    def rollback(self) -> MorphResult:
        """回退到上一次成功的变形"""
        if len(self._history) < 2:
            return MorphResult(False, "回退", self.schema, self.schema,
                               ["没有可回退的历史"])
        return MorphResult(False, "回退（未实现物理回退，需要重新装配）",
                           self.schema, self.schema, [])

    # ── 报告 ──
    def history_report(self) -> str:
        lines = ["变形历史:"]
        for i, (act, sch) in enumerate(self._history):
            lines.append(
                f"  {i}. {act:28s} → {sch.locomotion_mode:16s} "
                f"{sch.total_dof:2d}DOF {sch.total_mass_kg:.2f}kg")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
#  控制连续性校验
# ══════════════════════════════════════════════════════════

def check_control_continuity(before: BodySchema, after: BodySchema,
                             target_poses: Optional[Dict[str, np.ndarray]] = None,
                             tol_m: float = 0.01) -> List[str]:
    """变形后，还在的链能不能保持原来的末端位置？

    这是「热插拔不停机」的硬指标：
    拔掉一条腿的时候，其余三条腿的足端不能移位 ——
    否则身体会瞬间失去支撑。

    实现方式：对每条在变形前后都存在的链（按 role + 模块序列识别），
    用变形前的姿态解变形后的 IK，看末端误差。

    注意：真正的实现需要在拓扑变更时携带关节角度快照。
    这里给出校验框架，角度快照由调用方提供。
    """
    issues = []

    def chain_key(c: KinematicChain) -> str:
        return f"{c.role}:{'-'.join(map(str, c.module_ids))}"

    after_map = {chain_key(c): c for c in after.chains}

    for bc in before.chains:
        k = chain_key(bc)
        ac = after_map.get(k)
        if ac is None:
            continue        # 这条链被拆了，不要求保持

        if target_poses and k in target_poses:
            target = target_poses[k]
        else:
            # 用变形前的零位姿态末端位置作为目标
            target = bc.tip_position(bc.default_q())

        res = ac.ik(target)
        if not res.converged or res.error > tol_m:
            issues.append(
                f"{k} 变形后无法保持末端位置（误差 {res.error*1000:.1f}mm）")

    return issues


def power_summary(topo: Topology) -> dict:
    """功率核算 —— 决定母线和电池选型"""
    steady = sum(m.desc.power_mw for m in topo.modules.values()) / 1000.0
    peak = topo.peak_power_w()
    return {
        "modules": len(topo.modules),
        "steady_w": round(steady, 1),
        "peak_w": round(peak, 1),
        "peak_ratio": round(peak / steady, 2) if steady > 0 else 0,
        "bus_current_a_at_48v": round(peak / 48.0, 1),
        "recommend_psu_w": round(peak * 1.3, 0),      # 30% 余量
        "bus_capacitance_mf": round(peak / 48.0 * 2, 0),  # 粗估：2ms 掉压容限
    }