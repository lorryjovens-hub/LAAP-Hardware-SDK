"""LAAP Body Protocol — 身体层的协议工程实现

## 这个包是什么

LAAP 之前所有工作都在软件抽象层之上（OS/ROS 给的数）。
这个包补的是**物理地面**：定义身体怎么被协议描述、怎么被发现、
插拔之后身体图式怎么自动重建。

## 分层

```
frame.py       L2 链路层  帧 / CRC32 / 分片 / 优先级 / 时钟同步
module.py      L3 节点层  模块自描述 BMD / 标准模块库
topology.py    L4 身体层  拓扑 / 运动链 / 身体图式推导
kinematics.py  L4 身体层  FK / DLS-IK / 支撑多边形 / 稳定裕度
morphing.py    L4 身体层  装配 / 变形场景 / 重构验证
```

## 最大的差别：物理拓扑就是语义

USB 枚举把「插在哪个口」当寻址信息。
LBP 把「插在哪个口」当成**身体结构**：

    底面四角 → 四足
    两侧     → 双臂
    四角四轮 → 车

协议不需要知道"我是四足"，它只要知道谁接在哪，
**身体图式是推导出来的**。

用法：

```python
from laaper.body import Topology, make_module, derive_schema

topo = Topology()
body = topo.add_module(make_module("power_core"), label="躯干")
leg = topo.add_module(make_module("leg_3dof"), label="前左腿")
topo.connect(body, 0, leg)

schema = derive_schema(topo)
print(schema.summary())
```

This file is part of LAAP Hardware SDK, GPL v3.
"""
from .frame import (
    LBPFrame, MsgType, Priority, Flags,
    Fragment, Fragmenter, PriorityQueue, ClockSync,
    bandwidth_estimate,
    SOF, EOF, HDR_SIZE, TRAILER_SIZE, MAX_PAYLOAD, MAX_CAN_PAYLOAD,
    ADDR_BROADCAST, ADDR_UNASSIGNED,
)
from .module import (
    ModuleClass, ModuleRole, Capability, BusProfile,
    JointSpec, Port, ModuleDescriptor,
    MODULE_LIBRARY, make_module,
    make_power_core, make_leg_3dof, make_arm_4dof,
    make_wheel_module, make_camera_head,
    make_speaker_module, make_gripper_module,
)
from .topology import (
    ModuleInstance, Connection, Topology,
    ChainSegment, KinematicChain, BodySchema,
    derive_schema,
)
from .kinematics import (
    rot_axis, trans, rot4, frame_from_zy, port_frame,
    chain_fk, tip_position, jacobian_position,
    IKResult, ik_dls, ik_generic,
    convex_hull_2d, stability_margin,
)

__all__ = [
    # 链路层
    "LBPFrame", "MsgType", "Priority", "Flags",
    "Fragment", "Fragmenter", "PriorityQueue", "ClockSync",
    "bandwidth_estimate",
    "SOF", "EOF", "HDR_SIZE", "TRAILER_SIZE", "MAX_PAYLOAD", "MAX_CAN_PAYLOAD",
    "ADDR_BROADCAST", "ADDR_UNASSIGNED",
    # 节点层
    "ModuleClass", "ModuleRole", "Capability", "BusProfile",
    "JointSpec", "Port", "ModuleDescriptor",
    "MODULE_LIBRARY", "make_module",
    "make_power_core", "make_leg_3dof", "make_arm_4dof",
    "make_wheel_module", "make_camera_head",
    "make_speaker_module", "make_gripper_module",
    # 身体层
    "ModuleInstance", "Connection", "Topology",
    "ChainSegment", "KinematicChain", "BodySchema",
    "derive_schema",
    # 运动学
    "rot_axis", "trans", "rot4", "frame_from_zy", "port_frame",
    "chain_fk", "tip_position", "jacobian_position",
    "IKResult", "ik_dls", "ik_generic",
    "convex_hull_2d", "stability_margin",
]
