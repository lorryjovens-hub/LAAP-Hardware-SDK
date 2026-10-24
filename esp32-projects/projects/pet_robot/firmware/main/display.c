/*
 * display.c — GC9A01 圆屏 + LVGL 眼睛表情系统
 *
 * ## 为什么眼睛是宠物最重要的部分
 *
 * 桌面宠物的运动只有 2 个自由度（pan/tilt），动作幅度有限。
 * 真正让人觉得"它活着"的，是屏幕上的眼睛：
 *   · 会眨眼（随机，3-8 秒一次）
 *   · 瞳孔会跟着人移动
 *   · 说话时眼睛有波形
 *   · 开心时弯成弧线
 *   · 睡觉时闭上、呼吸变慢
 *
 * 所以这个文件的代码量比 motion.c 大，是刻意的。
 *
 * ## 表情状态机
 *
 *   IDLE      呼吸缩放 + 随机眨眼 + 瞳孔缓慢游移
 *   LISTENING 瞳孔放大、看向声源
 *   THINKING  瞳孔左右缓移、偶尔上翻
 *   SPEAKING  下方环形波形随音量
 *   HAPPY     眼睛弯成 ^ ^
 *   SLEEP     闭眼 + 呼吸更慢
 *
 * This file is part of LAAP Mobile Hardware, GPL v3.
 */
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lvgl_port.h"
#include "esp_log.h"
#include "lvgl.h"

#include "display.h"

#define TAG "eyes"

/* ── GC9A01 圆屏 240x240 ─────────────────────────────
 * 引脚按你的板改；下面是常见的接法 */
#define PIN_LCD_SCLK   GPIO_NUM_12
#define PIN_LCD_MOSI   GPIO_NUM_11
#define PIN_LCD_CS     GPIO_NUM_10
#define PIN_LCD_DC     GPIO_NUM_9
#define PIN_LCD_RST    GPIO_NUM_8
#define PIN_LCD_BL     GPIO_NUM_7      /* 背光，PWM 调光 */

#define LCD_H_RES      240
#define LCD_V_RES      240
#define LCD_BL_LEDC    LEDC_CHANNEL_0

/* ── 眼睛几何 ─────────────────────────────────── */
#define EYE_W          62          /* 眼睛宽 */
#define EYE_H          74          /* 眼睛高（睁眼） */
#define EYE_GAP        26          /* 两眼间距 */
#define EYE_RADIUS     28          /* 圆角（够大 = 椭圆） */
#define PUPIL_W        26
#define PUPIL_H        30

static lv_obj_t *s_eye_l = NULL;
static lv_obj_t *s_eye_r = NULL;
static lv_obj_t *s_pupil_l = NULL;
static lv_obj_t *s_pupil_r = NULL;
static lv_obj_t *s_wave = NULL;        /* 说话波形（一排小竖条） */
static lv_obj_t *s_status = NULL;      /* 顶部状态文字 */
static lv_obj_t *s_subtitle = NULL;    /* 字幕 */

static volatile expression_t s_expr = EXPR_IDLE;
static volatile uint8_t s_blink_h = EYE_H;  /* 当前眼睛高度（眨眼动画用） */

/* 瞳孔注视偏移（-1..1 归一化） */
static volatile float s_gaze_x = 0.0f;
static volatile float s_gaze_y = 0.0f;

/* 波形条（12 根） */
#define WAVE_BARS 12
static lv_obj_t *s_bars[WAVE_BARS];
static volatile uint8_t s_volume = 0;      /* 0-100，说话音量 */

/* ─────────────────── 背光 PWM ─────────────────── */

static void backlight_init(void)
{
    ledc_timer_config_t t = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = 5000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&t);
    ledc_channel_config_t c = {
        .gpio_num = PIN_LCD_BL,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LCD_BL_LEDC,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };
    ledc_channel_config(&c);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LCD_BL_LEDC, 900);  /* ~88% */
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LCD_BL_LEDC);
}

void display_set_brightness(uint8_t percent)
{
    if (percent > 100) percent = 100;
    uint32_t duty = percent * 1023 / 100;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LCD_BL_LEDC, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LCD_BL_LEDC);
}

/* ─────────────────── 眼睛创建 ─────────────────── */

