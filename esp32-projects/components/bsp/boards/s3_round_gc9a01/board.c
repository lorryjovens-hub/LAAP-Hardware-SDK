/*
 * board.c — ESP32-S3 + GC9A01 圆屏宠物板
 *
 * 自组方案 ¥120：S3(N16R8) + GC9A01 圆屏 + 2×SG90 + INMP441 + MAX98357 + TTP223
 */
#include "esp_log.h"
#include "bsp.h"
#include "bsp_board.h"
#include "bsp_common.h"
#include "board_pins.h"

static const char *TAG = "bsp.s3round";

/* ── 句柄 ── */
static void *s_panel = NULL;
static void *s_tx = NULL, *s_rx = NULL;
static void *s_batt = NULL;

/* ── 舵机标定 ── */
static struct { float offset; bool invert; } s_cal[2] = { {0, false}, {0, false} };

static const gpio_num_t     s_servo_gpios[2] = { BSP_SERVO0_GPIO, BSP_SERVO1_GPIO };
static const ledc_channel_t s_servo_chs[2]   = { BSP_LEDC_CH_SERVO0, BSP_LEDC_CH_SERVO1 };

/* ══════════════ 板级信息 ══════════════ */

static const bsp_info_t s_info = {
    .name = "ESP32-S3 圆屏宠物板",
    .id = "s3_round_gc9a01",
    .chip = "esp32s3",
    .caps = BSP_CAP_DISPLAY | BSP_CAP_TOUCH | BSP_CAP_AUDIO_OUT
          | BSP_CAP_AUDIO_IN | BSP_CAP_SERVO
          | (BSP_BATTERY_ENABLE ? BSP_CAP_BATTERY : 0),
    .display_w = 240,
    .display_h = 240,
    .display_driver = "gc9a01",
    .servo_count = 2,
    .note = "舵机需外接 5V/2A 独立电源 + 共地",
};

const bsp_info_t *bsp_board_info(void)
{
    return &s_info;
}

/* ══════════════ 显示 ══════════════ */

esp_err_t bsp_display_init(void)
{
    bsp_lcd_spi_cfg_t cfg = {
        .sclk = BSP_LCD_SCLK,
        .mosi = BSP_LCD_MOSI,
        .cs = BSP_LCD_CS,
        .dc = BSP_LCD_DC,
        .rst = BSP_LCD_RST,
        .bl = BSP_LCD_BL,
        .w = 240, .h = 240,
        .invert_color = true,
        .bgr_order = true,
        .spi_host = 2,                       /* SPI2_HOST */
        .pclk_hz = 40000000,
        .bl_timer = BSP_LEDC_TIMER_BL,
        .bl_ch = BSP_LEDC_CH_BL,
        .driver = "gc9a01",
    };
    return bsp_common_lcd_spi_init(&cfg, &s_panel);
}

esp_err_t bsp_display_set_brightness(uint8_t percent)
{
    return bsp_common_lcd_set_brightness(BSP_LEDC_CH_BL, percent);
}

void *bsp_display_panel(void) { return s_panel; }

/* ══════════════ 舵机 ══════════════ */

esp_err_t bsp_servo_init(void)
{
    bsp_servo_cfg_t cfg = {
        .gpios = s_servo_gpios,
        .channels = s_servo_chs,
        .count = 2,
        .timer = BSP_LEDC_TIMER_SERVO,
    };
    return bsp_common_servo_init(&cfg);
}

esp_err_t bsp_servo_set_angle(uint8_t ch, float deg)
{
    if (ch >= 2) return ESP_ERR_INVALID_ARG;
    float d = deg + s_cal[ch].offset;
    if (s_cal[ch].invert) d = 180.0f - d;
    return bsp_common_servo_set(s_servo_chs[ch], d);
}

esp_err_t bsp_servo_calibrate(uint8_t ch, float offset, bool invert)
{
    if (ch >= 2) return ESP_ERR_INVALID_ARG;
    s_cal[ch].offset = offset;
    s_cal[ch].invert = invert;
    ESP_LOGI(TAG, "舵机 %u 标定 offset=%.1f invert=%d", ch, offset, invert);
    return ESP_OK;
}

/* ══════════════ 音频 ══════════════ */

esp_err_t bsp_audio_init(void)
{
    bsp_i2s_cfg_t cfg = {
        .bclk = BSP_I2S_BCLK,
        .lrck = BSP_I2S_LRCK,
        .dout = BSP_I2S_DOUT,
        .din = BSP_I2S_DIN,
        .sample_rate = BSP_I2S_SAMPLE_RATE,
        .port = 0,
        .mono = true,
    };
    return bsp_common_i2s_init(&cfg, &s_tx, &s_rx);
}

void *bsp_audio_tx(void) { return s_tx; }
void *bsp_audio_rx(void) { return s_rx; }
uint32_t bsp_audio_sample_rate(void) { return BSP_I2S_SAMPLE_RATE; }

/* ══════════════ 触摸 ══════════════ */

esp_err_t bsp_touch_init(void)
{
    esp_err_t e = bsp_common_gpio_in(BSP_TOUCH_GPIO, true, false);
    if (e == ESP_OK) ESP_LOGI(TAG, "触摸就绪 TTP223");
    return e;
}

bool bsp_touch_pressed(void)
{
    return gpio_get_level(BSP_TOUCH_GPIO) != 0;
}

/* ══════════════ 电池 ══════════════ */

esp_err_t bsp_board_init(void)
{
#if BSP_BATTERY_ENABLE
    bsp_battery_cfg_t cfg = {
        .adc_unit = 1,
        .channel = BSP_BATTERY_ADC,
        .divider = BSP_BATTERY_DIVIDER,
        .v_empty = 3.3f,
        .v_full = 4.2f,
    };
    esp_err_t e = bsp_common_battery_init(&cfg, &s_batt);
    if (e != ESP_OK) {
        ESP_LOGW(TAG, "电池采样初始化失败（不影响其它功能）");
    }
    return ESP_OK;
#else
    return ESP_OK;
#endif
}

int bsp_battery_percent(void)
{
#if BSP_BATTERY_ENABLE
    return bsp_common_battery_percent(s_batt);
#else
    return -1;
#endif
}

int bsp_battery_charging(void) { return -1; }