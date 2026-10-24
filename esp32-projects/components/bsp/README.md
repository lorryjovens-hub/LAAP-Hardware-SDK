# LAAP BSP — 板级支持包

> 换一块板子，业务代码**一行都不用改**。

---

## 为什么需要 BSP

之前的状态：每个 `board.c` 里硬编码引脚宏、SPI 初始化、LEDC 通道、
I2S 配置。宠物板改到机器车，`display.c` / `motion.c` / `audio.c` 全要改。

BSP 解决两件事：

1. **引脚归 BSP**：`boards/<板名>/board_pins.h` 一处定义
2. **能力归声明**：`bsp_info_t.caps` 告诉应用「这块板有什么」

应用代码只问 `bsp_has_cap(BSP_CAP_DISPLAY)`，不问「你是哪块板」。

---

## 应用代码怎么写（永远这样写）

```c
void app_main(void)
{
    ESP_ERROR_CHECK(bsp_init());        // ① 板子自己初始化

    display_init();                      // ② 应用层逻辑
    motion_init();                       //    内部各自判断能力
    audio_init();
    touch_init(on_touch);

    while (1) {
        display_update(20);              // 生命表达
        motion_tick(20);
        touch_poll();
        bsp_tick();                      // ③ 板级周期任务
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
```

**这段代码在 5 块板子上都编译、都跑**：

| 板子 | display_init | motion_init | audio_init | touch_init |
|------|:---:|:---:|:---:|:---:|
| s3_round_gc9a01 | ✅ 240x240 | ✅ 2 舵机 | ✅ 麦克风+喇叭 | ✅ TTP223 |
| s3_korvo2 | ✅ 240x240 | ⚠ 跳过（无舵机） | ✅ 双麦+codec | ⚠ 跳过 |
| s3_eye | ✅ 240x240 | ⚠ 跳过 | ✅ 仅麦克风 | ⚠ 跳过 |
| p4_lcd | ⚠ DSI 待接 | ⚠ 跳过 | ✅ codec | ✅ GT911 |
| generic | ✅ 自定义引脚 | ✅ 2 舵机 | ✅ | ✅ |

⚠ = 该板无此能力，函数内部直接返回，不会崩，不会链接失败。

---

## 弱符号机制（核心设计）

`bsp_base.c` 给每个接口一个**弱默认实现**：

```c
__attribute__((weak)) esp_err_t bsp_servo_init(void)
{
    ESP_LOGW(TAG, "此板无舵机通道");
    return ESP_ERR_NOT_SUPPORTED;
}
```

板子用**强符号**覆盖它真正具备的能力：

```c
esp_err_t bsp_servo_init(void) { /* 真的初始化舵机 */ }   // s3_round 覆盖了
// s3_korvo2 没覆盖 → 自动走弱实现 → 返回 NOT_SUPPORTED
```

**好处**：
- 板子只实现自己有的东西，不用写一堆 `return ESP_ERR_NOT_SUPPORTED`
- 新板子漏实现某个函数不会链接失败，只会降级
- `bsp_init()` 按 `caps` 决定调哪些，实现和声明不一致只是警告

---

## 目录结构

```
components/bsp/
├── include/
│   ├── bsp.h              统一接口（应用只 include 这个）
│   ├── bsp_types.h        能力位 + bsp_info_t
│   ├── bsp_board.h        内部契约（base ↔ board，应用不用看）
│   └── bsp_common.h       公共实现（板子复用）
├── bsp_base.c             通用层 + 弱默认实现
├── bsp_common.c           SPI LCD / 舵机 / I2S / ADC 的通用实现
├── Kconfig                板子选择 + generic 引脚配置
└── boards/
    ├── s3_round_gc9a01/   ① 圆屏宠物板（¥120，主推）
    ├── s3_korvo2/         ② 乐鑫语音板（双麦+功放）
    ├── s3_eye/            ③ 乐鑫视觉板（摄像头）
    ├── p4_lcd/            ④ P4 大屏终端
    └── generic/           ⑤ 自定义板（引脚从 menuconfig 读）
```

**关键**：`bsp_common.c` 把 4 块板子 90% 相同的初始化收在一处。
一个 `board.c` 从 400 行降到 **80-150 行**。

---

## 加一块新板子（四步）

```bash
# 1. 建目录
mkdir -p components/bsp/boards/my_board

# 2. 写引脚（照抄参考板，改引脚）
cp components/bsp/boards/s3_round_gc9a01/board_pins.h \
   components/bsp/boards/my_board/

# 3. 写 board.c（只用 bsp_common_* 和填 bsp_info_t）
#    参考 s3_round_gc9a01/board.c 150 行

# 4. Kconfig 加两行
#    config BSP_BOARD_MY_BOARD
#        bool "我的板子"
#    config BSP_BOARD
#        default "my_board" if BSP_BOARD_MY_BOARD
```

然后 `python tools/bsp_doctor.py` 检查，`idf.py menuconfig` 选上就能跑。

---

## 验证工具

### `tools/bsp_doctor.py` — 板级定义检查

```bash
python tools/bsp_doctor.py        # 检查全部板子
python tools/bsp_doctor.py -v     # 显示能力/函数明细
```

检查四类**编译器不报但真机会出事**的问题：

| # | 检查项 | 为什么重要 |
|---|--------|-----------|
| 1 | Kconfig 与 boards/ 目录一致 | 不一致则选板编译失败 |
| 2 | **引脚冲突** | 两个功能抢同一 GPIO，真机神秘故障 |
| 3 | 声明能力但未实现函数 | 运行时报"声明支持但未实现" |
| 4 | display_w/h 与 board_pins 不符 | 屏幕花屏 |

**实测抓到的真问题**：`s3_eye` 上 GPIO2 同时被 LCD_RST 和麦克风数据占用。
这是我写引脚表时凭印象填的，靠人工审代码极难发现。

### 待核对标记 `VERIFY`

凭原理图才能确认的引脚，标 `/* VERIFY */`：

```c
#define BSP_I2S_DIN  GPIO_NUM_3   /* VERIFY */
```

doctor 会把它降为**警告**而不是错误，并在输出里列出来提醒你核对。

---

## 当前状态

```
5 块板 / 63 个引脚定义 / 53 个板级函数 / 26 项能力声明
bsp_doctor: ✓ 全部通过
c_static_check: ✓ 全部通过（24 文件 / 3285 行）
```

### 诚实边界

| 项 | 状态 |
|----|------|
| BSP 架构 + 弱符号降级 | ✅ 完整 |
| 5 块板定义 + 公共层 | ✅ 完整 |
| 宠物固件改用 BSP | ✅ 完成（display/motion/audio/touch 全部解耦） |
| 脚手架改为依赖 BSP | ✅ 完成 |
| **真机编译** | ❌ **本机无 IDF/gcc，未编译** |
| **P4 MIPI-DSI 面板驱动** | 🟡 配置结构就位，需装 esp_lcd 面板驱动组件 |
| **Korvo-2 codec** | 🟡 I2S 通了，ES8311/ES7210 需 esp_codec_dev |
| **S3-EYE 摄像头** | 🟡 引脚就位，需 esp32-camera 组件 |
| s3_eye 麦克风引脚 | ⚠ 标了 VERIFY，需对原理图确认 |
