# LBP C 组件 — 从站 / 主站 / 分段传输

> LBP/1.0 的 ESP-IDF 实现。**2977 行，纯 C，不依赖 C++ 和外部库。**

---

## 一行接入

### 从站（一条腿）

```c
#include "lbp.h"

static void on_cmd(const float *q, uint8_t dof, uint32_t t_exec, void *user) {
    for (int i = 0; i < dof; i++) servo_set(i, q[i]);
    lbp_node_send_telem(&g_node, q, NULL, 42, true);
}

static void on_stop(void *user) { servo_release_all(); }

void app_main(void) {
    lbp_node_t *n = calloc(1, sizeof(lbp_node_t));
    lbp_node_cfg_t cfg = {
        .addr       = CONFIG_LBP_NODE_ADDR,
        .mount_port = CONFIG_LBP_MOUNT_PORT,
        .bus = {
            .gpio_tx = CONFIG_LBP_CAN_TX_GPIO,
            .gpio_rx = CONFIG_LBP_CAN_RX_GPIO,
            .bitrate = CONFIG_LBP_BITRATE,
        },
        .on_cmd       = on_cmd,
        .on_safe_stop = on_stop,
    };
    lbp_fill_leg_3dof_bmd(&cfg.bmd, 0x1001);
    lbp_node_start(n, &cfg);
}
```

### 主站（躯干）

```c
lbp_master_t m;
lbp_bus_cfg_t bus = {
    .gpio_tx = CONFIG_LBP_CAN_TX_GPIO,
    .gpio_rx = CONFIG_LBP_CAN_RX_GPIO,
    .bitrate = CONFIG_LBP_BITRATE,
};
lbp_master_init(&m, &bus);

int found = lbp_master_enumerate(&m, 1500);   // 收 BMD
lbp_master_query_topology(&m, 0);             // 读端口 ID
lbp_master_print_topology(&m);

char json[1024];
lbp_master_topology_json(&m, json, sizeof(json));
wifi_send_to_pc(json);                        // PC 算身体图式 + IK

// 同步下发：四条腿同一个 t_exec
uint32_t t = now_us() + 100000;
lbp_master_send_cmd(&m, 2, q0, 3, t);
lbp_master_send_cmd(&m, 3, q1, 3, t);
lbp_master_send_cmd(&m, 4, q2, 3, t);
lbp_master_send_cmd(&m, 5, q3, 3, t);
```

---

## 为什么需要 TP 层（最容易忽略的一点）

**CAN 2.0B 单帧数据域只有 8 字节**（CAN FD 才是 64）。
而 LBP 帧最小 23 字节、典型 37–51 字节。

所以 LBP 帧必须分段。这不是优化，是协议能不能跑起来的前提。

### LBP/TP-8 分段格式

每 CAN 帧 8 字节：

```
byte0 = (seq << 4) | type
  type 0x1 SINGLE  整帧 ≤7 字节
  type 0x2 FIRST   byte1..2 = 总长(LE u16)，byte3..7 = 数据(5B)
  type 0x3 CONT    byte1..7 = 数据(7B)
  type 0x4 LAST    byte1..7 = 数据(1..7B)
```

例：23 字节 LBP 帧 → `FIRST(5) + CONT(7) + CONT(7) + LAST(4)` = **4 个 CAN 帧**

例：318 字节 BMD → LBP 帧 341B → **49 个 CAN 帧**（一次性枚举，可接受）

### CAN ID 分配

```
can_id = (priority << 8) | dst
```

优先级放高位 → **SAFETY 帧在 CAN 仲裁时天然抢占总线**，不需要软件调度。

---

## 分层

| 文件 | 层 | 内容 |
|------|----|------|
| `lbp_frame.c` | L2 | 帧编解码、CRC-32/ISO-HDLC、分片重组（纯逻辑，PC 可编译） |
| `lbp_payload.c` | L2 | 载荷编解码（小端二进制，见下） |
| `lbp_tp.c` | L1.5 | CAN 8 字节分段（纯逻辑） |
| `lbp_bus.c` | L1 | TWAI 驱动封装 |
| `lbp_node.c` | L3 | 从站：枚举应答 / 拓扑应答 / CMD 执行 / 遥测 / 反射 |
| `lbp_master.c` | L3 | 主站：枚举 / 拓扑收集 / 同步下发 |
| `lbp_bmd_presets.c` | L3 | 标准模块 BMD（3-DOF 腿、4-DOF 臂） |

---

## 载荷编码：为什么不是 JSON

实测踩到的两个硬约束：

