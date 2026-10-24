/*
 * bsp_base.c — BSP 通用层 + 弱符号默认实现
 *
 * ## 核心机制：弱符号（weak symbols）
 *
 * 这里为每个板级接口提供「不支持」的默认实现，
 * 板子的 board.c 用强符号覆盖它真正具备的能力。
 *
 * 结果是：**板子只实现自己有的东西**，没有的自动降级。
 *
 *   s3_round_gc9a01/board.c  实现 display + servo + audio + touch
 *   s3_eye/board.c           实现 camera + audio，不实现 servo
 *   → 两者都能链接通过，应用代码用 bsp_has_cap() 判断即可
 *
 * 这比「每个板子实现全部接口然后返回 NOT_SUPPORTED」干净得多，
 * 也避免了一个新板子忘了实现某个函数就链接失败的麻烦。
 *
 * This file is part of LAAP Hardware SDK, GPL v3.
 */
#include <string.h>
#include "esp_log.h"
#include "bsp.h"
#include "bsp_board.h"

static const char *TAG = "bsp";

/* ══════════════════════════════════════════════════════════
 *  板子必须提供的：板级信息
 * ══════════════════════════════════════════════════════════ */

/* 板子未定义时的兜底信息 */
static const bsp_info_t s_fallback_info = {
    .name = "未识别板子",
    .id = "unknown",
    .chip = "unknown",
    .caps = 0,
    .display_w = 0,
    .display_h = 0,
    .display_driver = NULL,
    .servo_count = 0,
    .note = "bsp_board_info() 未被板级实现覆盖",
};

/** 板级信息（板子覆盖） */
__attribute__((weak)) const bsp_info_t *bsp_board_info(void)
{
    return &s_fallback_info;
}

/* ══════════════════════════════════════════════════════════
 *  板级可选实现（弱默认 = 不支持）
 * ══════════════════════════════════════════════════════════ */

__attribute__((weak)) esp_err_t bsp_board_init(void)
{
    return ESP_OK;
}

