/*
 * display.c — 眼睛表情系统（BSP 版）
 *
 * ## 这个文件和硬件无关了
 *
 * 改版前：文件里硬编码了 6 个 LCD 引脚宏、SPI 初始化、GC9A01 驱动、
 *        背光 LEDC 通道。换一块板子就要改这里。
 *
 * 改版后：只调 bsp_display_init() / bsp_display_set_brightness()，
 *        屏幕多大问 bsp_display_width()。**换板子这个文件一个字都不用改。**
 *
 * 剩下的全是"生命表达"逻辑，那才是这个文件真正该负责的事：
 *   · 呼吸缩放（永不停）
 *   · 随机眨眼（3-8 秒）
 *   · 瞳孔注视
 *   · 6 种表情的几何变形
 *   · 说话波形
 */
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_lvgl_port.h"
#include "lvgl.h"
#include "bsp.h"

#include "display.h"

#define TAG "eyes"

/* ── 眼睛几何（与屏幕尺寸无关，按比例算）── */
#define EYE_H_RATIO    0.31f      /* 眼睛高 / 屏高 */
#define EYE_W_RATIO    0.26f
#define EYE_GAP_RATIO  0.11f
#define WAVE_BARS      12

static int s_scr_w = 240, s_scr_h = 240;
static int s_eye_w, s_eye_h, s_eye_gap, s_eye_radius, s_pupil_w, s_pupil_h;

static lv_obj_t *s_eye_l = NULL, *s_eye_r = NULL;
static lv_obj_t *s_pupil_l = NULL, *s_pupil_r = NULL;
static lv_obj_t *s_wave = NULL;
static lv_obj_t *s_status = NULL;
static lv_obj_t *s_subtitle = NULL;
static lv_obj_t *s_bars[WAVE_BARS];

static volatile expression_t s_expr = EXPR_IDLE;
static volatile int s_blink_h = 0;
static volatile float s_gaze_x = 0.0f, s_gaze_y = 0.0f;
static volatile uint8_t s_volume = 0;

/* ══════════════════════════════════════════════════════════
 *  UI 构建（不含任何硬件初始化）
 * ══════════════════════════════════════════════════════════ */

