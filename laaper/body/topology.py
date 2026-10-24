"""LBP/1.0 身体层 — 拓扑、运动链、身体图式

## 这一层是「变形金刚」的全部秘密

USB 枚举把我插在哪个口上当成「端口号」，只是寻址信息。
LBP 的拓扑把我插在哪个口上当成**语义**：

    插在躯干底面四角  → 四条腿 → 我是四足
    插在躯干左右两侧  → 两条臂 → 我能抓东西
    底面两腿 + 两侧两臂 → 我是人形
    底面四轮          → 我是车

**协议不需要知道"我是四足"，它只要知道"谁接在哪个口上"，
身体图式是自动推导出来的。**

## 推导流程

```
拓扑图 → 找根 → DFS 建链 → 聚合关节/几何 → FK 算末端 → 分类
                                              ↓
                       质心 / 支撑多边形 / 稳定裕度 / 能力 / 运动模式
```

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from . import kinematics as kin
from .module import (Capability, JointSpec, ModuleClass, ModuleDescriptor,
                     ModuleRole, Port)
from .kinematics import port_frame, trans, rot4


# ══════════════════════════════════════════════════════════
#  拓扑元素
# ══════════════════════════════════════════════════════════

@dataclass
class ModuleInstance:
    """装到身体上的一个模块实例"""
    instance_id: int
    desc: ModuleDescriptor
    serial: int = 0
    label: str = ""

    def __post_init__(self):
        if not self.serial:
            self.serial = self.desc.serial

    def __str__(self) -> str:
        return f"#{self.instance_id}:{self.label or self.desc.name}"


@dataclass
class Connection:
    """一条物理连接：parent 的某端口 ↔ child 的某端口"""
    parent: int
    parent_port: int
    child: int
    child_port: int

    def __str__(self) -> str:
        return f"#{self.parent}.p{self.parent_port} ↔ #{self.child}.p{self.child_port}"


class Topology:
    """身体拓扑图

    物理上对应：谁插在谁的哪个口上。来自 LBP 的 TOPO_REQ/TOPO_ACK 交换。
    """

    def __init__(self):
        self.modules: Dict[int, ModuleInstance] = {}
        self.connections: List[Connection] = []
        self._next_id = 1
        self._ports_used: Set[Tuple[int, int]] = set()   # (module, port)

    # ── 装配 ──
    def add_module(self, desc: ModuleDescriptor, label: str = "",
                   serial: int = 0) -> int:
        mid = self._next_id
        self._next_id += 1
        self.modules[mid] = ModuleInstance(mid, desc, serial, label)
        return mid

    def connect(self, parent: int, parent_port: int,
                child: int, child_port: int = 0) -> bool:
        """接上。返回 False 表示端口已被占用或无此端口"""
        if parent not in self.modules or child not in self.modules:
            return False

        pport = self.modules[parent].desc.find_port(parent_port)
        if pport is None:
            return False
        # 子模块的对接口可以不指定是否存在（末端模块可能只有 1 个口）
        if child_port not in [p.pos_id for p in self.modules[child].desc.ports] \
                and self.modules[child].desc.ports:
            return False

        key = (parent, parent_port)
        if key in self._ports_used:
            return False       # 一个口只能接一个东西

        # 防环
        if self._would_cycle(parent, child):
            return False

        self._ports_used.add(key)
        self.connections.append(Connection(parent, parent_port, child, child_port))
        return True

    def disconnect(self, parent: int, parent_port: int) -> Optional[int]:
        """拔掉。返回被拔掉的子树所有实例 id（含子树）"""
        for i, c in enumerate(self.connections):
            if c.parent == parent and c.parent_port == parent_port:
                removed_root = c.child
                self.connections.pop(i)
                self._ports_used.discard((parent, parent_port))
                subtree = self.subtree_ids(removed_root)
                # 从拓扑里移除整棵子树
                for mid in subtree:
                    self.modules.pop(mid, None)
                self.connections = [
                    x for x in self.connections if x.child not in subtree
                ]
                self._ports_used = {
                    k for k in self._ports_used if k[0] not in subtree
                }
                return removed_root
        return None

    def _would_cycle(self, parent: int, child: int) -> bool:
        """把 child 挂到 parent 下会不会成环"""
        # 若 parent 已在 child 的子树里，则会成环
        return parent in self.subtree_ids(child)

    def subtree_ids(self, root: int) -> Set[int]:
        out = {root}
        stack = [root]
        while stack:
            cur = stack.pop()
            for c in self.connections:
                if c.parent == cur and c.child not in out:
                    out.add(c.child)
                    stack.append(c.child)
        return out

    # ── 查询 ──
    def children_of(self, mid: int) -> List[Tuple[Port, int, int]]:
        """返回 [(端口, 子实例 id, 子的对接口 id)]"""
        out = []
        for c in self.connections:
            if c.parent == mid:
                port = self.modules[mid].desc.find_port(c.parent_port)
                if port:
                    out.append((port, c.child, c.child_port))
        out.sort(key=lambda x: x[0].pos_id)
        return out

    def parent_of(self, mid: int) -> Optional[Tuple[int, int]]:
        for c in self.connections:
            if c.child == mid:
                return (c.parent, c.parent_port)
        return None

    def find_root(self) -> int:
        """找根：没有被挂的模块就是根。

        优先选 POWER/COMPUTE 类（那是躯干）。
        """
        attached = {c.child for c in self.connections}
        candidates = [m for m in self.modules if m not in attached]
        if not candidates:
            # 成环了（不该发生），退化为 id 最小的
            return min(self.modules) if self.modules else 0
        for m in candidates:
            if self.modules[m].desc.cls in (ModuleClass.POWER, ModuleClass.COMPUTE):
                return m
        return min(candidates)

    def free_ports(self) -> List[Tuple[int, Port]]:
        """还空着的端口 —— 变形时往哪插"""
        out = []
        for mid, inst in self.modules.items():
            for p in inst.desc.ports:
                if (mid, p.pos_id) not in self._ports_used:
                    out.append((mid, p))
        return out

    def total_mass(self) -> float:
        return sum(m.desc.mass_kg for m in self.modules.values())

    def peak_power_w(self) -> float:
        return sum(m.desc.power_peak_mw for m in self.modules.values()) / 1000.0


# ══════════════════════════════════════════════════════════
#  运动链
# ══════════════════════════════════════════════════════════

@dataclass
class ChainSegment:
    """链上的一段：一个模块 + 它的关节 + 接下一个模块的端口"""
    module_id: int
    joints: List[JointSpec]
    next_port_id: Optional[int] = None


@dataclass
class KinematicChain:
    """一条从躯干端口到末端的运动链"""
    role: str                       # leg / arm / wheel / head / voice / other
    segments: List[ChainSegment]
    base_T: np.ndarray              # 躯干端口坐标系
    port_map: Dict[Tuple[int, int], Port] = field(default_factory=dict)
    root_port_id: int = 0
    root_port_label: str = ""

    # ── 派生属性 ──
    @property
    def joints(self) -> List[JointSpec]:
        return [j for s in self.segments for j in s.joints]

    @property
    def dof(self) -> int:
        return len(self.joints)

    @property
    def module_ids(self) -> List[int]:
        return [s.module_id for s in self.segments]

    @property
    def tip_module(self) -> int:
        return self.segments[-1].module_id

    @property
    def is_ground_contact(self) -> bool:
        return self.role in ("leg", "wheel")

    def fk(self, q: Sequence[float]) -> Tuple[np.ndarray, List[Tuple[int, np.ndarray]]]:
        """整条链的 FK

        @return (末端 T, [(模块 id, 该模块末端 T), ...])
        """
        T = self.base_T.copy()
        qi = 0
        module_ends: List[Tuple[int, np.ndarray]] = []

        for si, seg in enumerate(self.segments):
            for j in seg.joints:
                T = T @ trans(j.offset)
                T = T @ rot4(j.axis, q[qi] if qi < len(q) else 0.0)
                T = T @ trans(j.link)
                qi += 1
            module_ends.append((seg.module_id, T.copy()))

            # 接下一段：过端口坐标系
            if si < len(self.segments) - 1 and seg.next_port_id is not None:
                nxt = self.segments[si + 1]
                parent_desc_T = T
                # 端口定义在「本模块的局部系」里，而 T 已经到本模块末端（含关节旋转）
                # 端口随本模块一起动，所以直接用 T @ port_frame
                port = self._port_of(seg.module_id, seg.next_port_id)
                if port is not None:
                    T = parent_desc_T @ port_frame(port)

        return T, module_ends

    def _port_of(self, module_id: int, port_id: int) -> Optional[Port]:
        return self.port_map.get((module_id, port_id))

    def tip_position(self, q: Sequence[float]) -> np.ndarray:
        T, _ = self.fk(q)
        return T[:3, 3]

    def default_q(self) -> List[float]:
        """默认站姿

        腿的默认值不是拍脑袋的：
          髋偏仰 +20°，膝 -40° → 足端几乎正好在髀关节正下方，
          且膝盖有弯曲（不是死直）
        推导：大腿 90mm、小腿 100mm，θ1=20° θ2=-40° 时
          水平位移 = 90·sin20° + 100·sin(-20°) = 30.8 - 34.2 = -3.4mm ≈ 0
          垂直下沉 = 90·cos20° + 100·cos20° = 178.6mm

        如果两条腿长度差很大，这个补偿就不准了 —— 但真实机器人
        的脚一般就是按等长连杆设计的。
        """
        out = []
        for j in self.joints:
            n = j.name.lower()
            if n == "hip_pitch":
                out.append(j.clamp(math.radians(20)))
            elif n == "knee":
                out.append(j.clamp(math.radians(-40)))
            elif "elbow" in n:
                out.append(j.clamp(j.min_rad * 0.4))
            elif "knee" in n:
                out.append(j.clamp(j.min_rad * 0.45))
            else:
                out.append(j.clamp(0.0))
        return out

    def ik(self, target: np.ndarray, q0: Optional[Sequence[float]] = None,
           **kw) -> kin.IKResult:
        """逆解到世界坐标 target"""
        q0 = list(q0) if q0 is not None else self.default_q()
        joints = self.joints
        lo = np.array([j.min_rad for j in joints])
        hi = np.array([j.max_rad for j in joints])

        def fk_pos(q):
            return self.tip_position(q)

        return kin.ik_generic(fk_pos, q0, target, lo, hi, **kw)


# ══════════════════════════════════════════════════════════
#  身体图式
# ══════════════════════════════════════════════════════════

@dataclass
class BodySchema:
    """当前身体是什么 —— 协议层对「我」的客观描述"""
    chains: List[KinematicChain] = field(default_factory=list)
    total_dof: int = 0
    total_mass_kg: float = 0.0
    com: np.ndarray = field(default_factory=lambda: np.zeros(3))
    support_polygon: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    stability_margin_m: float = 0.0
    stable: bool = False
    capabilities: Set[Capability] = field(default_factory=set)
    locomotion_mode: str = "none"
    peak_power_w: float = 0.0
    root_id: int = 0
    contact_count: int = 0                 # 着地点个数
    requires_active_balance: bool = False  # 是否必须主动平衡（两足/单足）
    warnings: List[str] = field(default_factory=list)

    # ── 便捷查询 ──
    @property
    def legs(self) -> List[KinematicChain]:
        return [c for c in self.chains if c.role == "leg"]

    @property
    def arms(self) -> List[KinematicChain]:
        return [c for c in self.chains if c.role == "arm"]

    @property
    def wheels(self) -> List[KinematicChain]:
        return [c for c in self.chains if c.role == "wheel"]

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities

    def chain_by_role(self, role: str) -> List[KinematicChain]:
        return [c for c in self.chains if c.role == role]

    def summary(self) -> str:
        roles: Dict[str, int] = {}
        for c in self.chains:
            roles[c.role] = roles.get(c.role, 0) + 1

        parts = [f"{n}×{r}" for r, n in sorted(roles.items())]
        caps = ",".join(sorted(c.name for c in self.capabilities)) or "-"

        lines = [
            f"身体: {' + '.join(parts) if parts else '空'}",
            f"自由度 {self.total_dof} | 质量 {self.total_mass_kg:.2f}kg | "
            f"峰值功率 {self.peak_power_w:.0f}W",
            f"运动模式: {self.locomotion_mode}",
            f"能力: {caps}",
            f"质心 ({self.com[0]:+.3f}, {self.com[1]:+.3f}, {self.com[2]:+.3f})",
            f"着地点 {self.contact_count} 个 | 稳定裕度 "
            f"{self.stability_margin_m*1000:+.1f}mm "
            f"({'稳定' if self.stable else ('需主动平衡' if self.requires_active_balance else '⚠ 不稳')})",
        ]
        if self.warnings:
            lines += [f"⚠ {w}" for w in self.warnings]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
#  推导
# ══════════════════════════════════════════════════════════

def _classify_chain(segments: List[ChainSegment],
                    topo: Topology) -> str:
    """判断这条链是什么角色

    优先看模块角色和能力，其次看模块名。
    这个分类是「语义」的，物理上不对应任何东西 —— 所以它必须能从
    BMD 推出来，不能硬编码。
    """
    descs = [topo.modules[s.module_id].desc for s in segments]
    roles = [d.role for d in descs]

    if ModuleRole.WHEEL in roles:
        return "wheel"
    if ModuleRole.EYE in roles:
        return "head"
    if ModuleRole.VOICE in roles:
        return "voice"

    names = " ".join(d.name for d in descs)
    if "leg" in names:
        return "leg"
    if "arm" in names:
        return "arm"
    if ModuleRole.LIMB in roles:
        return "limb"
    if ModuleRole.END_EFFECTOR in roles:
        return "end_effector"
    return "other"


def _is_ground_contact(chain: KinematicChain, tip_z: float,
                       ground_z: float, tol_limb: float = 0.04,
                       tol_other: float = 0.02) -> bool:
    """这条链的末端算不算着地点

    ## 为什么不能只看角色

    轮子模块如果装在**侧向端口**上，它的末端在 z=+0.02，
    比足端高 27cm —— 几何上根本不可能着地。

    早期版本写了「role 是 wheel 就算着地」，结果四足侧面插两个轮
    也会被当成 6 点支撑，算出一个假稳定的身体图式。
    这种错误在真机上就是「以为能站，结果一松手就倒」。

    所以：角色只是必要条件，**z 坐标才是充分条件**。
    肢/轮容差 40mm（悬空抬起的脚也算半接触），其它部件 20mm。
    """
    tol = tol_limb if chain.role in ("leg", "wheel") else tol_other
    return tip_z <= ground_z + tol


def derive_schema(topo: Topology,
                  ground_tol: float = 0.02,
                  com_from_pose: bool = True) -> BodySchema:
    """从拓扑推导身体图式

    这是整个 LBP 身体层的核心函数：输入「谁插在哪个口上」，
    输出「我现在是什么生物、能动多少、会不会倒」。
    """
    schema = BodySchema()
    if not topo.modules:
        return schema

    root = topo.find_root()
    schema.root_id = root
    schema.total_mass_kg = topo.total_mass()
    schema.peak_power_w = topo.peak_power_w()

    # ── 1. DFS 建链 ──
    #
    # 重要：每条链必须用独立的 ChainSegment 对象。
    # 如果共享同一个 seg 对象，一个模块有多个子端口时，
    # next_port_id 会被后面的分支覆盖，先建好的链也跟着变 → FK 算错。
    chains: List[KinematicChain] = []

    def walk(module_id: int, base_T: np.ndarray, root_port: Optional[Port],
             path: List[Tuple[int, List[JointSpec], Optional[int]]]):
        """path 里每项 = (模块 id, 关节表, 接下一个的口)；None 表示末端

        用元组而不是对象，就是为了避免共享可变状态。
        """
        children = topo.children_of(module_id)
        desc = topo.modules[module_id].desc

        if not children:
            full = path + [(module_id, list(desc.joints), None)]
            _finish(full, base_T, root_port)
            return

        for port, child_id, _child_port in children:
            here = path + [(module_id, list(desc.joints), port.pos_id)]
            walk(child_id, base_T, root_port, here)

    def _finish(path, base_T, root_port):
        segs = [ChainSegment(module_id=m, joints=list(j), next_port_id=nxt_port)
                for m, j, nxt_port in path]
        role = _classify_chain(segs, topo)
        pmap: Dict[Tuple[int, int], Port] = {}
        for m, _, _ in path:
            for p in topo.modules[m].desc.ports:
                pmap[(m, p.pos_id)] = p
        chains.append(KinematicChain(
            role=role,
            segments=segs,
            base_T=base_T,
            port_map=pmap,
            root_port_id=root_port.pos_id if root_port else 0,
            root_port_label=root_port.label if root_port else "",
        ))

    root_children = topo.children_of(root)
    if not root_children:
        # 只有躯干（或躯干自己带关节）
        seg = ChainSegment(root, list(topo.modules[root].desc.joints))
        pmap = {(root, p.pos_id): p for p in topo.modules[root].desc.ports}
        chains.append(KinematicChain(role="other", segments=[seg],
                                    base_T=np.eye(4), port_map=pmap))
    else:
        for port, child_id, _ in root_children:
            walk(child_id, port_frame(port), port, [])

    schema.chains = chains
    schema.total_dof = sum(c.dof for c in chains)

    # ── 2. 各链末端（零位姿态）──
    tips: List[np.ndarray] = []
    chain_qs: List[List[float]] = []
    for c in chains:
        q = c.default_q()
        chain_qs.append(q)
        tips.append(c.tip_position(q))

    if tips:
        tip_arr = np.array(tips)
        ground_z = float(tip_arr[:, 2].min())
    else:
        ground_z = 0.0

    # ── 3. 支撑多边形 ──
    contacts = []
    for c, tip in zip(chains, tips):
        if _is_ground_contact(c, tip[2], ground_z):
            contacts.append(tip[:2])
    # 同名足端去重（比如腿和轮重叠）
    uniq = {}
    for p in contacts:
        uniq[(round(p[0], 4), round(p[1], 4))] = p
    contacts = list(uniq.values())
    schema.contact_count = len(contacts)

    if len(contacts) >= 3:
        schema.support_polygon = kin.convex_hull_2d(np.array(contacts))
    elif len(contacts) >= 1:
        schema.support_polygon = np.array(contacts)     # 退化：线段或点
    else:
        schema.support_polygon = np.zeros((0, 2))

    # ── 4. 质心 ──
    com = np.zeros(3)
    msum = 0.0
    for c, q in zip(chains, chain_qs):
        _, module_ends = c.fk(q)
        for mid, T in module_ends:
            d = topo.modules[mid].desc
            # 模块质心随该模块末端坐标系一起动（近似：刚性附着）
            p_local = np.array([*d.com_offset, 1.0])
            p_world = (T @ p_local)[:3]
            com += p_world * d.mass_kg
            msum += d.mass_kg
    # 根模块质心
    root_desc = topo.modules[root].desc
    com += np.array([*root_desc.com_offset,]) * root_desc.mass_kg
    msum += root_desc.mass_kg

    schema.com = com / msum if msum > 0 else com

    # ── 5. 稳定性 ──
    if len(schema.support_polygon) >= 3:
        margin = kin.stability_margin(schema.support_polygon, schema.com[:2])
        schema.stability_margin_m = margin
        schema.stable = margin > 0.015
        schema.requires_active_balance = False
    elif schema.contact_count == 2:
        # 两足：平凡上就不稳定，靠主动平衡（动量控制）站着
        schema.stability_margin_m = -float("inf")
        schema.stable = False
        schema.requires_active_balance = True
        schema.warnings.append("两点支撑，必须主动平衡（需要 IMU + 力矩控制闭环）")
    else:
        schema.stability_margin_m = -float("inf")
        schema.stable = False
        schema.requires_active_balance = False

    # ── 6. 能力 ──
    caps: Set[Capability] = set()
    for m in topo.modules.values():
        caps.update(m.desc.capabilities)

    n_legs = len([c for c in chains if c.role == "leg"])
    n_wheels = len([c for c in chains if c.role == "wheel"])
    n_arms = len([c for c in chains if c.role == "arm"])

    # 能力可以从拓扑推导出来，不需要模块自己声明
    if n_legs >= 2 or n_wheels >= 2:
        caps.add(Capability.LOCOMOTION)
    if n_legs >= 3:
        caps.add(Capability.BALANCE)
    if n_arms >= 1:
        caps.add(Capability.MANIPULATION)
    if n_wheels >= 2:
        caps.add(Capability.ROLL)
    schema.capabilities = caps

    # ── 7. 运动模式 ──
    if n_legs >= 4:
        schema.locomotion_mode = "quadruped"
    elif n_legs == 3:
        schema.locomotion_mode = "tripod"
    elif n_legs == 2 and n_wheels >= 2:
        schema.locomotion_mode = "wheel_leg"
    elif n_legs == 2:
        schema.locomotion_mode = "biped"
    elif n_wheels >= 2:
        schema.locomotion_mode = "differential"
    elif n_wheels == 1:
        schema.locomotion_mode = "wheel_arm"
    elif n_arms >= 1:
        schema.locomotion_mode = "fixed_manipulator"
    else:
        schema.locomotion_mode = "immobile"

    # ── 8. 警告 ──
    if (not schema.stable
            and schema.locomotion_mode not in ("immobile",)
            and not schema.requires_active_balance):
        schema.warnings.append(
            f"支撑不足（裕度 {schema.stability_margin_m*1000:+.1f}mm），建议降级为趴伏模式")
    if schema.total_dof == 0:
        schema.warnings.append("全身无自由度，只是结构体")
    if n_legs == 1 and n_wheels == 0:
        schema.warnings.append("只有一条腿，无法行走")
    if n_legs + n_wheels == 0 and schema.locomotion_mode != "immobile":
        schema.warnings.append("无移动能力")
    if n_arms >= 1 and schema.total_mass_kg > 0:
        arm_mass = sum(topo.modules[m].desc.mass_kg
                       for c in chains if c.role == "arm"
                       for m in c.module_ids)
        if arm_mass / schema.total_mass_kg > 0.6:
            schema.warnings.append("臂占质量超过 60%，重心偏移严重")

    return schema