__attribute__((weak)) esp_err_t bsp_display_init(void)
{
    ESP_LOGW(TAG, "此板无显示能力");
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t bsp_display_set_brightness(uint8_t percent)
{
    (void)percent;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) void *bsp_display_panel(void)
{
    return NULL;
}

__attribute__((weak)) esp_err_t bsp_servo_init(void)
{
    ESP_LOGW(TAG, "此板无舵机通道");
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t bsp_servo_set_angle(uint8_t ch, float deg)
{
    (void)ch; (void)deg;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t bsp_servo_calibrate(uint8_t ch, float off, bool inv)
{
    (void)ch; (void)off; (void)inv;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t bsp_audio_init(void)
{
    ESP_LOGW(TAG, "此板无音频");
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) void *bsp_audio_tx(void)
{
    return NULL;
}

__attribute__((weak)) void *bsp_audio_rx(void)
{
    return NULL;
}

__attribute__((weak)) uint32_t bsp_audio_sample_rate(void)
{
    return 16000;
}

__attribute__((weak)) esp_err_t bsp_touch_init(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) bool bsp_touch_pressed(void)
{
    return false;
}

__attribute__((weak)) esp_err_t bsp_i2c_init(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) void *bsp_i2c_bus(void)
{
    return NULL;
}

__attribute__((weak)) int bsp_battery_percent(void)
{
    return -1;
}

__attribute__((weak)) int bsp_battery_charging(void)
{
    return -1;
}

__attribute__((weak)) bool bsp_button_pressed(void)
{
    return false;
}

__attribute__((weak)) void bsp_board_tick(void)
{
    /* 板级周期任务（采样电池、按键消抖等），默认无 */
}

/* ══════════════════════════════════════════════════════════
 *  通用实现
 * ══════════════════════════════════════════════════════════ */

const bsp_info_t *bsp_get_info(void)
{
    const bsp_info_t *info = bsp_board_info();
    return info ? info : &s_fallback_info;
}

bool bsp_has_cap(uint32_t cap)
{
    return (bsp_get_info()->caps & cap) != 0;
}

uint16_t bsp_display_width(void)
{
    return bsp_get_info()->display_w;
}

uint16_t bsp_display_height(void)
{
    return bsp_get_info()->display_h;
}

uint8_t bsp_servo_count(void)
{
    return bsp_get_info()->servo_count;
}

void bsp_print_info(void)
{
    const bsp_info_t *i = bsp_get_info();

    ESP_LOGI(TAG, "╔══════════════════════════════════════════════");
    ESP_LOGI(TAG, "║ Board : %s", i->name);
    ESP_LOGI(TAG, "║ ID    : %s", i->id);
    ESP_LOGI(TAG, "║ Chip  : %s", i->chip);

    if (i->display_w && i->display_h) {
        ESP_LOGI(TAG, "║ Screen: %dx%d (%s)",
                 i->display_w, i->display_h,
                 i->display_driver ? i->display_driver : "?");
    }
    if (i->servo_count) {
        ESP_LOGI(TAG, "║ Servo : %u ch", i->servo_count);
    }

    /* 能力清单 */
    char caps[160] = {0};
    struct { uint32_t bit; const char *name; } map[] = {
        {BSP_CAP_DISPLAY, "display"}, {BSP_CAP_TOUCH, "touch"},
        {BSP_CAP_AUDIO_OUT, "speaker"}, {BSP_CAP_AUDIO_IN, "mic"},
        {BSP_CAP_CAMERA, "camera"}, {BSP_CAP_SERVO, "servo"},
        {BSP_CAP_MOTOR, "motor"}, {BSP_CAP_IMU, "imu"},
        {BSP_CAP_BATTERY, "battery"}, {BSP_CAP_BUTTON, "button"},
        {BSP_CAP_LED, "led"}, {BSP_CAP_SDCARD, "sdcard"},
        {BSP_CAP_I2C, "i2c"}, {BSP_CAP_EXPANDER, "expander"},
    };
    for (size_t k = 0; k < sizeof(map) / sizeof(map[0]); k++) {
        if (i->caps & map[k].bit) {
            if (caps[0]) strncat(caps, " ", sizeof(caps) - strlen(caps) - 1);
            strncat(caps, map[k].name, sizeof(caps) - strlen(caps) - 1);
        }
    }
    ESP_LOGI(TAG, "║ Caps  : %s", caps[0] ? caps : "(none)");

    if (i->note) {
        ESP_LOGI(TAG, "║ Note  : %s", i->note);
    }
    ESP_LOGI(TAG, "╚══════════════════════════════════════════════");
}

esp_err_t bsp_init(void)
{
    static bool inited = false;
    if (inited) return ESP_OK;

    bsp_print_info();

    /* 1. 板级通用初始化（电源使能、扩展芯片复位等） */
    esp_err_t e = bsp_board_init();
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "板级初始化失败: %s", esp_err_to_name(e));
        return e;
    }

    /* 2. I2C 先起（IMU/触摸/传感器都靠它） */
    if (bsp_has_cap(BSP_CAP_I2C)) {
        e = bsp_i2c_init();
        if (e != ESP_OK) {
            ESP_LOGW(TAG, "I2C 初始化失败（继续）: %s", esp_err_to_name(e));
        }
    }

    /* 3. 按能力初始化，单个失败不阻断其它 */
    struct { uint32_t cap; esp_err_t (*fn)(void); const char *name; } steps[] = {
        {BSP_CAP_DISPLAY,    bsp_display_init, "display"},
        {BSP_CAP_TOUCH,      bsp_touch_init,   "touch"},
        {BSP_CAP_AUDIO_OUT,  bsp_audio_init,   "audio"},
        {BSP_CAP_AUDIO_IN,   bsp_audio_init,   "audio"},   /* 同一次初始化 */
        {BSP_CAP_SERVO,      bsp_servo_init,   "servo"},
    };

    for (size_t k = 0; k < sizeof(steps) / sizeof(steps[0]); k++) {
        if (!bsp_has_cap(steps[k].cap)) continue;
        /* audio 会被 OUT/IN 各触发一次，加个简单去重 */
        if (k > 0 && steps[k].fn == steps[k-1].fn) continue;

        e = steps[k].fn();
        if (e == ESP_OK) {
            ESP_LOGI(TAG, "✓ %s 就绪", steps[k].name);
        } else if (e == ESP_ERR_NOT_SUPPORTED) {
            ESP_LOGW(TAG, "✗ %s 声明支持但未实现", steps[k].name);
        } else {
            ESP_LOGE(TAG, "✗ %s 初始化失败: %s", steps[k].name, esp_err_to_name(e));
        }
    }

    inited = true;
    ESP_LOGI(TAG, "板级初始化完成");
    return ESP_OK;
}

esp_err_t bsp_deinit(void)
{
    /* 保守实现：只关背光。完整 deinit 涉及外设顺序，留给具体板子扩展 */
    if (bsp_has_cap(BSP_CAP_DISPLAY)) {
        bsp_display_set_brightness(0);
    }
    return ESP_OK;
}

void bsp_tick(void)
{
    bsp_board_tick();
}