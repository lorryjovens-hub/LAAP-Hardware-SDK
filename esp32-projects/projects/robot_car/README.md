# ② 机器车（差速底盘）

> ROS 生态最成熟的一类。运控数学简单（2 自由度），工程重点是 **PID 闭环**。

---

## 硬件清单（约 ¥150）

| 件 | 型号 | 数量 | 说明 |
|----|------|------|------|
| 主控 | ESP32-S3 | 1 | |
| 电机 | N20 减速电机（带编码器） | 2 | 减速比 1:100~1:150 |
| 驱动 | TB6612FNG 或 DRV8833 | 1 | 双路 H 桥 |
| IMU | MPU6050 / QMI8658 | 1 | yaw 校正 |
| 超声 | HC-SR04 | 1 | 避障 |
| 电源 | 2S 锂电 + 降压 | 1 | 电机 7.4V，主控 5V |
| 底盘 | 亚克力两轮 + 万向轮 | 1 | |

---

## 接线

| 模块 | ESP32-S3 引脚 |
|------|--------------|
| TB6612 PWMA/AIN1/AIN2 | 4/5/6 |
| TB6612 PWMB/BIN1/BIN2 | 7/15/16 |
| 编码器 A 相（左/右） | 9/10（中断） |
| 编码器 B 相（左/右） | 11/12 |
| MPU6050 SDA/SCL | 8/18（I2C） |
| HC-SR04 TRIG/ECHO | 17/21 |

---

## 运控三层

### ① 运动学（开环解算）

```
v_left  = vx - ω·(wheel_base/2)
v_right = vx + ω·(wheel_base/2)
```

### ② PID 闭环（关键）

```
每 20ms:
    v_actual = (encoder_delta / ticks_per_rev) · (2π · wheel_radius) / dt
    pwm_delta = Kp·(v_target - v_actual) + Ki·integral + Kd·derivative
    pwm = clamp(pwm + pwm_delta, -MAX, MAX)
```

**调参顺序**（别跳）：
1. 先只给 Kp，从小往大加到"接近目标但有轻微振荡"
2. 加 Kd 压振荡
3. 最后加很小的 Ki 消静差（Ki 太大会积分饱和）

典型初值：`Kp=8, Ki=0.5, Kd=1.2`（按电机改）

### ③ 里程计

```python
from laap_esp32 import DifferentialDrive, RobotSpec

car = DifferentialDrive(RobotSpec(kind="car", wheel_radius_mm=35, wheel_base_mm=180))
pose = (0.0, 0.0, 0.0)
for _ in range(50):                      # 50 × 20ms = 1s
    pose = car.odometry(0.02, left_mm_s=100, right_mm_s=150, pose=pose)
# → x=123.4mm y=17.6mm θ=15.9°
```

---

## 固件结构

```
firmware/main/
  main.c        WiFi + WS + LDP 消息循环
  motor.c       TB6612 驱动 + 编码器中断 + PID 任务（20ms）
  odom.c        里程计积分 + IMU 融合（互补滤波）
  sonar.c       HC-SR04 测距 → percept("distance")
```

**PID 任务必须固定周期**（`vTaskDelayUntil`），周期抖动会让微分项炸。

---

## LAAP 侧对接

```python
from laap_esp32 import LDPProtocol, make_controller

car = make_controller("car")

mv = LDPProtocol.text_to_motion("往前走", kind="car")
if mv["cmd"] == "move":
    car.move(vx=mv["vx"])
    cmd = car.tick(0.02)
    # → {"target_left_mm_s": 150, "target_right_mm_s": 150}
    # 下发到固件，固件 PID 闭环
```

---

## 进阶：接 ROS2（可选）

如果要 SLAM / 路径规划，走 micro-ROS：

```
ESP32 (micro-ROS) ──▶ 上位机 (ros2 humble)
                       ├─ nav2 路径规划
                       ├─ slam_toolbox 建图
                       └─ 发布 /cmd_vel，订阅 /odom
```

ESP32 侧只需：订阅 `cmd_vel` → PID → 电机；读编码器 → 发 `odom`。

**判断标准**：只做"语音让它走"就用 LDP；要做自主导航才上 ROS。

---

## 调试步骤

1. 电机单独测试（正反转 + 调速）
2. 编码器计数验证（手转一圈看 tick 数是否等于标称值）
3. PID 单轮闭环（目标 100mm/s，看实际速度曲线）
4. 双轮直线测试（走 2 米，看偏多少，修 Kp 差异）
5. 转弯测试（ω=90°/s 转 90° 停）
6. 里程计验证（走一个正方形回到原点）
7. 加 IMU 融合校正 yaw 漂移

---

## 待办

- [ ] 固件骨架落地
- [ ] PID 自整定（阶跃响应自动算 Kp/Ki/Kd）
- [ ] 超声避障策略（前方 <200mm 自动停/绕）
