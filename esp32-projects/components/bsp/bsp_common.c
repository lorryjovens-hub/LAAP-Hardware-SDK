/*
 * bsp_common.c — 板级公共实现
 *
 * 把 4 块板子 90% 相同的初始化代码收在一处。
 */
#include <string.h>
#include "esp_log.h"
#include "esp_check.h"
#include "driver/spi_master.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lvgl_port.h"
#include "esp_adc/adc_oneshot.h"
#include "bsp_common.h"

static const char *TAG = "bsp.common";

/* ══════════════════════════════════════════════════════════
 *  SPI LCD
 * ══════════════════════════════════════════════════════════ */

esp_err_t bsp_common_lcd_spi_init(const bsp_lcd_spi_cfg_t *cfg, void **out_panel)
{
    if (!cfg || !cfg->driver) return ESP_ERR_INVALID_ARG;

    /* 1. 背光 PWM */
    if (cfg->bl >= 0) {
        ledc_timer_config_t t = {
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .duty_resolution = LEDC_TIMER_10_BIT,
            .timer_num = cfg->bl_timer,
            .freq_hz = 5000,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        ESP_RETURN_ON_ERROR(ledc_timer_config(&t), TAG, "bl timer");

        ledc_channel_config_t c = {
            .gpio_num = cfg->bl,
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = cfg->bl_ch,
            .timer_sel = cfg->bl_timer,
            .duty = 0,
            .hpoint = 0,
        };
        ESP_RETURN_ON_ERROR(ledc_channel_config(&c), TAG, "bl ch");
    }

    /* 2. SPI 总线 */
    spi_bus_config_t bus = {
        .mosi_io_num = cfg->mosi,
        .miso_io_num = -1,
        .sclk_io_num = cfg->sclk,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = cfg->w * 40 * sizeof(uint16_t),
    };
    esp_err_t e = spi_bus_initialize(cfg->spi_host, &bus, SPI_DMA_CH_AUTO);
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {   /* 已初始化也算 OK */
        ESP_LOGE(TAG, "SPI bus: %s", esp_err_to_name(e));
        return e;
    }

    /* 3. Panel IO */
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num = cfg->dc,
        .cs_gpio_num = cfg->cs,
        .pclk_hz = cfg->pclk_hz ? cfg->pclk_hz : 40000000,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_RETURN_ON_ERROR(
        esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)cfg->spi_host,
                                 &io_cfg, &io),
        TAG, "panel io");

    /* 4. Panel 驱动 */
    esp_lcd_panel_dev_config_t pcfg = {
        .reset_gpio_num = cfg->rst,
        .rgb_ele_order = cfg->bgr_order ? LCD_RGB_ELEMENT_ORDER_BGR
                                        : LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };

    esp_lcd_panel_handle_t panel = NULL;
    if (strcmp(cfg->driver, "gc9a01") == 0) {
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_gc9a01(io, &pcfg, &panel),
                            TAG, "gc9a01");
    } else if (strcmp(cfg->driver, "st7789") == 0) {
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7789(io, &pcfg, &panel),
                            TAG, "st7789");
    } else {
        ESP_LOGE(TAG, "未知 LCD 驱动: %s", cfg->driver);
        return ESP_ERR_NOT_SUPPORTED;
    }

    esp_lcd_panel_reset(panel);
    esp_lcd_panel_init(panel);
    if (cfg->invert_color) {
        esp_lcd_panel_invert_color(panel, true);
    }
    esp_lcd_panel_disp_on_off(panel, true);

    /* 5. LVGL 注册（全局只初始化一次 port） */
    static bool lvgl_inited = false;
    if (!lvgl_inited) {
        const lvgl_port_cfg_t lvgl_cfg = ESP_LVGL_PORT_INIT_CONFIG();
        ESP_RETURN_ON_ERROR(lvgl_port_init(&lvgl_cfg), TAG, "lvgl port");
        lvgl_inited = true;
    }

    const lvgl_port_display_cfg_t dcfg = {
        .io_handle = io,
        .panel_handle = panel,
        .buffer_size = cfg->w * 40,
        .double_buffer = true,
        .hres = cfg->w,
        .vres = cfg->h,
        .monochrome = false,
        .rotation = { .swap_xy = false, .mirror_x = false, .mirror_y = false },
        .flags = { .buff_dma = true },
    };
    ESP_RETURN_ON_ERROR(lvgl_port_add_disp(&dcfg), TAG, "lvgl disp");

    if (cfg->bl >= 0) {
        bsp_common_lcd_set_brightness(cfg->bl_ch, 88);
    }

    if (out_panel) *out_panel = (void *)panel;
    ESP_LOGI(TAG, "LCD 就绪 %dx%d (%s)", cfg->w, cfg->h, cfg->driver);
    return ESP_OK;
}

