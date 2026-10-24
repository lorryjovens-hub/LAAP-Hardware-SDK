# LAAP ESP32 硬件项目库

> 数字生命的四种身体：桌面宠物 · 机械狗 · 机器车 · 桌面机器人
> 一套认知（LAAP）、一套协议（LDP）、四套躯体。

---

## 这个库是什么

```
esp32-projects/
├── README.md                    本文件（总览 + 工作流）
├── docs/
│   ├── RESEARCH.md              ★ 开源项目深度调研（对话/运控/步态/差速）
│   ├── LDP_PROTOCOL.md          统一接入协议规范
│   └── WORKFLOW.md              从零到一台能跑的机器人的完整工作流
├── sdk/
│   └── laap_esp32/              ★ LAAP ESP32 统一 SDK（Python 参考实现）
│       ├── protocol.py          LDP 协议（注册/感知/运动/对话）
│       ├── motion.py            运动抽象（差速/四足/云台）
│       └── gait.py              四足 IK + 步态（trot/walk/pace）
├── projects/
│   ├── pet_robot/               ① 桌面宠物（圆屏表情 + 云台 + 语音）
│   ├── robot_car/               ② 机器车（差速 + 编码器 PID + 超声）
│   ├── robot_dog/               ③ 机械狗（12 舵机 IK + 三种步态）
│   └── desktop_bot/             ④ 桌面机器人（宠物 + 车 合体）
└── tools/
    ├── sdk_selftest.py          SDK 全量自检
    ├── fk_verify.py             ★ 正运动学反验 IK（0.00mm 误差）
    └── gait_animate.py          步态可视化（导出动画帧）
```

---

## 核心设计：一个运动抽象，三类身体

LAAP 的指令层**不需要知道**对面是轮子还是十二条腿：

```python
from laap_esp32 import make_controller

robot = make_controller("dog")     # 或 "car" / "pet"
robot.move(vx=100, omega=20)       # 同一句调用
robot.pose("sit")                  # 同一个动词
cmd = robot.tick(dt=0.02)          # 同一个控制周期
```

| 类型 | tick() 输出 | 自由度 |
|------|------------|--------|
| `car` | 左右轮目标角速度（固件 PID 闭环） | 2 |
| `dog` | 12 个关节角（IK + 步态） | 12 |
| `pet` | pan/tilt 角度（一阶低通平滑） | 2 |

---

## 协议 LDP 一眼看懂

```
设备 ──hello/register──▶ LAAP     上报身份 + 能力（会什么姿态、有什么传感器）
设备 ──percept────────▶ LAAP     感知上报（IMU/触摸/距离/图像）
LAAP ──motion.move────▶ 设备     {vx, vy, omega}
LAAP ──motion.pose────▶ 设备     {name: "sit"|"wave"|"look_up"}
LAAP ──dialogue.text──▶ 设备     要说的话（设备播报 + 显示）
设备 ──state.report───▶ LAAP     电量/运动状态/在线
```

**语义映射**（LAAP 侧把中文翻成运动指令）：

```python
LDPProtocol.text_to_motion("往前走")   # → {"cmd":"move", "vx":150}
LDPProtocol.text_to_motion("坐下")     # → {"cmd":"pose", "name":"sit"}
LDPProtocol.text_to_motion("看着我")   # → {"cmd":"pose", "name":"look_up"}
```

传输复用已有三端链路：局域网 `ws://<ip>:8765` / 云端 `wss://api.laap.cn/ws`。

---

## 已实现的算法（都验证过）

### ① 四足逆运动学（三段腿）

```
θ1 = atan2(x, y)                                    coxa 绕竖直轴
θ2 = atan2(z, a) + acos((L1²+D²-L2²)/(2·L1·D))      femur
θ3 = acos((L1²+L2²-D²)/(2·L1·L2))                  大腿-小腿内角
tibia_servo = θ3 - 180                              ★ 偏离伸直位（0=直）
```

**验证方式**：正运动学反验，5 个测试点误差 **0.00mm**。
运行 `python tools/fk_verify.py` 可复现。

> 踩过的坑：最初写成 `-θ3`，足端落点最大偏 99mm。
> 现象像舵机标定问题，实则是角度约定错。**IK 写完必须用 FK 反验。**

### ② 三种步态

| 步态 | 相位偏移 | 占空比 | 用途 |
|------|---------|--------|------|
| trot | LF/RR=0, RF/LR=0.5 | 0.5 | 机器狗默认，快且稳 |
| walk | LF=0, RR=.25, RF=.5, LR=.75 | 0.75 | 四拍，三腿着地最稳 |
| pace | LF/LR=0, RF/RR=.5 | 0.5 | 同侧，易侧翻 |

