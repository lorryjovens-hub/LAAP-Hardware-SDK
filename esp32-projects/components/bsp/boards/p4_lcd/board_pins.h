/*
 * board_pins.h — ESP32-P4 + LCD（大屏终端）
 *
 * ## ⚠ P4 最重要的限制：没有内置 WiFi/蓝牙
 *
 * ESP32-P4 是纯计算芯片（RISC-V 双核 400MHz + MIPI-DSI/CSI + H.264 编码），
 * **必须外挂 ESP32-C6 模组**才有网络。官方 ESP32-P4-EYE 板就是这样做的。
 *
 * 所以这块板的网络不归 BSP 管 —— 要用 P4 的 WiFi，需要：
 *   1. 硬件上 P4 通过 SDIO/SPI 连 C6
 *   2. 软件上用 esp_hosted 组件（ESP-Hosted-MCU）
 *
 * 本 BSP 只负责显示/音频/触摸，网络留给应用层用 esp_hosted。
 *
 * ## 引脚（以微雪 ESP32-P4-WIFI6-Touch-LCD 系列为参考）
 *
 * 实际接线随板子差异大，换板务必对照原理图改。
 */
#pragma once

#include "driver/gpio.h"

/* ── MIPI-DSI 屏（部分 P4 板用 SPI 小屏，这里按 DSI 给）── */
#define BSP_MIPI_DSI_LANE_NUM     2
#define BSP_MIPI_DSI_LANE_MBPS    1000
#define BSP_LCD_RST               GPIO_NUM_27
#define BSP_LCD_BL                GPIO_NUM_26

/* ── 触摸（I2C，GT911）── */
#define BSP_TOUCH_INT             GPIO_NUM_25
#define BSP_TOUCH_RST             GPIO_NUM_24
#define BSP_TOUCH_I2C_ADDR        0x5D

/* ── I2C（触摸 + 传感器）── */
#define BSP_I2C_SDA               GPIO_NUM_7
#define BSP_I2C_SCL               GPIO_NUM_8

/* ── 音频（ES8311 codec，经 I2C 配置）── */
#define BSP_I2S_MCLK              GPIO_NUM_13
#define BSP_I2S_BCLK              GPIO_NUM_12
#define BSP_I2S_LRCK              GPIO_NUM_10
#define BSP_I2S_DOUT              GPIO_NUM_9
#define BSP_I2S_DIN               GPIO_NUM_11
#define BSP_I2S_SAMPLE_RATE       16000

/* ── 资源 ── */
#define BSP_LEDC_TIMER_BL         LEDC_TIMER_0
#define BSP_LEDC_CH_BL            LEDC_CHANNEL_0

/* ── 屏幕规格 ── */
#define BSP_LCD_W                 1024
#define BSP_LCD_H                 600