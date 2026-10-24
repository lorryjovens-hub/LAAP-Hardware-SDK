/*
 * bsp_types.h — BSP 公共类型
 *
 * ## 设计原则
 *
 * BSP 不是"把所有外设实现一遍"，是回答两个问题：
 *   1. 这块板子上有什么？（能力清单 caps）
 *   2. 怎么用？（每个能力的 init + 句柄）
 *
 * 应用代码只依赖 bsp.h，**换板子不改一行**。
 *
 * This file is part of LAAP Hardware SDK, GPL v3.
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ══════════════ 板子能力位 ══════════════ */
#define BSP_CAP_DISPLAY     (1u << 0)   /* 有屏幕 */
#define BSP_CAP_TOUCH       (1u << 1)   /* 触摸输入（屏触或独立触摸片） */
#define BSP_CAP_AUDIO_OUT   (1u << 2)   /* 扬声器 */
#define BSP_CAP_AUDIO_IN    (1u << 3)   /* 麦克风 */
#define BSP_CAP_CAMERA      (1u << 4)   /* 摄像头 */
#define BSP_CAP_SERVO       (1u << 5)   /* 舵机（云台/腿） */
#define BSP_CAP_MOTOR       (1u << 6)   /* 直流电机（底盘） */
#define BSP_CAP_IMU         (1u << 7)   /* 加速度/陀螺仪 */
#define BSP_CAP_BATTERY     (1u << 8)   /* 电池检测 */
#define BSP_CAP_BUTTON      (1u << 9)   /* 物理按键 */
#define BSP_CAP_LED         (1u << 10)  /* RGB LED */
#define BSP_CAP_SDCARD      (1u << 11)  /* SD 卡 */
#define BSP_CAP_I2C         (1u << 12)  /* 可用 I2C 总线 */
#define BSP_CAP_EXPANDER    (1u << 13)  /* I/O 扩展芯片（如 PCA9557/TCA9554） */

/* ══════════════ 板子信息 ══════════════ */
typedef struct {
    const char *name;           /* 如 "ESP32-S3 圆屏宠物板" */
    const char *id;             /* 如 "s3_round_gc9a01" */
    const char *chip;           /* "esp32s3" / "esp32p4" / ... */
    uint32_t caps;              /* BSP_CAP_* 位掩码 */

    /* 显示规格（无屏则为 0） */
    uint16_t display_w;
    uint16_t display_h;
    const char *display_driver; /* "gc9a01" / "st7789" / ... */

    /* 舵机通道数（无则 0） */
    uint8_t servo_count;

    /* 备注（供电要求等关键提醒） */
    const char *note;
} bsp_info_t;

/* ══════════════ 舵机通道语义 ══════════════ */
typedef enum {
    BSP_SERVO_0 = 0,
    BSP_SERVO_1 = 1,
    BSP_SERVO_2 = 2,
    BSP_SERVO_3 = 3,
    BSP_SERVO_MAX = 4,
} bsp_servo_ch_t;

#ifdef __cplusplus
}
#endif