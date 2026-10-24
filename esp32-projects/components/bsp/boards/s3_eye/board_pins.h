/*
 * board_pins.h — ESP32-S3-EYE（乐鑫官方视觉板）
 *
 * 特点：OV2640 摄像头 + 240x240 ST7789 LCD + 麦克风 + 6 按键
 * 没有舵机/电机 —— 它是视觉板
 *
 * 适合：需要"眼睛"的数字生命体（看世界、识别人、读文字）
 */
#pragma once

#include "driver/gpio.h"

/* ── LCD（ST7789 240x240）── */
#define BSP_LCD_SCLK        GPIO_NUM_21
#define BSP_LCD_MOSI        GPIO_NUM_47
#define BSP_LCD_CS          GPIO_NUM_44
#define BSP_LCD_DC          GPIO_NUM_43
#define BSP_LCD_RST         GPIO_NUM_2
#define BSP_LCD_BL          GPIO_NUM_48

/* ── 摄像头 OV2640（DVP 接口）── */
#define BSP_CAM_XCLK        GPIO_NUM_15
#define BSP_CAM_PCLK        GPIO_NUM_13
#define BSP_CAM_VSYNC       GPIO_NUM_6
#define BSP_CAM_HREF        GPIO_NUM_7
#define BSP_CAM_SDA         GPIO_NUM_4     /* SCCB = I2C */
#define BSP_CAM_SCL         GPIO_NUM_5
#define BSP_CAM_D0          GPIO_NUM_11
#define BSP_CAM_D1          GPIO_NUM_9
#define BSP_CAM_D2          GPIO_NUM_8
#define BSP_CAM_D3          GPIO_NUM_10
#define BSP_CAM_D4          GPIO_NUM_12
#define BSP_CAM_D5          GPIO_NUM_18
#define BSP_CAM_D6          GPIO_NUM_17
#define BSP_CAM_D7          GPIO_NUM_16
#define BSP_CAM_PWDN        GPIO_NUM_NC
#define BSP_CAM_RESET       GPIO_NUM_NC

/* ── 麦克风（简单模拟/PCM，此板无 codec）── */
/* ⚠ VERIFY: 以下 I2S 引脚需对照你的板子原理图确认。
 *   最初写的 GPIO2 与 LCD_RST 冲突（bsp_doctor 查出的），已改到 GPIO3。
 *   ESP32-S3-EYE 历史悠久，不同批次接线有差异。 */
#define BSP_I2S_BCLK        GPIO_NUM_41
#define BSP_I2S_LRCK        GPIO_NUM_42
#define BSP_I2S_DIN         GPIO_NUM_3      /* VERIFY */
#define BSP_I2S_DOUT        (-1)            /* 此板无扬声器输出 */

#define BSP_I2S_SAMPLE_RATE 16000

/* ── 资源 ── */
#define BSP_LEDC_TIMER_BL   LEDC_TIMER_0
#define BSP_LEDC_CH_BL      LEDC_CHANNEL_0