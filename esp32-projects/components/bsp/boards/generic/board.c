/*
 * board.c — 通用/自定义板
 *
 * 所有引脚都从 menuconfig 读（CONFIG_BSP_GEN_*），
 * 适合自己画的板子或还没写 BSP 的第三方板。
 *
 * 用法：
 *   idf.py menuconfig → LAAP BSP → Generic Board Pins
 *   把引脚填成你实际的接线，不用改代码。
 */
#include "esp_log.h"
#include "sdkconfig.h"
#include "bsp.h"
#include "bsp_board.h"
#include "bsp_common.h"

static const char *TAG = "bsp.generic";

static void *s_panel = NULL;
static void *s_tx = NULL, *s_rx = NULL;

static const gpio_num_t     s_servo_gpios[2] = {
    (gpio_num_t)CONFIG_BSP_GEN_SERVO0, (gpio_num_t)CONFIG_BSP_GEN_SERVO1
};
static const ledc_channel_t s_servo_chs[2] = {
    LEDC_CHANNEL_2, LEDC_CHANNEL_3
};

static const bsp_info_t s_info = {
    .name = "通用自定义板",
    .id = "generic",
    .chip = "custom",
    .caps = BSP_CAP_DISPLAY | BSP_CAP_TOUCH | BSP_CAP_AUDIO_OUT
          | BSP_CAP_AUDIO_IN | BSP_CAP_SERVO,
    .display_w = 240,
    .display_h = 240,
    .display_driver = "gc9a01（可在 board.c 改）",
    .servo_count = 2,
    .note = "引脚来自 menuconfig，改接线不用改代码",
};

const bsp_info_t *bsp_board_info(void)
{
    return &s_info;
}

esp_err_t bsp_display_init(void)
{
    bsp_lcd_spi_cfg_t cfg = {
        .sclk = (gpio_num_t)CONFIG_BSP_GEN_LCD_SCLK,
        .mosi = (gpio_num_t)CONFIG_BSP_GEN_LCD_MOSI,
        .cs = (gpio_num_t)CONFIG_BSP_GEN_LCD_CS,
        .dc = (gpio_num_t)CONFIG_BSP_GEN_LCD_DC,
        .rst = (gpio_num_t)CONFIG_BSP_GEN_LCD_RST,
        .bl = (gpio_num_t)CONFIG_BSP_GEN_LCD_BL,
        .w = 240, .h = 240,
        .invert_color = true,
        .bgr_order = true,
        .spi_host = 2,
        .pclk_hz = 40000000,
        .bl_timer = LEDC_TIMER_0,
        .bl_ch = LEDC_CHANNEL_0,
        .driver = "gc9a01",
    };
    return bsp_common_lcd_spi_init(&cfg, &s_panel);
}

esp_err_t bsp_display_set_brightness(uint8_t percent)
{
    return bsp_common_lcd_set_brightness(LEDC_CHANNEL_0, percent);
}

void *bsp_display_panel(void) { return s_panel; }

esp_err_t bsp_servo_init(void)
{
    bsp_servo_cfg_t cfg = {
        .gpios = s_servo_gpios,
        .channels = s_servo_chs,
        .count = 2,
        .timer = LEDC_TIMER_1,
    };
    return bsp_common_servo_init(&cfg);
}

esp_err_t bsp_servo_set_angle(uint8_t ch, float deg)
{
    if (ch >= 2) return ESP_ERR_INVALID_ARG;
    return bsp_common_servo_set(s_servo_chs[ch], deg);
}

esp_err_t bsp_audio_init(void)
{
    bsp_i2s_cfg_t cfg = {
        .bclk = (gpio_num_t)CONFIG_BSP_GEN_I2S_BCLK,
        .lrck = (gpio_num_t)CONFIG_BSP_GEN_I2S_LRCK,
        .dout = (gpio_num_t)CONFIG_BSP_GEN_I2S_DOUT,
        .din = (gpio_num_t)CONFIG_BSP_GEN_I2S_DIN,
        .sample_rate = 16000,
        .port = 0,
        .mono = true,
    };
    return bsp_common_i2s_init(&cfg, &s_tx, &s_rx);
}

void *bsp_audio_tx(void) { return s_tx; }
void *bsp_audio_rx(void) { return s_rx; }

esp_err_t bsp_touch_init(void)
{
    return bsp_common_gpio_in((gpio_num_t)CONFIG_BSP_GEN_TOUCH, true, false);
}

bool bsp_touch_pressed(void)
{
    return gpio_get_level((gpio_num_t)CONFIG_BSP_GEN_TOUCH) != 0;
}