# LAAP ESP32 硬件开发工作流

> 从「想做一台机器人」到「它接入 LAAP 能听能动能说话」的完整路径。
> 强调：**先在软件里验证，再碰硬件**。硬件调错的代价是时间和烧掉的舵机。

---

## 全景

```
Phase 1 选型          → 决定做哪类机器人（宠物/车/狗/桌面）
Phase 2 算法验证      → SDK 自检 + FK 反验（不用硬件，1 小时）
Phase 3 LAAP 侧联调   → 语义映射 + 运动指令生成（半天）
Phase 4 单体硬件调试  → 逐个外设点亮（1-2 天）
Phase 5 标定          → 舵机零位/方向/限位（1-2 天，最耗时）
Phase 6 整机联调      → 语音 → 动作 → 反馈（1 天）
Phase 7 接入三端      → 挂到中继，被小智/手机/电脑控制（半天）
```

---

## Phase 1 · 选型决策树

```
想最快看到效果？
  └─ 是 → 桌面宠物（2 自由度，¥120，2 天能跑）

需要移动能力？
  └─ 是 → 需要越障？
            ├─ 是 → 机械狗（12 舵机，¥400，1-2 周）
            └─ 否 → 机器车（差速，¥150，3-5 天）

需要屏幕显示？
  └─ 是 → 桌面机器人（宠物+车合体，或 ESP32-P4 屏终端）
```

**推荐顺序**：宠物 → 车 → 桌面机器人 → 狗。
理由：每级只增加一个维度的复杂度，链路复用。

---

## Phase 2 · 算法验证（关键步骤，别跳过）

### 2.1 SDK 自检

```bash
cd esp32-projects
python tools/sdk_selftest.py
```

期望输出：
```
[1] 单腿逆运动学 ... 不可达（正确）
[2] Trot 步态一圈 → {"unreachable": 0, "smooth": true, "ok": true}
[5] 运动抽象 → car/dog/pet 三类都能 tick
[8] LDP 协议 → hello/percept/move 全通
```

### 2.2 IK 精度反验（四足必做）

```bash
python tools/fk_verify.py
```

**必须 0.00mm 误差**。如果偏差几十毫米，说明角度约定错了——
装到真机上就是"腿落不到该落的地方"，现象像舵机标定问题，极难排查。

### 2.3 参数试算

在纸上/代码里先算清楚：
- 你的腿长（coxa/femur/tibia）能覆盖多高、多远？
- 步长 60mm 时，足端轨迹是否都在可达范围内？

```python
from laap_esp32 import LegIK, LegConfig
ik = LegIK(LegConfig(coxa=40, femur=80, tibia=100))
# 扫一遍工作空间，看哪些位置不可达
for y in range(40, 160, 10):
    for z in range(-60, -180, -10):
        if ik.solve(0, y, z) is None:
            print(f"不可达: y={y} z={z}")
```

**这一步能把"装机后腿够不到地"的问题提前消灭。**

---

## Phase 3 · LAAP 侧联调（无硬件）

### 3.1 语义映射

```python
from laap_esp32 import LDPProtocol

# 把中文翻成运动指令
for text in ["往前走", "快点前进", "左转", "坐下", "打个招呼", "停"]:
    print(text, "→", LDPProtocol.text_to_motion(text, kind="dog"))
```

### 3.2 运动指令生成

```python
from laap_esp32 import make_controller

dog = make_controller("dog")
dog.move(vx=100, omega=20)
for i in range(25):                    # 跑半秒
    cmd = dog.tick(0.02)
    # 这个 cmd 就是要下发给固件的内容
    print(cmd["gait"], cmd["joints"])
```

**确认关节角序列连续平滑**（相邻两步单关节变化 < 10°），否则真机会抖。

---

## Phase 4 · 单体硬件调试

**顺序很重要**（从最简单到最复杂）：

### 宠物
1. 圆屏点亮（SPI + LVGL hello）
2. 单个舵机（0/90/180 三点）
3. 双舵机云台（pan/tilt 正交）
4. 麦克风（录 1 秒，看波形）
5. 功放（播一段测试音）
6. 触摸（串口打印按下/松开）

### 车
1. 电机正反转（先给 30% PWM）
2. 编码器计数（手转一圈，核对 tick）
3. PID 单轮（目标 100mm/s，看速度曲线）
4. IMU（读 roll/pitch/yaw）
5. 超声（量 10cm/30cm/1m）

