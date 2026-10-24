# ① 桌面宠物（agent 宠物）

> **最推荐的起步项目**：2 个自由度就能表达生命感，代码量最小，
> 最快验证「语音 → 意图 → 动作 → 反馈」整条链路。

---

## 硬件清单（约 ¥120）

| 件 | 型号 | 数量 | 说明 |
|----|------|------|------|
| 主控 | ESP32-S3-WROOM-1（N16R8） | 1 | 16MB Flash / 8MB PSRAM，够跑 LVGL + 语音 |
| 圆屏 | GC9A01 240×240 SPI | 1 | 表情全靠它 |
| 云台舵机 | SG90 / MG90S | 2 | pan（左右）+ tilt（上下） |
| 麦克风 | INMP441（I2S） | 1 | 语音输入 |
| 功放 | MAX98357A（I2S） | 1 | 驱动喇叭 |
| 喇叭 | 8Ω 2W 小喇叭 | 1 | |
| 触摸 | TTP223 | 1 | 摸头反应（生命感关键） |
| 电源 | 18650 + 充电板 | 1 | 或直接 USB 供电 |

---

## 接线

| 模块 | ESP32-S3 引脚 | 说明 |
|------|--------------|------|
| GC9A01 SCK/MOSI/CS/DC/RST | 12/11/10/9/8 | SPI |
| GC9A01 BL | 3.3V（或 7 加 PWM 调光） | 背光 |
| SG90 pan（信号） | 4 | LEDC PWM 50Hz |
| SG90 tilt（信号） | 5 | LEDC PWM 50Hz |
| INMP441 SCK/WS/SD | 14/15/16 | I2S RX |
| MAX98357A BCLK/LRC/DIN | 18/17/19 | I2S TX |
| TTP223 OUT | 6 | 触摸检测 |

---

## 生命感设计（这才是宠物的核心）

运动只有 2 个自由度，所以「活着」靠这三样：

### 1. 表情系统（圆屏 LVGL）

| 状态 | 眼睛表现 |
|------|---------|
| idle | 呼吸式缩放 + 每 3-8 秒随机眨眼 |
| listening | 瞳孔放大、看向声源方向 |
| thinking | 眼球左右缓移、偶尔上翻 |
| speaking | 随音量波动的环形波 |
| happy | 弯成 ^ ^ 弧线 |
| sleep | 闭眼 + 呼吸节奏变慢 |

### 2. 动作平滑

所有云台动作走一阶低通（`pan += (target-pan)*0.25`），
**绝不生硬跳变**——这是机械感和生命感的分界线。

### 3. 主动注意

不等人叫，自己转头看人：
- 触摸 → 立刻转向触摸点 + 开心表情
- 检测到声音方向 → 缓慢转头
- 长时间无交互 → 打瞌睡（低头 + 闭眼）

---

## 固件结构

```
firmware/main/
  main.c        WiFi + WS + LDP 循环（复制 projects/robot_car 的骨架改）
  motion.c      2 舵机 PWM + 一阶低通平滑
  display.c     GC9A01 + LVGL 表情（眨眼/瞳孔/波形）
  audio.c       I2S 麦克风采集 + 功放播放 + Opus
  touch.c       TTP223 中断 → percept("touch")
```

关键代码位置：
- `motion.c`：`servo_set_angle(pan, tilt)` 用 LEDC，50Hz，0.5-2.5ms 脉宽
- `display.c`：LVGL 画两个圆当眼睛，`lv_anim` 做眨眼
- `audio.c`：直接用 `laaper/hub/xiaozhi_audio_stream.py` 的协议（Opus 16k/20ms）

---

## LAAP 侧对接

```python
from laap_esp32 import LDPProtocol, make_controller

pet = make_controller("pet")
proto = LDPProtocol(device_id="pet-01", kind="pet")

# 小智说"打个招呼" → 宠物挥手 + 说"你好呀"
mv = LDPProtocol.text_to_motion("打个招呼", kind="pet")
if mv:
    pet.pose(mv["name"])          # look_up/think/nod
    # 下发 dialogue.text 让它播报

# 被摸头 → 开心
proto.percept("touch", {"zone": "head", "pressed": True})
pet.pose("look_up")
```

---

## 调试步骤

1. 先不装舵机，只用 `tools/sdk_selftest.py` 验证算法
2. 点亮圆屏（LVGL hello world），确认 SPI 正常
3. 单个舵机测试 0/90/180 三个角度，确认方向和限位
4. 双舵机云台组合，验证 pan/tilt 正交
5. 加麦克风 + 功放，跑通 Opus 回环（录一段播一段）
6. 最后接 LDP，用语音驱动

---

## 待办

- [ ] 固件骨架落地（当前是清单 + 关键点，需按板子填引脚）
- [ ] 表情资源设计（眼睛形状/眨眼曲线）
- [ ] 唤醒词自定义（用 "aris" 训练 ESP-SR WakeNet）
