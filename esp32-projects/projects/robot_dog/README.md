# ③ 机械狗（四足）

> 数学最多、调试最费时的一类。**建议最后做**——先在宠物/车上验证整条链路，
> 再来对付 12 个舵机的协同。

---

## 硬件清单（约 ¥400）

| 件 | 型号 | 数量 | 说明 |
|----|------|------|------|
| 主控 | ESP32-S3 | 1 | |
| 舵机 | MG90S（金属齿） | 12 | 4 腿 × 3 关节，别用 SG90（塑料齿易崩） |
| 舵机驱动 | PCA9685（I2C 16 通道） | 1 | 比 ESP32 直出 PWM 稳 |
| IMU | MPU6050 / BNO085 | 1 | 姿态反馈（BNO085 更好，自带融合） |
| 电源 | 2S 锂电 + 5V/6V BEC | 1 | **12 舵机同时动电流很大，BEC 至少 5A** |
| 结构 | 3D 打印腿 + 机体 | 1 | Petoi/OpenCat 有现成模型 |

> ⚠️ **电源是第一个坑**：12 个 MG90S 堵转时总电流可达 8-10A，
> 用普通 2A 降压会瞬间掉压重启。必须独立 BEC + 大电容（1000µF）。

---

## 舵机布局（12 个）

```
        前
   LF ──────── RF        每条腿 3 个关节：
   │  机体      │        · coxa  横摆（左右摆）
   │            │        · femur 大腿（上下抬）
   LR ──────── RR        · tibia 小腿（膝弯）
        后
```

| 腿 | coxa 通道 | femur 通道 | tibia 通道 |
|----|----------|-----------|-----------|
| LF（左前） | 0 | 1 | 2 |
| RF（右前） | 3 | 4 | 5 |
| LR（左后） | 6 | 7 | 8 |
| RR（右后） | 9 | 10 | 11 |

---

## 三步走（别跳步）

### Step 1 · SDK 先算对（不用硬件）

```bash
python tools/fk_verify.py       # IK 精度反验，必须 0.00mm
python tools/sdk_selftest.py    # trot 一圈，看 max_joint_delta < 10°
```

**这一步能排除 90% 的问题**：如果算出来腿够不到地，装到真机上就是一堆舵机乱抖。

### Step 2 · 单腿标定

对每条腿做三件事：

```python
from laap_esp32 import LegIK, LegConfig

# 1) 量机构尺寸（mm）
cfg = LegConfig(coxa=40, femur=80, tibia=100, side=-1)   # 左腿 side=-1

# 2) 找零位：让腿呈「标准站姿」，记下三个舵机值 → 填 offset
cfg.offset_coxa = -3.0
cfg.offset_femur = 2.0
cfg.offset_tibia = -5.0

# 3) 测限位：手动测试各关节能转到的极限，填 range
cfg.coxa_range = (-45, 45)
cfg.femur_range = (-70, 80)
cfg.tibia_range = (-160, 0)
```

**顺序**：先标好一条腿，用同一套参数验证另外三条（只改 `side`）。

### Step 3 · 步态调参

```python
from laap_esp32 import QuadrupedGait, GaitType, GaitParams

gait = QuadrupedGait(
    GaitType.TROT,                       # 先用 trot
    GaitParams(
        step_length=60,                  # 步长（先小后大）
        step_height=30,                  # 抬腿高（低了绊地，高了慢）
        body_height=120,                 # 机体高度（低了腿折不住，高了够不到）
        period_s=0.5,                    # 周期（先慢，稳了再快）
    ),
)
```

**调参口诀**：
- 腿打滑 → 加 `step_height` 或减慢 `period_s`
- 走起来晃 → 降低 `body_height`（重心更低更稳）
- 腿够不到地 → 加 `body_height` 或减小 `step_length`
- 撞地 → `body_height` 太高，腿伸太直

---

## 三种步态的选择

| 步态 | 何时用 |
|------|--------|
| **Trot** | 默认。平地快走 |
| **Walk** | 负重、不平地面、要稳。三腿着地 |
| **Pace** | 基本不用，会侧翻 |

---

## 固件结构

```
firmware/main/
  main.c        WiFi + WS + LDP 循环
  leg.c         单腿 IK 调 C 版（照 gait.py 移植）
  gait.c        步态调度 + 足端轨迹
  servo.c       PCA9685 驱动（I2C，50Hz）
  imu.c         MPU6050 姿态 → 平衡修正
  balance.c     姿态反馈（斜坡补偿）
```

**控制频率**：50Hz（20ms 一周期）。低于 30Hz 动作会明显顿挫。

---

## C 版 IK 移植要点

Python 版（`gait.py` 的 `LegIK.solve`）直接照搬即可，注意：

```c
// 关键：膝角必须是 θ3 - 180（踩过坑，见 docs/RESEARCH.md）
float theta3 = acosf(clampf((L1*L1 + L2*L2 - D*D) / (2*L1*L2), -1.0f, 1.0f));
float tibia_deg = theta3 * 180.0f / M_PI - 180.0f;   // ← 这个 -180 不能少
```

同时要在 C 侧也做一次正运动学反验（单元测试），确保移植没走样。

---

## LAAP 侧对接

```python
from laap_esp32 import LDPProtocol, make_controller

dog = make_controller("dog")

# 语音："坐下" → 真坐下 + 语音确认
mv = LDPProtocol.text_to_motion("坐下", kind="dog")
if mv:
    dog.pose(mv["name"])
    cmd = dog.tick(0.02)     # → 12 个关节角
    # 下发到 PCA9685

# 语音："往前走" → trot 步态
mv = LDPProtocol.text_to_motion("往前走", kind="dog")
dog.move(vx=mv["vx"])
cmd = dog.tick(0.02)         # → {"gait": "trot", "joints": {...}}
```

---

## 常见故障

| 现象 | 原因 | 解法 |
|------|------|------|
| 舵机抖动 | 电源不足 | 换大 BEC + 电容 |
| 腿落不到该落的位置 | IK 角度约定错 | 跑 `fk_verify.py` 反验 |
| 走起来歪 | 左右腿标定不一致 | 重新标零位 |
| 抬腿绊地 | step_height 太小 | 加大到 35-40mm |
| 关机重启（一动作就断） | 电流峰值掉压 | 独立电机电源 + 软启动 |

---

## 待办

- [ ] 固件骨架落地（C 版 IK + PCA9685）
- [ ] 姿态过渡插值（stand→sit 平滑，避免舵机冲击）
- [ ] IMU 平衡反馈（斜坡自动调姿态）
- [ ] RL 步态（MuJoCo + PPO → sim2real，比手工步态鲁棒）