### 狗
1. **电源先验**（12 舵机堵转电流，示波器看掉压）
2. 单个舵机（确认方向和限位）
3. PCA9685 多通道（逐个通道点亮）
4. 单腿三关节（coxa→femur→tibia 逐级）
5. 单腿 IK（输入足端坐标，看实际落点）
6. 四条腿（`side` 镜像验证）

---

## Phase 5 · 标定（最耗时，别抄近路）

### 舵机三件事

```python
from laap_esp32 import LegConfig

cfg = LegConfig(
    coxa=40, femur=80, tibia=100,
    side=-1,                    # ① 方向：左腿 -1，右腿 +1
    offset_coxa=-3.0,           # ② 零位偏移（逐个试出来）
    offset_femur=2.0,
    offset_tibia=-5.0,
    coxa_range=(-45, 45),       # ③ 限位（手动测极限，留 5° 余量）
    femur_range=(-70, 80),
    tibia_range=(-160, 0),
)
```

### 标定流程

1. **找零位**：让腿呈标准站姿（大腿水平、小腿垂直），记下三个舵机值
2. **测方向**：给 +10°，看腿往哪个方向动，不符就改 `side`
3. **测限位**：慢慢加到机械极限前停，多留 5° 余量防堵转
4. **写回配置**：所有动作都基于这套 offset

### 验证

```python
# 让腿走到指定足端位置，用尺子量实际位置
ik = LegIK(cfg)
joints = ik.solve(0, 80, -120)     # 期望足端在 (0, 80, -120)
# 下发 → 量实际 → 误差应 < 5mm（机械间隙导致）
```

---

## Phase 6 · 整机联调

### 6.1 站立

```python
dog.pose("stand")
cmd = dog.tick(0.02)
# 12 个关节角下发，四条腿撑起机体
```

检查：机体水平？四腿高度一致？有没有舵机持续响（堵转）？

### 6.2 步态

```python
dog.move(vx=50)                    # 先慢
for i in range(50):
    cmd = dog.tick(0.02)
    # 观察：有没有打滑、晃动、绊地
```

调参口诀见 `projects/robot_dog/README.md`。

### 6.3 语音闭环

```
小智说"往前走" → LAAP 解析 → motion.move → 设备走
             ← dialogue.text "好，往前走"
```

**这是整条链路的验收点**：说一句话，机器真的动了，还回你一句。

---

## Phase 7 · 接入三端

设备作为 node 挂到 `api.laap.cn`：

```python
# LAAP 侧
from laaper.hub.tri_node_daemon import TriNodeDaemon, DaemonConfig

daemon = TriNodeDaemon(DaemonConfig(
    cloud_url="wss://api.laap.cn/ws",
    cloud_token="<jwt>",
))
await daemon.start()

# 现在可以：
await daemon.assign("dog-01", "motion.pose", {"name": "sit"})
await daemon.broadcast("大家注意，我要开始工作了")
```

接入后的能力：
- 小智硬件说"让狗坐下" → 中继 → 狗真的坐下
- 手机 LAAP-Mobile 查看狗的电量/状态
- 电脑屏幕显示狗的摄像头画面（P4 终端屏幕流）

---

## 检查清单（每个阶段收尾自查）

### Phase 2 后
- [ ] `sdk_selftest.py` 全绿
- [ ] `fk_verify.py` 误差 < 1mm
- [ ] 工作空间扫描无意外不可达

### Phase 4 后
- [ ] 每个外设都有串口日志证明工作
- [ ] 电源在最大负载下不掉压

### Phase 5 后
- [ ] 每条腿的 offset/side/range 都记录在配置里
- [ ] 足端定位误差 < 5mm

### Phase 6 后
- [ ] 站立不堵转、不晃
- [ ] 步态连续平滑（单关节步间变化 < 10°）
- [ ] 语音 → 动作 → 反馈闭环

### Phase 7 后
- [ ] 设备在中继上显示在线
- [ ] 其他端能派活给它并能收到回执

---

## 时间预估（一个人）

| 项目 | 硬件到手前 | 硬件到手后 | 总计 |
|------|-----------|-----------|------|
| 桌面宠物 | 0.5 天 | 2-3 天 | 3 天 |
| 机器车 | 0.5 天 | 3-5 天 | 5 天 |
| 机械狗 | 1 天 | 7-10 天 | 2 周 |
| 桌面机器人 | 1 天 | 5-7 天 | 1 周 |

硬件到手前的时间主要花在 Phase 2/3（算法验证 + LAAP 联调），
这部分**完全不需要硬件**，可以现在就做。
