/*
 * bsp_common.h — 板级公共实现（供各 board.c 复用）
 *
 * ## 为什么需要这层
 *
 * 4 块板子的 GC9A01/ST7789 初始化、LEDC 舵机、I2S 音频
 * 代码 90% 相同，只有引脚和参数不同。
 *
 * 抽掉之后，一块新板子的 board.c 只剩：
 *   引脚定义 → 调用 bsp_common_xxx(引脚) → 填 bsp_info_t
 *
 * 每个 board.c 从 400 行降到 80 行。
 *
 * This file is part of LAAP Hardware SDK, GPL v3.
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ══════════════ SPI LCD ══════════════ */

typedef struct {
    gpio_num_t sclk;
    gpio_num_t mosi;
    gpio_num_t cs;
    gpio_num_t dc;
    gpio_num_t rst;
    gpio_num_t bl;              /* 背光，-1 表示固定接 3.3V 无 PWM */

    uint16_t w;
    uint16_t h;
    bool     invert_color;      /* 多数圆屏需要 true */
    bool     bgr_order;

    int      spi_host;          /* SPI2_HOST / SPI3_HOST */
    uint32_t pclk_hz;

    ledc_timer_t   bl_timer;
    ledc_channel_t bl_ch;

    /** "gc9a01" 或 "st7789" */
    const char *driver;
} bsp_lcd_spi_cfg_t;

/** 初始化 SPI LCD 并注册 LVGL。out_panel 可传 NULL */
esp_err_t bsp_common_lcd_spi_init(const bsp_lcd_spi_cfg_t *cfg, void **out_panel);

/** 背光亮度 0-100（cfg.bl < 0 时返回 NOT_SUPPORTED） */
esp_err_t bsp_common_lcd_set_brightness(ledc_channel_t ch, uint8_t percent);

/* ══════════════ 舵机（LEDC 50Hz）══════════════ */

typedef struct {
    const gpio_num_t     *gpios;
    const ledc_channel_t *channels;
    uint8_t  count;
    ledc_timer_t timer;
} bsp_servo_cfg_t;

esp_err_t bsp_common_servo_init(const bsp_servo_cfg_t *cfg);

/** 设置某个 LEDC 通道的角度 0-180 */
esp_err_t bsp_common_servo_set(ledc_channel_t ch, float deg);

/* ══════════════ I2S 音频 ══════════════ */

typedef struct {
    gpio_num_t bclk;
    gpio_num_t lrck;
    gpio_num_t dout;            /* -1 = 无扬声器 */
    gpio_num_t din;             /* -1 = 无麦克风 */
    uint32_t   sample_rate;
    int        port;            /* I2S_NUM_0 / I2S_NUM_1 */
    bool       mono;
} bsp_i2s_cfg_t;

/** 初始化 I2S，按 dout/din 是否存在决定创建 TX/RX */
esp_err_t bsp_common_i2s_init(const bsp_i2s_cfg_t *cfg,
                              void **out_tx, void **out_rx);

/* ══════════════ GPIO 输入 ══════════════ */

/** 配置为输入（可选下拉/上拉，适合 TTP223 / 按键） */
esp_err_t bsp_common_gpio_in(gpio_num_t pin, bool pulldown, bool pullup);

/* ══════════════ ADC 电池采样 ══════════════ */

typedef struct {
    int      adc_unit;          /* 1 = ADC_UNIT_1 */
    int      channel;           /* ADC_CHANNEL_n */
    float    divider;           /* 分压比，如 2.0 */
    float    v_empty;           /* 空电电压，如 3.3 */
    float    v_full;            /* 满电电压，如 4.2 */
} bsp_battery_cfg_t;

/**
 * 初始化电池采样。
 * @param ctx 输出句柄（内部结构，调用方不要解引用）
 */
esp_err_t bsp_common_battery_init(const bsp_battery_cfg_t *cfg, void **ctx);

/** 读电量百分比 0-100，-1 失败 */
int bsp_common_battery_percent(void *ctx);

#ifdef __cplusplus
}
#endif