/*
 * board_pins.h — ESP32-S3 + GC9A01 圆屏宠物板
 *
 * ## 接线表（自组 ¥120 方案）
 *
 * ┌────────────┬──────────┬────────────────────────────────┐
 * │ 器件        │ ESP32-S3 │ 说明                            │
 * ├────────────┼──────────┼────────────────────────────────┤
 * │ GC9A01 SCK  │ GPIO12   │ SPI2                            │
 * │ GC9A01 MOSI │ GPIO11   │                                 │
 * │ GC9A01 CS   │ GPIO10   │                                 │
 * │ GC9A01 DC   │ GPIO9    │                                 │
 * │ GC9A01 RST  │ GPIO8    │                                 │
 * │ 背光        │ GPIO7    │ PWM 调光                        │
 * │ SG90 Pan    │ GPIO4    │ 水平舵机                        │
 * │ SG90 Tilt   │ GPIO5    │ 俯仰舵机                        │
 * │ TTP223 触摸 │ GPIO6    │ 摸头检测                        │
 * │ INMP441 SCK │ GPIO18   │ 麦克风 BCLK                     │
 * │ INMP441 WS  │ GPIO17   │ 麦克风 LRCK                     │
 * │ INMP441 SD  │ GPIO16   │ 麦克风数据（→ MCU）             │
 * │ MAX98357 DIN│ GPIO19   │ 功放数据（← MCU）               │
 * │ MPU6050 SDA │ GPIO15   │ IMU（可选）                     │
 * │ MPU6050 SCL │ GPIO16*  │ ⚠ 与麦克风冲突，见下方警告       │
 * │ 电池采样    │ GPIO1    │ ADC1_CH0，需 1:2 分压           │
 * └────────────┴──────────┴────────────────────────────────┘
 *
 * ## ⚠ 两个真实硬件坑
 *
 * 1. **I2S 麦克风和 I2C 只能复用引脚**：S3 的 GPIO 紧张，
 *    INMP441 只需要 3 根（BCLK/WS/SD），I2C 用 GPIO15/16 会和麦克风 SD 撞。
 *    解决：IMU 改用 I2C 的另两个脚（GPIO47/48 在 S3 上可用），或
 *    不用 IMU。此板默认 IMU 关闭，需要的话把 IMU_SDA/SCL 改成 47/48。
 *
 * 2. **舵机电源必须独立**：两个 SG90 堵转总电流约 1.5A，
 *    从开发板 3.3V 取电会瞬间掉压重启。
 *    必须外接 5V/2A 电源 + 共地。
 */
#pragma once

#include "driver/gpio.h"

/* ── 显示（GC9A01 240x240 SPI）── */
#define BSP_LCD_SCLK        GPIO_NUM_12
#define BSP_LCD_MOSI        GPIO_NUM_11
#define BSP_LCD_CS          GPIO_NUM_10
#define BSP_LCD_DC          GPIO_NUM_9
#define BSP_LCD_RST         GPIO_NUM_8
#define BSP_LCD_BL          GPIO_NUM_7

/* ── 舵机（LEDC PWM）── */
#define BSP_SERVO0_GPIO     GPIO_NUM_4
#define BSP_SERVO1_GPIO     GPIO_NUM_5

/* ── 触摸 ── */
#define BSP_TOUCH_GPIO      GPIO_NUM_6

/* ── I2S 音频 ── */
#define BSP_I2S_BCLK        GPIO_NUM_18
#define BSP_I2S_LRCK        GPIO_NUM_17
#define BSP_I2S_DOUT        GPIO_NUM_19   /* → MAX98357 DIN */
#define BSP_I2S_DIN         GPIO_NUM_16   /* ← INMP441 SD */

/* ── IMU（可选，默认关闭避免与麦克风冲突）── */
#define BSP_IMU_ENABLE      0
#define BSP_IMU_SDA         GPIO_NUM_47
#define BSP_IMU_SCL         GPIO_NUM_48

/* ── 电池采样 ── */
#define BSP_BATTERY_ENABLE  1
#define BSP_BATTERY_ADC     ADC_CHANNEL_0    /* GPIO1 */
#define BSP_BATTERY_DIVIDER 2.0f             /* 1:2 分压 */

/* ── 音频参数 ── */
#define BSP_I2S_SAMPLE_RATE 16000

/* ── 硬件资源分配 ── */
#define BSP_LEDC_TIMER_BL       LEDC_TIMER_0
#define BSP_LEDC_CH_BL          LEDC_CHANNEL_0
#define BSP_LEDC_TIMER_SERVO    LEDC_TIMER_1
#define BSP_LEDC_CH_SERVO0      LEDC_CHANNEL_2
#define BSP_LEDC_CH_SERVO1      LEDC_CHANNEL_3