esp_err_t bsp_common_lcd_set_brightness(ledc_channel_t ch, uint8_t percent)
{
    if (percent > 100) percent = 100;
    uint32_t duty = (uint32_t)percent * 1023 / 100;
    ESP_RETURN_ON_ERROR(ledc_set_duty(LEDC_LOW_SPEED_MODE, ch, duty),
                        TAG, "bl duty");
    return ledc_update_duty(LEDC_LOW_SPEED_MODE, ch);
}

/* ══════════════════════════════════════════════════════════
 *  舵机
 * ══════════════════════════════════════════════════════════ */

#define SERVO_MIN_US     500
#define SERVO_MAX_US     2500
#define SERVO_FREQ_HZ    50
#define SERVO_PERIOD_US  20000
#define SERVO_RES_BITS   LEDC_TIMER_14_BIT

static uint32_t servo_duty(float deg)
{
    if (deg < 0) deg = 0;
    if (deg > 180) deg = 180;
    uint32_t us = SERVO_MIN_US +
        (uint32_t)((deg / 180.0f) * (SERVO_MAX_US - SERVO_MIN_US));
    return (uint32_t)((float)us / SERVO_PERIOD_US * ((1 << SERVO_RES_BITS) - 1));
}

esp_err_t bsp_common_servo_init(const bsp_servo_cfg_t *cfg)
{
    if (!cfg || !cfg->gpios || !cfg->channels || cfg->count == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    ledc_timer_config_t t = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = SERVO_RES_BITS,
        .timer_num = cfg->timer,
        .freq_hz = SERVO_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_RETURN_ON_ERROR(ledc_timer_config(&t), TAG, "servo timer");

    for (uint8_t i = 0; i < cfg->count; i++) {
        ledc_channel_config_t c = {
            .gpio_num = cfg->gpios[i],
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = cfg->channels[i],
            .timer_sel = cfg->timer,
            .duty = servo_duty(90.0f),      /* 上电回中，避免猛打 */
            .hpoint = 0,
        };
        ESP_RETURN_ON_ERROR(ledc_channel_config(&c), TAG, "servo ch");
    }

    ESP_LOGI(TAG, "舵机 %u ch 就绪", cfg->count);
    return ESP_OK;
}

esp_err_t bsp_common_servo_set(ledc_channel_t ch, float deg)
{
    ESP_RETURN_ON_ERROR(
        ledc_set_duty(LEDC_LOW_SPEED_MODE, ch, servo_duty(deg)),
        TAG, "servo duty");
    return ledc_update_duty(LEDC_LOW_SPEED_MODE, ch);
}

/* ══════════════════════════════════════════════════════════
 *  I2S
 * ══════════════════════════════════════════════════════════ */

esp_err_t bsp_common_i2s_init(const bsp_i2s_cfg_t *cfg,
                              void **out_tx, void **out_rx)
{
    if (!cfg) return ESP_ERR_INVALID_ARG;
    bool has_tx = (cfg->dout >= 0);
    bool has_rx = (cfg->din >= 0);
    if (!has_tx && !has_rx) return ESP_ERR_NOT_SUPPORTED;

    i2s_chan_config_t chan_cfg =
        I2S_CHANNEL_DEFAULT_CONFIG(cfg->port, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true;

    i2s_chan_handle_t tx = NULL, rx = NULL;
    ESP_RETURN_ON_ERROR(
        i2s_new_channel(&chan_cfg, has_tx ? &tx : NULL, has_rx ? &rx : NULL),
        TAG, "i2s chan");

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(
            cfg->sample_rate ? cfg->sample_rate : 16000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT,
            cfg->mono ? I2S_SLOT_MODE_MONO : I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = cfg->bclk,
            .ws = cfg->lrck,
            .dout = has_tx ? cfg->dout : I2S_GPIO_UNUSED,
            .din = has_rx ? cfg->din : I2S_GPIO_UNUSED,
            .invert_flags = {0},
        },
    };

    if (has_tx) {
        ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(tx, &std_cfg),
                            TAG, "i2s tx");
        ESP_RETURN_ON_ERROR(i2s_channel_enable(tx), TAG, "i2s tx en");
    }
    if (has_rx) {
        ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(rx, &std_cfg),
                            TAG, "i2s rx");
        ESP_RETURN_ON_ERROR(i2s_channel_enable(rx), TAG, "i2s rx en");
    }

    if (out_tx) *out_tx = (void *)tx;
    if (out_rx) *out_rx = (void *)rx;

    ESP_LOGI(TAG, "I2S 就绪 %u Hz %s%s%s",
             (unsigned)(cfg->sample_rate ? cfg->sample_rate : 16000),
             cfg->mono ? "mono" : "stereo",
             has_tx ? " +speaker" : "",
             has_rx ? " +mic" : "");
    return ESP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  GPIO
 * ══════════════════════════════════════════════════════════ */