static lv_obj_t *make_eye(lv_obj_t *parent, int x)
{
    lv_obj_t *eye = lv_obj_create(parent);
    lv_obj_set_size(eye, EYE_W, EYE_H);
    lv_obj_set_pos(eye, x, LCD_V_RES / 2 - EYE_H / 2 - 18);
    lv_obj_set_style_radius(eye, EYE_RADIUS, 0);
    lv_obj_set_style_bg_color(eye, lv_color_hex(0x0b1220), 0);
    lv_obj_set_style_bg_opa(eye, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(eye, lv_color_hex(0x5eead4), 0);
    lv_obj_set_style_border_width(eye, 3, 0);
    lv_obj_set_style_shadow_color(eye, lv_color_hex(0x22d3ee), 0);
    lv_obj_set_style_shadow_width(eye, 18, 0);
    lv_obj_set_style_shadow_opa(eye, LV_OPA_50, 0);
    lv_obj_remove_flag(eye, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(eye, 0, 0);
    return eye;
}

static lv_obj_t *make_pupil(lv_obj_t *parent_eye)
{
    lv_obj_t *p = lv_obj_create(parent_eye);
    lv_obj_set_size(p, PUPIL_W, PUPIL_H);
    lv_obj_set_style_radius(p, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(p, lv_color_hex(0x22d3ee), 0);
    lv_obj_set_style_bg_opa(p, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(p, 0, 0);
    lv_obj_remove_flag(p, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(p, LV_ALIGN_CENTER, 0, 0);
    return p;
}

void display_init(void)
{
    backlight_init();

    /* ── SPI + GC9A01 ── */
    spi_bus_config_t bus = {
        .mosi_io_num = PIN_LCD_MOSI,
        .miso_io_num = -1,
        .sclk_io_num = PIN_LCD_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_H_RES * 80 * sizeof(uint16_t),
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num = PIN_LCD_DC,
        .cs_gpio_num = PIN_LCD_CS,
        .pclk_hz = 40 * 1000 * 1000,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(
        (esp_lcd_spi_bus_handle_t)SPI2_HOST, &io_cfg, &io));

    esp_lcd_panel_handle_t panel = NULL;
    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = PIN_LCD_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_gc9a01(io, &panel_cfg, &panel));
    esp_lcd_panel_reset(panel);
    esp_lcd_panel_init(panel);
    esp_lcd_panel_invert_color(panel, true);
    esp_lcd_panel_disp_on_off(panel, true);

    /* ── LVGL ── */
    const lvgl_port_cfg_t lvgl_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    lvgl_port_init(&lvgl_cfg);

    const lvgl_port_display_cfg_t disp_cfg = {
        .io_handle = io,
        .panel_handle = panel,
        .buffer_size = LCD_H_RES * 40,
        .double_buffer = true,
        .hres = LCD_H_RES,
        .vres = LCD_V_RES,
        .monochrome = false,
        .rotation = {
            .swap_xy = false,
            .mirror_x = false,
            .mirror_y = false,
        },
        .flags = {
            .buff_dma = true,
        },
    };
    lvgl_port_add_disp(&disp_cfg);

    /* ── 构建眼睛 UI ── */
    lvgl_port_lock(0);
    lv_obj_t *scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x05080f), 0);
    lv_obj_clean(scr);

    s_eye_l = make_eye(scr, LCD_H_RES / 2 - EYE_GAP / 2 - EYE_W);
    s_eye_r = make_eye(scr, LCD_H_RES / 2 + EYE_GAP / 2);
    s_pupil_l = make_pupil(s_eye_l);
    s_pupil_r = make_pupil(s_eye_r);

    /* 说话波形：底部一排竖条 */
    for (int i = 0; i < WAVE_BARS; i++) {
        s_bars[i] = lv_obj_create(scr);
        lv_obj_set_size(s_bars[i], 5, 8);
        lv_obj_set_pos(s_bars[i],
                       LCD_H_RES / 2 - (WAVE_BARS * 9) / 2 + i * 9,
                       LCD_V_RES - 46);
        lv_obj_set_style_radius(s_bars[i], 3, 0);
        lv_obj_set_style_bg_color(s_bars[i], lv_color_hex(0x22d3ee), 0);
        lv_obj_set_style_bg_opa(s_bars[i], LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(s_bars[i], 0, 0);
        lv_obj_add_flag(s_bars[i], LV_OBJ_FLAG_HIDDEN);
    }

    /* 状态文字 + 字幕 */
    s_status = lv_label_create(scr);
    lv_obj_set_style_text_color(s_status, lv_color_hex(0x64748b), 0);
    lv_obj_set_style_text_font(s_status, &lv_font_montserrat_12, 0);
    lv_obj_align(s_status, LV_ALIGN_TOP_MID, 0, 10);
    lv_label_set_text(s_status, "LAAP");

    s_subtitle = lv_label_create(scr);
    lv_obj_set_width(s_subtitle, LCD_H_RES - 24);
    lv_obj_set_style_text_color(s_subtitle, lv_color_hex(0x94a3b8), 0);
    lv_obj_set_style_text_font(s_subtitle, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(s_subtitle, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_subtitle, LV_ALIGN_BOTTOM_MID, 0, -14);
    lv_label_set_long_mode(s_subtitle, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_label_set_text(s_subtitle, "");

    lvgl_port_unlock();

    ESP_LOGI(TAG, "眼睛就绪 %dx%d", LCD_H_RES, LCD_V_RES);
}

/* ─────────────────── 眨眼动画 ─────────────────── */

static void blink_anim_cb(lv_anim_t *a)
{
    int h = lv_map(a->act_time, 0, a->duration, EYE_H, 6);
    /* 前一瞬快速闭合，后半缓慢张开 */
    if (a->act_time > a->duration / 2) {
        h = lv_map(a->act_time, a->duration / 2, a->duration, 6, EYE_H);
    }
    s_blink_h = (uint8_t)h;
    if (s_eye_l) lv_obj_set_height(s_eye_l, h);
    if (s_eye_r) lv_obj_set_height(s_eye_r, h);
}

static void do_blink(void)
{
    if (s_expr == EXPR_SLEEP) return;
    lvgl_port_lock(0);
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, s_eye_l);
    lv_anim_set_values(&a, 0, 100);
    lv_anim_set_duration(&a, 260);
    lv_anim_set_exec_cb(&a, (lv_anim_exec_xcb_t)blink_anim_cb);
    lv_anim_start(&a);
    lvgl_port_unlock();
}

/* ─────────────────── 表情更新（周期调用）─────────────────── */

void display_update(uint32_t dt_ms)
{
    static uint32_t acc = 0;
    static uint32_t blink_next = 3000;
    static float breath = 0.0f;
    static uint32_t wave_phase = 0;

    acc += dt_ms;
    breath += dt_ms / 1000.0f * (s_expr == EXPR_SLEEP ? 0.8f : 1.6f);
    wave_phase += dt_ms;

    lvgl_port_lock(0);

    /* ── 呼吸：眼睛整体轻微缩放（生命感的关键）── */
    int scale = (int)(2.0f + 1.6f * sinf(breath));    /* -1.6 ~ +3.6 px */
    if (s_eye_l && s_eye_r) {
        lv_obj_set_style_border_width(s_eye_l, scale, 0);
        lv_obj_set_style_border_width(s_eye_r, scale, 0);
    }

    /* ── 随机眨眼 ── */
    if (acc > blink_next && s_expr != EXPR_SLEEP) {
        do_blink();
        acc = 0;
        blink_next = 3000 + (rand() % 5000);          /* 3-8 秒 */
    }

    /* ── 瞳孔注视 ── */
    int px = (int)(s_gaze_x * 10.0f);
    int py = (int)(s_gaze_y * 10.0f);
    if (s_pupil_l && s_pupil_r) {
        lv_obj_align(s_pupil_l, LV_ALIGN_CENTER, px, py);
        lv_obj_align(s_pupil_r, LV_ALIGN_CENTER, px, py);
    }

    /* ── 按表情调整 ── */
    switch (s_expr) {
    case EXPR_LISTENING: {
        /* 瞳孔放大 */
        lv_obj_set_size(s_pupil_l, PUPIL_W + 6, PUPIL_H + 6);
        lv_obj_set_size(s_pupil_r, PUPIL_W + 6, PUPIL_H + 6);
        lv_obj_set_height(s_eye_l, EYE_H + 4);
        lv_obj_set_height(s_eye_r, EYE_H + 4);
        break;
    }
    case EXPR_THINKING: {
        /* 瞳孔左右缓移 */
        int off = (int)(sinf(wave_phase / 600.0f) * 8.0f);
        lv_obj_align(s_pupil_l, LV_ALIGN_CENTER, off, -4);
        lv_obj_align(s_pupil_r, LV_ALIGN_CENTER, off, -4);
        lv_obj_set_size(s_pupil_l, PUPIL_W, PUPIL_H);
        lv_obj_set_size(s_pupil_r, PUPIL_W, PUPIL_H);
        break;
    }
    case EXPR_SPEAKING: {
        /* 显示波形，按音量起伏 */
        for (int i = 0; i < WAVE_BARS; i++) {
            lv_obj_remove_flag(s_bars[i], LV_OBJ_FLAG_HIDDEN);
            float w = sinf((wave_phase / 120.0f) + i * 0.7f);
            int h = 6 + (int)((s_volume / 100.0f) * 22 * fabsf(w));
            lv_obj_set_height(s_bars[i], h > 4 ? h : 4);
        }
        break;
    }
    case EXPR_HAPPY: {
        /* 弯成 ^ ^：压扁眼睛 + 圆角拉满 */
        lv_obj_set_size(s_eye_l, EYE_W, 26);
        lv_obj_set_size(s_eye_r, EYE_W, 26);
        lv_obj_set_style_radius(s_eye_l, 16, 0);
        lv_obj_set_style_radius(s_eye_r, 16, 0);
        break;
    }
    case EXPR_SLEEP: {
        /* 闭眼：高度压到 8px */
        lv_obj_set_height(s_eye_l, 8);
        lv_obj_set_height(s_eye_r, 8);
        lv_obj_set_style_bg_color(s_eye_l, lv_color_hex(0x1e293b), 0);
        lv_obj_set_style_bg_color(s_eye_r, lv_color_hex(0x1e293b), 0);
        break;
    }
    case EXPR_IDLE:
    default: {
        /* 恢复标准睁眼 */
        if (s_blink_h >= EYE_H - 2) {
            lv_obj_set_height(s_eye_l, EYE_H);
            lv_obj_set_height(s_eye_r, EYE_H);
        }
        lv_obj_set_size(s_pupil_l, PUPIL_W, PUPIL_H);
        lv_obj_set_size(s_pupil_r, PUPIL_W, PUPIL_H);
        lv_obj_set_style_radius(s_eye_l, EYE_RADIUS, 0);
        lv_obj_set_style_radius(s_eye_r, EYE_RADIUS, 0);
        lv_obj_set_style_bg_color(s_eye_l, lv_color_hex(0x0b1220), 0);
        lv_obj_set_style_bg_color(s_eye_r, lv_color_hex(0x0b1220), 0);
        /* 瞳孔缓慢游移 */
        s_gaze_x = sinf(breath * 0.35f) * 0.25f;
        s_gaze_y = cosf(breath * 0.22f) * 0.15f;
        for (int i = 0; i < WAVE_BARS; i++) {
            lv_obj_add_flag(s_bars[i], LV_OBJ_FLAG_HIDDEN);
        }
        break;
    }
    }

    lvgl_port_unlock();
}

/* ─────────────────── 对外接口 ─────────────────── */

void display_set_expression(expression_t e)
{
    if (s_expr == e) return;
    s_expr = e;
    ESP_LOGI(TAG, "表情 → %d", (int)e);

    /* 切换时立刻刷新一次，避免延迟 */
    display_update(16);
}

expression_t display_get_expression(void)
{
    return s_expr;
}

void display_set_gaze(float nx, float ny)
{
    if (nx < -1) nx = -1;
    if (nx > 1) nx = 1;
    if (ny < -1) ny = -1;
    if (ny > 1) ny = 1;
    s_gaze_x = nx;
    s_gaze_y = ny;
}

void display_set_volume(uint8_t vol)
{
    s_volume = vol > 100 ? 100 : vol;
}

void display_set_status(const char *text)
{
    if (!s_status || !text) return;
    lvgl_port_lock(0);
    lv_label_set_text(s_status, text);
    lvgl_port_unlock();
}

void display_set_subtitle(const char *text)
{
    if (!s_subtitle || !text) return;
    lvgl_port_lock(0);
    lv_label_set_text(s_subtitle, text);
    lvgl_port_unlock();
}