| | JSON | 二进制 | 差 |
|---|------|-------|-----|
| TOPO_ACK | 67 B（**超 CAN 64B 上限**） | 3 B | 发不出去 |
| BMD (3DOF) | 663 B | **318 B** | 省 52%，少 10 个分片 |

所以全部载荷统一为固定布局小端二进制，对应 C 的 `#pragma pack(1)` 结构体。

| 消息 | 布局 | 大小（3DOF） |
|------|------|-------------|
| `TOPO_ACK` | `addr mount_port child_count [port child]×N` | 3 B |
| `CMD` | `flags dof q(f32)×dof` | 14 B |
| `TELEM` | `addr flags dof q(f32)×dof [torque] [temp]` | 28 B |
| `REFLEX` | `addr code joint value(f32)` | 7 B |
| `CLOCK_SYNC` | `t1_us(u64)` | 8 B |

### 单帧 CMD 的自由度上限

```
 9 DOF → 帧 61B  OK
10 DOF → 帧 65B  超限，需分片
```

所以**把一条腿做成一个独立节点**有两个好处：热插拔方便，且 CMD 能单帧下发。

---

## 两个真实踩过的坑

### 坑 1：分片丢了原始消息类型

分片后帧 `type` 全是 `FRAG`，接收方重组出 663 字节**却不知道这是 BMD**，只能丢弃。

分片头因此从 4 字节扩到 5 字节，加 `msg_type`：

```
group_id(2) index(1) total(1) msg_type(1)
```

代价：CAN 上每片容量从 37 B 降到 36 B。

### 坑 2：BMD 固定段少算 4 字节

`LBP_BMD_FIXED_SIZE` 宏里漏了 `mass` 的 4 字节 →
`lbp_bmd_encoded_size()` 少算 4 → 长度检查通过但**实际越界写 4 字节**（缓冲区溢出）。

现在宏写成常量 `89` 并在注释里逐项列出。
`test_bmd_parity.py` 会真去解析这个头文件跟 Python 常量对比。

---

## 反射弧：必须在模块里，不走总线

带宽核算：

```
技能层 10Hz × 20 关节 → 190 kbps → 占 5Mbps 的 3.8%   ✓
反射层 1kHz × 20 关节 → 8.8 Mbps → 占 378%           ✗ 超载
```

所以总线下发**目标位置 + 安全边界**，1kHz 反射环跑在模块 MCU 里：

```c
// 1kHz 任务里
if (read_motor_current(0) > 2500) {          // 2.5A 过流
    servo_release(0);                         // 立即卸力
    lbp_node_send_reflex(&node, LBP_REFLEX_OVER_CURRENT, 0, 2.5f);
}
```

`REFLEX` 走 `LBP_PRIO_SAFETY`（CAN ID 高位 0），仲裁时优先。

---

## 端口 ID 读取

模块侧 ID0/ID1/ID2 三根跳线接 GND 或悬空（3-bit 编码 0–7），主机侧 GPIO 上拉读取：

```c
uint8_t pos = lbp_read_port_id(GPIO_NUM_8, GPIO_NUM_9, GPIO_NUM_10);
bool present = lbp_is_present(GPIO_NUM_11);
```

**语义是「你插在我的第几号口」，所以编码跟着端口走，不跟模块走。**
同一块腿插 1 号口和 3 号口得到不同的身体图式 —— 这正是我们要的。

---

## 与 Python 侧的对齐

| C | Python | 校验 |
|---|--------|------|
| `lbp_frame.c` 帧布局 | `laaper/body/frame.py` | `test_bmd_parity.py` §5 |
| `lbp_bmd_encode` | `ModuleDescriptor.to_bytes()` | `test_bmd_parity.py` §1-4 |
| `lbp_payload.c` | `laaper/body/payload.py` | 布局表对照 |

```bash
python test_bmd_parity.py       # 41 项，真去解析 C 头文件
python tools/c_static_check.py  # 结构与符号检查
```

---

## 诚实边界

| 项 | 状态 |
|----|------|
| 帧 / 载荷 / 分段 / 节点 / 主站 | ✅ 完整实现（2977 行） |
| 与 Python 侧字节对齐 | ✅ 41 项校验通过 |
| 静态结构检查 | ✅ 通过 |
| **真机编译** | ❌ **本机无 IDF/gcc，未编译过** |
| TWAI 时序实测 | ❌ 需硬件 |
| 反射环（电流检测） | 🟡 框架就位，需接 ADC/驱动芯片 |
| BODY_SCHEMA 回传解析 | 🟡 主站只导出拓扑，图式在 PC 侧算 |