### ③ 差速里程计

```
v = (v_l + v_r)/2,  ω = (v_r - v_l)/wheel_base
θ += ω·dt,  x += v·cos(θ)·dt,  y += v·sin(θ)·dt
```

### ④ 云台平滑（生命感）

一阶低通 `pan += (target - pan) * 0.25`——动作不生硬，这是"活着"的手感来源。

---

## 完整工作流（从零到能跑）

### Phase 1 · 选型与选路（半天）

```
想做宠物？ → projects/pet_robot   2舵机+圆屏，最快见效
想做车？   → projects/robot_car   2电机+编码器，ROS 生态好
想做狗？   → projects/robot_dog   12舵机，数学最多，最后做
```

### Phase 2 · SDK 先跑通（1 小时，不用硬件）

```bash
python tools/sdk_selftest.py     # IK/步态/协议全链路自检
python tools/fk_verify.py        # IK 精度反验（应 0.00mm）
```

**这一步能在没有硬件的情况下验证所有算法**——先确认数学对，再买硬件。

### Phase 3 · LAAP 侧联调（半天）

```python
# 电脑上：注册设备 + 收感知 + 下发动作
from laap_esp32 import LDPProtocol, make_controller

proto = LDPProtocol(device_id="pet-01", kind="pet")
robot = make_controller("pet")

# 语音指令 → 运动
mv = LDPProtocol.text_to_motion("打个招呼", kind="pet")
if mv: robot.pose(mv["name"])
```

### Phase 4 · 固件烧录（1-2 天）

各项目的 `firmware/` 里是 IDF 工程骨架：
```
projects/pet_robot/firmware/main/
  main.c        WiFi + WS + LDP 消息循环
  motion.c      舵机驱动 + 云台平滑
  display.c     圆屏表情（LVGL）
  audio.c       I2S 麦克风/喇叭 + Opus
```

### Phase 5 · 真机标定（1-2 天）

**这步最费时间，别跳过**：
1. 每条腿/每个舵机的**零位偏移**逐个调
2. **方向**确认（左右镜像）
3. **限位**测试（避免舵机堵转烧毁）
4. 站立中立位固定为基准

### Phase 6 · 接入 LAAP 三端（半天）

设备作为 node 挂到 `api.laap.cn` 中继，就能：
- 小智硬件说"让狗过来" → LAAP 派活 → 狗移动
- 手机看狗的状态
- 电脑屏幕显示狗的摄像头画面

---

## 硬件选型速查

| 类型 | 主控 | 关键外设 | 预算 |
|------|------|---------|------|
| 桌面宠物 | ESP32-S3 | GC9A01 圆屏 + 2×SG90 + INMP441 麦 + MAX98357 功放 | ¥120 |
| 机器车 | ESP32-S3 | 2×N20 电机+编码器 + MPU6050 + HC-SR04 | ¥150 |
| 机械狗 | ESP32-S3 | 12×MG90S/SG90 + PCA9685 + MPU6050 | ¥400 |
| 桌面机器人 | ESP32-P4/S3 | 宠物+车 合体 + MIPI-DSI 屏 | ¥500 |

---

## 与 LAAP 其它部分的关系

```
        LAAP 认知核心（PSI/记忆/意识流帧）
                    ↓
        ┌───────────┴────────────┐
   电脑执行端                 硬件身体
   computer_use              ← 本库（ESP32 四类）
   browser_agent                 ↓
   multi_step              LDP 协议 + 三端中继
        ↓                       ↓
   TriNodeDaemon ←──────→ api.laap.cn
        ↓
   小智硬件（语音）/ 手机（LAAP-Mobile）/ ESP32-P4 桌面终端（屏幕流）
```

---

## 诚实标注

| 部分 | 状态 |
|------|------|
| SDK 算法（IK/步态/运动学/协议） | ✅ 已实现 + 自检通过 + FK 反验 0.00mm |
| 调研报告（四类开源、对话/运控算法） | ✅ 完成 |
| LDP 协议 | ✅ 实现 + 自检 |
| 各项目固件骨架 | 🟡 代码就位，**需真硬件编译联调** |
| 真机标定 | ⚪ 需实际舵机/电机 |
| RL 步态（MuJoCo sim2real） | ⚪ 待深入 |

---

*LAAP — 从"能看能说"到"能走能跑"。*
