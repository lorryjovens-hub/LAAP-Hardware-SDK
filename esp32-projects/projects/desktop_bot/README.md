# ④ 桌面机器人（宠物 + 车 合体）

> 前面三个项目的组合体：**能走 + 有表情 + 能说话 + 有屏幕**。
> 建议在宠物和车都跑通之后再上这个。

---

## 与其它项目的关系

```
桌面宠物（云台 + 表情 + 语音）  ┐
                              ├──→ 桌面机器人（全部）
机器车（差速 + 编解器）        ┘
                              └──→ 再加：屏幕显示电脑内容（P4 终端路线）
```

| 能力 | 来源 |
|------|------|
| 表情（圆屏/小屏） | pet_robot |
| 云台注视 | pet_robot |
| 底盘行走 | robot_car（差速轮）或 robot_dog（腿） |
| 语音对话 | xiaozhi 链路（已有 `laaper/hub/xiaozhi_audio_stream.py`） |
| 屏幕显示电脑 | `laaper/hub/screen_stream.py` + P4 终端（见 `docs/P4_DESKTOP_TERMINAL.md`） |

---

## 两种形态

### A. 小屏形态（ESP32-S3，成本低）

```
        ┌─────────┐
        │ 1.28" 圆屏 │ ← 表情（眼睛）
        ├─────────┤
        │  云台头   │ ← 2 舵机（看人）
        ├─────────┤
        │  底盘     │ ← 2 轮差速（走到你面前）
        └─────────┘
```

适合：桌宠、陪伴机器人。
硬件：ESP32-S3 + GC9A01 + 2 舵机 + 2 电机 + 麦/喇叭 ≈ ¥250

### B. 大屏形态（ESP32-P4，能显示电脑屏幕）

```
        ┌───────────────┐
        │  10.1" MIPI-DSI │ ← 电脑屏幕流（远程办公）
        ├───────────────┤
        │  云台/支架       │
        ├───────────────┤
        │  P4 + 麦 + 喇叭  │
        └───────────────┘
```

适合：远程办公终端（详见 `docs/P4_DESKTOP_TERMINAL.md`）。
硬件：ESP32-P4 + MIPI-DSI 屏 + I2S 麦/功放 ≈ ¥500

---

## 统一运动抽象怎么组合

桌面机器人同时有两种运动（底盘 + 云台），用两个 controller 并行：

```python
from laap_esp32 import make_controller

chassis = make_controller("car")     # 底盘
head    = make_controller("pet")     # 云台头

# 一句指令，两个身体同时响应
def handle(text):
    mv = LDPProtocol.text_to_motion(text, kind="car")
    if not mv:
        mv = LDPProtocol.text_to_motion(text, kind="pet")

    if mv["cmd"] == "move":
        chassis.move(vx=mv.get("vx", 0), omega=mv.get("omega", 0))
    elif mv["cmd"] == "pose":
        head.pose(mv["name"])         # 云台做姿态
    elif mv["cmd"] == "stop":
        chassis.stop()

# 控制循环（50Hz）
def loop():
    c1 = chassis.tick(0.02)   # → 左右轮速
    c2 = head.tick(0.02)      # → pan/tilt
    # 各下发各的
```

**关键设计**：底盘和云台**解耦**——可以一边走一边看人，
这个"边走边看"本身就是很强的生命感信号。

---

## 生命感三件套（桌面机器人最完整）

1. **注视**：说话时云台转向说话人（`head.look_at(dx, dy)`）
2. **表情**：屏幕眼睛随对话状态变化（listening/thinking/speaking）
3. **移动**：被叫时真的走过来（不只是转头）

三者叠加会产生一个有意思的效果：
**它朝你走过来并抬眼看你的瞬间，你会觉得它"在"**。

---

## 待办

- [ ] 底盘 + 云台组合的固件骨架
- [ ] 边走边看的协调逻辑（走的时候云台保持看向目标）
- [ ] P4 大屏形态的完整固件（见 `firmware/p4_terminal/`）
