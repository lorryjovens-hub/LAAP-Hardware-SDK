"""从身体图式自动推导运动学

## 这一层在做什么

输入：一条运动链（若干模块串联，每个带关节）
输出：末端位姿、雅可比、IK 解、稳定性

**关键：没有任何一块是人工配置的。** 关节轴、连杆长度、限位
全部来自模块的 BMD。插上新模块 → 链变了 → 运动学自动跟着变。

## 坐标系约定

世界系：X 前、Y 左、Z 上（右手系）

端口系（child 模块的局部系）：
    Z = port.normal（朝外）
    X = normalize(cross(world_up, Z))，退化时取 (1,0,0)
    Y = cross(Z, X)

FK：
    T = T_base · Π [ Translate(j.offset) · Rot(j.axis, q) · Translate(j.link) ]

This file is part of LAAP Hardware SDK, GPL v3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from .module import JointSpec, Port, Vec3

EPS = 1e-9


# ══════════════════════════════════════════════════════════
#  基础变换
# ══════════════════════════════════════════════════════════

def rot_axis(axis: Vec3, angle: float) -> np.ndarray:
    """Rodrigues 旋转矩阵（3×3）"""
    a = np.asarray(axis, dtype=float)
    n = np.linalg.norm(a)
    if n < EPS:
        return np.eye(3)
    a = a / n
    K = np.array([[0, -a[2], a[1]],
                  [a[2], 0, -a[0]],
                  [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * (K @ K)


def trans(p: Vec3) -> np.ndarray:
    """平移齐次矩阵（4×4）"""
    T = np.eye(4)
    T[:3, 3] = p
    return T


def rot4(axis: Vec3, angle: float) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = rot_axis(axis, angle)
    return T


def frame_from_zy(Z: Vec3, origin: Vec3) -> np.ndarray:
    """由 Z 轴方向构造端口坐标系

    Z = normal
    X = normalize(cross(world_up, Z))；Z 与 up 平行时退化取 (1,0,0)
    Y = cross(Z, X)
    """
    z = np.asarray(Z, dtype=float)
    nz = np.linalg.norm(z)
    if nz < EPS:
        raise ValueError("端口 normal 为零向量")
    z = z / nz

    up = np.array([0.0, 0.0, 1.0])
    x = np.cross(up, z)
    if np.linalg.norm(x) < 1e-6:
        # Z 与 up 平行（腿朝下/朝上）→ 退化，取世界前向
        x = np.array([1.0, 0.0, 0.0])
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)

    T = np.eye(4)
    T[:3, 0] = x
    T[:3, 1] = y
    T[:3, 2] = z
    T[:3, 3] = origin
    return T


def port_frame(port: Port) -> np.ndarray:
    """端口坐标系（在父模块局部系中）"""
    return frame_from_zy(port.normal, port.offset)


# ══════════════════════════════════════════════════════════
#  链式 FK
# ══════════════════════════════════════════════════════════

@dataclass
class ChainFrame:
    """FK 过程中一个节点的世界位姿"""
    name: str
    T: np.ndarray           # 4×4
    joint_origin: np.ndarray  # 关节转动中心世界坐标
    index: int


def chain_fk(joints: Sequence[JointSpec],
             q: Sequence[float],
             base_T: Optional[np.ndarray] = None) -> Tuple[np.ndarray, List[ChainFrame]]:
    """沿一条运动链做 FK

    @return (末端齐次变换, 各关节的位姿列表)
    """
    T = np.eye(4) if base_T is None else base_T.copy()
    frames: List[ChainFrame] = []

    for i, (j, qi) in enumerate(zip(joints, q)):
        T = T @ trans(j.offset)
        origin = T[:3, 3].copy()
        T = T @ rot4(j.axis, qi)
        frames.append(ChainFrame(j.name, T.copy(), origin, i))
        T = T @ trans(j.link)

    return T, frames


def tip_position(joints: Sequence[JointSpec], q: Sequence[float],
                 base_T: Optional[np.ndarray] = None) -> np.ndarray:
    T, _ = chain_fk(joints, q, base_T)
    return T[:3, 3]


# ══════════════════════════════════════════════════════════
#  雅可比与 IK
# ══════════════════════════════════════════════════════════

def jacobian_position(joints: Sequence[JointSpec],
                      q: Sequence[float],
                      base_T: Optional[np.ndarray] = None,
                      delta: float = 1e-5) -> np.ndarray:
    """位置雅可比（3×n），数值差分

    数值差分而不是解析：因为链的结构随时在变（插拔模块），
    解析式没法预先写死。差分对任意链都成立。
    """
    n = len(joints)
    J = np.zeros((3, n))
    qa = np.array(q, dtype=float)

    for i in range(n):
        qp = qa.copy(); qp[i] += delta
        qm = qa.copy(); qm[i] -= delta
        pp = tip_position(joints, qp, base_T)
        pm = tip_position(joints, qm, base_T)
        J[:, i] = (pp - pm) / (2 * delta)
    return J


@dataclass
class IKResult:
    q: List[float]
    error: float            # 末端位置误差（米）
    iterations: int
    converged: bool
    reason: str = ""


def ik_dls(joints: Sequence[JointSpec],
           q0: Sequence[float],
           target: np.ndarray,
           base_T: Optional[np.ndarray] = None,
           max_iter: int = 120,
           tol: float = 1e-4,
           damping: float = 1e-3) -> IKResult:
    """直线链的 DLS IK（便捷封装，内部调 ik_generic）"""
    def fk_pos(q):
        return tip_position(joints, q, base_T)

    lo = np.array([j.min_rad for j in joints])
    hi = np.array([j.max_rad for j in joints])
    return ik_generic(fk_pos, q0, target, lo, hi,
                      max_iter=max_iter, tol=tol, damping=damping)


def ik_generic(fk_pos: Callable[[Sequence[float]], np.ndarray],
               q0: Sequence[float],
               target: np.ndarray,
               lower: np.ndarray,
               upper: np.ndarray,
               max_iter: int = 120,
               tol: float = 1e-4,
               damping: float = 1e-3,
               delta: float = 1e-5,
               max_step: float = 0.3) -> IKResult:
    """任意链结构的 DLS IK

    为什么需要这个泛型版本：
      LBP 的链结构在运行时会变（插上新肢体），而且链上混着
      「关节」和「模块间的固定端口变换」。无法写成 joints+base_T 的形式。
      所以只要求调用方给一个 fk_pos(q) → 3D 位置 的闭包。

    参数：
      fk_pos  正解函数
      q0      初始关节角
      target  目标世界坐标
      lower/upper  关节限位
    """
    q = np.clip(np.array(q0, dtype=float), lower, upper)
    tgt = np.asarray(target, dtype=float)
    n = len(q)
    lam2 = damping ** 2
    err = float("inf")

    for it in range(max_iter):
        cur = np.asarray(fk_pos(q), dtype=float)
        e = tgt - cur
        err = float(np.linalg.norm(e))
        if err < tol:
            return IKResult(q.tolist(), err, it + 1, True, "收敛")

        # 数值雅可比
        J = np.zeros((3, n))
        for i in range(n):
            qp = q.copy(); qp[i] += delta
            qm = q.copy(); qm[i] -= delta
            J[:, i] = (np.asarray(fk_pos(qp)) - np.asarray(fk_pos(qm))) / (2 * delta)

        JJT = J @ J.T + lam2 * np.eye(3)
        try:
            dq = J.T @ np.linalg.solve(JJT, e)
        except np.linalg.LinAlgError:
            return IKResult(q.tolist(), err, it + 1, False, "矩阵奇异")

        step = float(np.linalg.norm(dq))
        if step > max_step:
            dq *= max_step / step

        q = np.clip(q + dq, lower, upper)

    return IKResult(q.tolist(), err, max_iter, False,
                    f"未收敛（误差 {err*1000:.1f}mm）")


# ══════════════════════════════════════════════════════════
#  支撑多边形与稳定性
# ══════════════════════════════════════════════════════════

def convex_hull_2d(points: np.ndarray) -> np.ndarray:
    """2D 凸包（Andrew monotone chain）

    点数很少（3-6 个足端），自己实现比拉 scipy 干净。
    """
    pts = sorted(set(map(tuple, points)))
    if len(pts) <= 2:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return np.array(lower[:-1] + upper[:-1])


def stability_margin(polygon: np.ndarray, com_xy: np.ndarray) -> float:
    """稳定裕度：质心投影到支撑多边形边界的最短距离

    正数 = 在多边形内（稳定），负数 = 在多边形外（要摔）
    单位：米

    这是四足机器人判断"会不会翻"的标准指标。
    工程上一般要求 > 0.02m 才敢迈步。
    """
    if len(polygon) < 3:
        return -float("inf")

    # 判断点是否在凸多边形内（叉积同号）
    n = len(polygon)
    inside = True
    min_dist = float("inf")

    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        edge = b - a
        to_p = com_xy - a
        cr = edge[0] * to_p[1] - edge[1] * to_p[0]
        if cr < 0:
            inside = False

        # 点到边的距离
        el = np.linalg.norm(edge)
        if el > EPS:
            d = abs(cr) / el
            min_dist = min(min_dist, d)

    return min_dist if inside else -min_dist