esp_err_t bsp_common_gpio_in(gpio_num_t pin, bool pulldown, bool pullup)
{
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << pin,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = pullup ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = pulldown ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    return gpio_config(&io);
}

/* ══════════════════════════════════════════════════════════
 *  电池 ADC
 * ══════════════════════════════════════════════════════════ */

typedef struct {
    adc_oneshot_unit_handle_t unit;
    adc_cali_handle_t cali;
    bool cali_ok;
    int channel;
    float divider;
    float v_empty;
    float v_full;
} battery_ctx_t;

esp_err_t bsp_common_battery_init(const bsp_battery_cfg_t *cfg, void **ctx)
{
    if (!cfg || !ctx) return ESP_ERR_INVALID_ARG;

    battery_ctx_t *b = calloc(1, sizeof(battery_ctx_t));
    if (!b) return ESP_ERR_NO_MEM;

    b->channel = cfg->channel;
    b->divider = cfg->divider > 0 ? cfg->divider : 2.0f;
    b->v_empty = cfg->v_empty > 0 ? cfg->v_empty : 3.3f;
    b->v_full = cfg->v_full > 0 ? cfg->v_full : 4.2f;

    adc_oneshot_unit_init_cfg_t ucfg = {
        .unit_id = (adc_unit_t)cfg->adc_unit,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    esp_err_t e = adc_oneshot_new_unit(&ucfg, &b->unit);
    if (e != ESP_OK) { free(b); return e; }

    adc_oneshot_chan_cfg_t ccfg = {
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
    };
    adc_oneshot_config_channel(b->unit, (adc_channel_t)cfg->channel, &ccfg);

    adc_cali_curve_fitting_config_t cal = {
        .unit_id = (adc_unit_t)cfg->adc_unit,
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
    };
    b->cali_ok = (adc_cali_create_scheme_curve_fitting(&cal, &b->cali) == ESP_OK);

    *ctx = b;
    ESP_LOGI(TAG, "电池采样就绪（标定 %s）", b->cali_ok ? "OK" : "未启用");
    return ESP_OK;
}

int bsp_common_battery_percent(void *ctx)
{
    battery_ctx_t *b = (battery_ctx_t *)ctx;
    if (!b || !b->unit) return -1;

    /* 8 次采样取中位数，避开 ADC 噪声 */
    int s[8];
    for (int i = 0; i < 8; i++) {
        if (adc_oneshot_read(b->unit, (adc_channel_t)b->channel, &s[i]) != ESP_OK) {
            return -1;
        }
    }
    for (int i = 1; i < 8; i++) {
        int k = s[i], j = i - 1;
        while (j >= 0 && s[j] > k) { s[j + 1] = s[j]; j--; }
        s[j + 1] = k;
    }
    int raw = (s[3] + s[4]) / 2;

    int mv = raw;
    if (b->cali_ok && adc_cali_raw_to_voltage(b->cali, raw, &mv) != ESP_OK) {
        return -1;
    }
    float vbat = (mv / 1000.0f) * b->divider;

    if (vbat <= b->v_empty) return 0;
    if (vbat >= b->v_full) return 100;
    return (int)((vbat - b->v_empty) / (b->v_full - b->v_empty) * 100.0f);
}