/*
 * bsp.h — LAAP 统一板级接口
 *
 * ## 应用代码怎么写（永远这样写，不管什么板子）
 *
 * ```c
 * void app_main(void) {
 *     ESP_ERROR_CHECK(bsp_init());
 *
 *     if (bsp_has_cap(BSP_CAP_DISPLAY)) {
 *         display_init();          // 内部调 bsp_display_*()
 *     }
 *     if (bsp_has_cap(BSP_CAP_SERVO)) {
 *         motion_init();           // 内部调 bsp_servo_*()
 *     }
 *     if (bsp_has_cap(BSP_CAP_AUDIO_IN)) {
 *         audio_init();
 *     }
 *     ...
 * }
 * ```
 *
 * 换板子只改 `idf.py menuconfig` 里的 Board Selection，代码不动。
 *
 * ## 能力降级
 *
 * 买了便宜的板子没有屏幕？`bsp_has_cap(BSP_CAP_DISPLAY)` 返回 false，
 * display_init() 里自然跳过，其它功能照常跑。不需要 #ifdef 满天飞。
 *
 * This file is part of LAAP Hardware SDK, GPL v3.
 */
#pragma once

#include "bsp_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ══════════════════════════════════════════════════════════
 *  板子信息与能力
 * ══════════════════════════════════════════════════════════ */

/** 当前板子的信息（编译期确定，永远非 NULL） */
const bsp_info_t *bsp_get_info(void);

/** 是否有某项能力 */
bool bsp_has_cap(uint32_t cap);

/** 打印板子信息（开机诊断用） */
void bsp_print_info(void);

/* ══════════════════════════════════════════════════════════
 *  初始化
 * ══════════════════════════════════════════════════════════ */

/**
 * 初始化板子（按能力自动初始化所有可用外设）。
 * 幂等：重复调用安全。
 */
esp_err_t bsp_init(void);

/** 释放（低功耗/重启前） */
esp_err_t bsp_deinit(void);

/* ══════════════════════════════════════════════════════════
 *  显示
 * ══════════════════════════════════════════════════════════ */

/** 初始化 LCD（含 LVGL 注册）。无屏返回 ESP_ERR_NOT_SUPPORTED */
esp_err_t bsp_display_init(void);

/** 背光亮度 0-100 */
esp_err_t bsp_display_set_brightness(uint8_t percent);

/** 屏幕尺寸（无屏返回 0） */
uint16_t bsp_display_width(void);
uint16_t bsp_display_height(void);

/** 底层 panel 句柄（esp_lcd_panel_handle_t，无屏为 NULL） */
void *bsp_display_panel(void);

/* ══════════════════════════════════════════════════════════
 *  舵机（云台 / 腿）
 * ══════════════════════════════════════════════════════════ */

/** 初始化舵机 PWM。无舵机返回 ESP_ERR_NOT_SUPPORTED */
esp_err_t bsp_servo_init(void);

/** 设置角度 0-180。ch 越界或该通道不存在返回错误 */
esp_err_t bsp_servo_set_angle(uint8_t ch, float deg);

/** 舵机数量（0 表示没有） */
uint8_t bsp_servo_count(void);

/**
 * 舵机标定（真机必做）。
 * @param ch        通道
 * @param offset    中位偏移（度）
 * @param invert    方向反转
 */
esp_err_t bsp_servo_calibrate(uint8_t ch, float offset, bool invert);

/* ══════════════════════════════════════════════════════════
 *  音频
 * ══════════════════════════════════════════════════════════ */

/** 初始化 I2S 麦克风 + 功放（按能力） */
esp_err_t bsp_audio_init(void);

/** I2S TX 句柄（扬声器），无则 NULL */
void *bsp_audio_tx(void);

/** I2S RX 句柄（麦克风），无则 NULL */
void *bsp_audio_rx(void);

/** 采样率（板子可能固定，如 16000） */
uint32_t bsp_audio_sample_rate(void);

/* ══════════════════════════════════════════════════════════
 *  触摸
 * ══════════════════════════════════════════════════════════ */

esp_err_t bsp_touch_init(void);

/** 是否被按下（屏触或独立触摸片） */
bool bsp_touch_pressed(void);

/* ══════════════════════════════════════════════════════════
 *  I2C 总线（IMU / 传感器共用）
 * ══════════════════════════════════════════════════════════ */

esp_err_t bsp_i2c_init(void);

/** i2c_master_bus_handle_t，无则 NULL */
void *bsp_i2c_bus(void);

/* ══════════════════════════════════════════════════════════
 *  电源与输入
 * ══════════════════════════════════════════════════════════ */

/** 电量百分比 0-100，-1 表示不支持 */
int bsp_battery_percent(void);

/** 是否在充电，-1 表示未知 */
int bsp_battery_charging(void);

/** 按键是否按下（内部消抖） */
bool bsp_button_pressed(void);

/* ══════════════════════════════════════════════════════════
 *  周期任务
 * ══════════════════════════════════════════════════════════ */

/** 周期调用：按键消抖、电池采样等（建议 20-50ms 一次，很轻） */
void bsp_tick(void);

#ifdef __cplusplus
}
#endif