static lv_obj_t *make_eye(lv_obj_t *parent, int x)
{
    lv_obj_t *eye = lv_obj_create(parent);
    lv_obj_set_size(eye, s_eye_w, s_eye_h);
    lv_obj_set_pos(eye, x, s_scr_h / 2 - s_eye_h / 2 - s_scr_h / 13);
    lv_obj_set_style_radius(eye, s_eye_radius, 0);
    lv_obj_set_style_bg_color(eye, lv_color_hex(0x0b1220), 0);
    lv_obj_set_style_bg_opa(eye, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(eye, lv_color_hex(0x5eead4), 0);
    lv_obj_set_style_border_width(eye, 3, 0);
    lv_obj_set_style_shadow_color(eye, lv_color_hex(0x22d3ee), 0);
    lv_obj_set_style_shadow_width(eye, 18, 0);
    lv_obj_set_style_shadow_opa(eye, LV_OPA_50, 0);
    lv_obj_set_style_pad_all(eye, 0, 0);
    lv_obj_remove_flag(eye, LV_OBJ_FLAG_SCROLLABLE);
    return eye;
}

static lv_obj_t *make_pupil(lv_obj_t *eye)
{
    lv_obj_t *p = lv_obj_create(eye);
    lv_obj_set_size(p, s_pupil_w, s_pupil_h);
    lv_obj_set_style_radius(p, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(p, lv_color_hex(0x22d3ee), 0);
    lv_obj_set_style_bg_opa(p, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(p, 0, 0);
    lv_obj_remove_flag(p, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(p, LV_ALIGN_CENTER, 0, 0);
    return p;
}

static void build_ui(void)
{
    /* 尺寸按屏幕算，不写死 240 */
    s_eye_h = (int)(s_scr_h * EYE_H_RATIO);
    s_eye_w = (int)(s_scr_w * EYE_W_RATIO);
    s_eye_gap = (int)(s_scr_w * EYE_GAP_RATIO);
    s_eye_radius = s_eye_w * 45 / 100;
    s_pupil_w = s_eye_w * 42 / 100;
    s_pupil_h = s_eye_h * 40 / 100;
    s_blink_h = s_eye_h;

    lvgl_port_lock(0);
    lv_obj_t *scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x05080f), 0);
    lv_obj_clean(scr);

    s_eye_l = make_eye(scr, s_scr_w / 2 - s_eye_gap / 2 - s_eye_w);
    s_eye_r = make_eye(scr, s_scr_w / 2 + s_eye_gap / 2);
    s_pupil_l = make_pupil(s_eye_l);
    s_pupil_r = make_pupil(s_eye_r);

    /* 说话波形 */
    int bar_w = s_scr_w / 60;
    int spacing = bar_w * 2;
    for (int i = 0; i < WAVE_BARS; i++) {
        s_bars[i] = lv_obj_create(scr);
        lv_obj_set_size(s_bars[i], bar_w, bar_w * 2);
        lv_obj_set_pos(s_bars[i],
                       s_scr_w / 2 - (WAVE_BARS * spacing) / 2 + i * spacing,
                       s_scr_h - s_scr_h / 5);
        lv_obj_set_style_radius(s_bars[i], bar_w / 2, 0);
        lv_obj_set_style_bg_color(s_bars[i], lv_color_hex(0x22d3ee), 0);
        lv_obj_set_style_bg_opa(s_bars[i], LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(s_bars[i], 0, 0);
        lv_obj_add_flag(s_bars[i], LV_OBJ_FLAG_HIDDEN);
    }

    s_status = lv_label_create(scr);
    lv_obj_set_style_text_color(s_status, lv_color_hex(0x64748b), 0);
    lv_obj_align(s_status, LV_ALIGN_TOP_MID, 0, s_scr_h / 24);
    lv_label_set_text(s_status, "LAAP");

    s_subtitle = lv_label_create(scr);
    lv_obj_set_width(s_subtitle, s_scr_w - s_scr_w / 10);
    lv_obj_set_style_text_color(s_subtitle, lv_color_hex(0x94a3b8), 0);
    lv_obj_set_style_text_align(s_subtitle, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_subtitle, LV_ALIGN_BOTTOM_MID, 0, -s_scr_h / 17);
    lv_label_set_long_mode(s_subtitle, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_label_set_text(s_subtitle, "");

    lvgl_port_unlock();
}

void display_init(void)
{
    /* 硬件全交给 BSP */
    if (!bsp_has_cap(BSP_CAP_DISPLAY)) {
        ESP_LOGW(TAG, "此板无屏幕，眼睛表情不可用");
        return;
    }

    s_scr_w = bsp_display_width();
    s_scr_h = bsp_display_height();
    if (s_scr_w <= 0 || s_scr_h <= 0) {
        s_scr_w = s_scr_h = 240;
    }

    /* BSP 在 bsp_init() 里已经初始化过显示；这里防御性再调一次（幂等） */
    esp_err_t e = bsp_display_init();
    if (e != ESP_OK && e != ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGE(TAG, "显示初始化失败: %s", esp_err_to_name(e));
        return;
    }

    build_ui();
    ESP_LOGI(TAG, "眼睛就绪 %dx%d", s_scr_w, s_scr_h);
}

/* ══════════════════════════════════════════════════════════
 *  眨眼
 * ══════════════════════════════════════════════════════════ */

static void blink_anim_cb(lv_anim_t *a)
{
    int h = lv_map(a->act_time, 0, a->duration, s_eye_h, 6);
    if (a->act_time > a->duration / 2) {
        h = lv_map(a->act_time, a->duration / 2, a->duration, 6, s_eye_h);
    }
    s_blink_h = h;
    if (s_eye_l) lv_obj_set_height(s_eye_l, h);
    if (s_eye_r) lv_obj_set_height(s_eye_r, h);
}

static void do_blink(void)
{
    if (s_expr == EXPR_SLEEP || !s_eye_l) return;
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

/* ══════════════════════════════════════════════════════════
 *  周期更新
 * ══════════════════════════════════════════════════════════ */

void display_update(uint32_t dt_ms)
{
    if (!s_eye_l) return;

    static uint32_t acc = 0;
    static uint32_t blink_next = 3000;
    static float breath = 0.0f;
    static uint32_t wave_phase = 0;

    acc += dt_ms;
    breath += dt_ms / 1000.0f * (s_expr == EXPR_SLEEP ? 0.8f : 1.6f);
    wave_phase += dt_ms;

    lvgl_port_lock(0);

    /* 呼吸 */
    int bw = (int)(2.0f + 1.6f * sinf(breath));
    lv_obj_set_style_border_width(s_eye_l, bw, 0);
    lv_obj_set_style_border_width(s_eye_r, bw, 0);

    /* 随机眨眼 */
    if (acc > blink_next && s_expr != EXPR_SLEEP) {
        do_blink();
        acc = 0;
        blink_next = 3000 + (rand() % 5000);
    }

    /* 瞳孔注视 */
    int px = (int)(s_gaze_x * (s_eye_w / 6));
    int py = (int)(s_gaze_y * (s_eye_h / 7));
    lv_obj_align(s_pupil_l, LV_ALIGN_CENTER, px, py);
    lv_obj_align(s_pupil_r, LV_ALIGN_CENTER, px, py);

    switch (s_expr) {
    case EXPR_LISTENING:
        lv_obj_set_size(s_pupil_l, s_pupil_w + 6, s_pupil_h + 6);
        lv_obj_set_size(s_pupil_r, s_pupil_w + 6, s_pupil_h + 6);
        lv_obj_set_height(s_eye_l, s_eye_h + 4);
        lv_obj_set_height(s_eye_r, s_eye_h + 4);
        break;

    case EXPR_THINKING: {
        int off = (int)(sinf(wave_phase / 600.0f) * 8.0f);
        lv_obj_align(s_pupil_l, LV_ALIGN_CENTER, off, -4);
        lv_obj_align(s_pupil_r, LV_ALIGN_CENTER, off, -4);
        lv_obj_set_size(s_pupil_l, s_pupil_w, s_pupil_h);
        lv_obj_set_size(s_pupil_r, s_pupil_w, s_pupil_h);
        break;
    }

    case EXPR_SPEAKING:
        for (int i = 0; i < WAVE_BARS; i++) {
            lv_obj_remove_flag(s_bars[i], LV_OBJ_FLAG_HIDDEN);
            float w = sinf((wave_phase / 120.0f) + i * 0.7f);
            int h = 6 + (int)((s_volume / 100.0f) * (s_scr_h / 10) * fabsf(w));
            lv_obj_set_height(s_bars[i], h > 4 ? h : 4);
        }
        break;

    case EXPR_HAPPY:
        lv_obj_set_size(s_eye_l, s_eye_w, s_eye_h / 3);
        lv_obj_set_size(s_eye_r, s_eye_w, s_eye_h / 3);
        lv_obj_set_style_radius(s_eye_l, s_eye_h / 5, 0);
        lv_obj_set_style_radius(s_eye_r, s_eye_h / 5, 0);
        break;

    case EXPR_SLEEP:
        lv_obj_set_height(s_eye_l, 8);
        lv_obj_set_height(s_eye_r, 8);
        lv_obj_set_style_bg_color(s_eye_l, lv_color_hex(0x1e293b), 0);
        lv_obj_set_style_bg_color(s_eye_r, lv_color_hex(0x1e293b), 0);
        break;

    case EXPR_IDLE:
    default:
        if (s_blink_h >= s_eye_h - 2) {
            lv_obj_set_height(s_eye_l, s_eye_h);
            lv_obj_set_height(s_eye_r, s_eye_h);
        }
        lv_obj_set_size(s_pupil_l, s_pupil_w, s_pupil_h);
        lv_obj_set_size(s_pupil_r, s_pupil_w, s_pupil_h);
        lv_obj_set_style_radius(s_eye_l, s_eye_radius, 0);
        lv_obj_set_style_radius(s_eye_r, s_eye_radius, 0);
        lv_obj_set_style_bg_color(s_eye_l, lv_color_hex(0x0b1220), 0);
        lv_obj_set_style_bg_color(s_eye_r, lv_color_hex(0x0b1220), 0);
        s_gaze_x = sinf(breath * 0.35f) * 0.25f;
        s_gaze_y = cosf(breath * 0.22f) * 0.15f;
        for (int i = 0; i < WAVE_BARS; i++) {
            lv_obj_add_flag(s_bars[i], LV_OBJ_FLAG_HIDDEN);
        }
        break;
    }

    lvgl_port_unlock();
}

/* ══════════════════════════════════════════════════════════
 *  对外接口
 * ══════════════════════════════════════════════════════════ */

void display_set_expression(expression_t e)
{
    if (s_expr == e) return;
    s_expr = e;
    ESP_LOGD(TAG, "表情 → %d", (int)e);
    display_update(16);
}

expression_t display_get_expression(void) { return s_expr; }

void display_set_gaze(float nx, float ny)
{
    if (nx < -1) nx = -1;
    if (nx > 1) nx = 1;
    if (ny < -1) ny = -1;
    if (ny > 1) ny = 1;
    s_gaze_x = nx;
    s_gaze_y = ny;
}

void display_set_volume(uint8_t vol) { s_volume = vol > 100 ? 100 : vol; }

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

void display_set_brightness(uint8_t percent)
{
    bsp_display_set_brightness(percent);
}