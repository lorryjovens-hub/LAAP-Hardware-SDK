/*
 * board_pins.h — ESP32-S3-Korvo-2（乐鑫官方语音开发板）
 *
 * ## 这块板的特点
 *
 * - 双麦克风阵列（ES7210 ADC）+ ES8311 codec + 功放
 * - 240x240 ST7789 LCD（SPI）
 * - 6 个按键、SD 卡、3 个 LED
 * - **没有舵机**（它是语音板，不是运动板）
 *
 * 适合：纯语音交互场景（桌面音箱型数字生命体）
 *
 * ## 音频链路的坑
 *
 * Korvo-2 的音频不是直接接 I2S 麦/功放，要经过 ES7210/ES8311 codec，
 * 必须先用 I2C 配置 codec 寄存器。这部分需要 esp_codec_dev 组件：
 *
 *     idf.py add-dependency espressif/esp_codec_dev
 *
 * 本文件给出 I2S 引脚，codec 初始化见 board.c 的说明。
 */
#pragma once

#include "driver/gpio.h"

/* ── LCD（ST7789 240x240）── */
#define BSP_LCD_SCLK        GPIO_NUM_21
#define BSP_LCD_MOSI        GPIO_NUM_47
#define BSP_LCD_CS          GPIO_NUM_44
#define BSP_LCD_DC          GPIO_NUM_43
#define BSP_LCD_RST         GPIO_NUM_2
#define BSP_LCD_BL          GPIO_NUM_1

/* ── I2S（经 codec）── */
#define BSP_I2S_MCLK        GPIO_NUM_16
#define BSP_I2S_BCLK        GPIO_NUM_9
#define BSP_I2S_LRCK        GPIO_NUM_45
#define BSP_I2S_DOUT        GPIO_NUM_8     /* → ES8311 DAC */
#define BSP_I2S_DIN         GPIO_NUM_10    /* ← ES7210 ADC */

/* ── I2C（codec 控制 + 扩展 IO）── */
#define BSP_I2C_SDA         GPIO_NUM_17
#define BSP_I2C_SCL         GPIO_NUM_18
#define BSP_ES8311_ADDR     0x18
#define BSP_ES7210_ADDR     0x40

/* ── 按键（ADC 键盘，接 GPIO5）── */
#define BSP_BUTTON_ADC      GPIO_NUM_5

/* ── 音频参数 ── */
#define BSP_I2S_SAMPLE_RATE 16000

/* ── 资源 ── */
#define BSP_LEDC_TIMER_BL   LEDC_TIMER_0
#define BSP_LEDC_CH_BL      LEDC_CHANNEL_0