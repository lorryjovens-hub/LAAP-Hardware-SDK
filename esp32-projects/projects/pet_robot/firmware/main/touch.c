/*
 * touch.c — 触摸检测（BSP 版）
 *
 * 改版前：硬编码 TTP223 的 GPIO，自己 gpio_config。
 * 改版后：只用 bsp_touch_pressed()。**换板子不用改。**
 *
 * 屏幕触摸和独立触摸片（TTP223）在 BSP 层统一了 ——
 * 应用层不关心是哪种，只知道"被碰了"。
 *
 * 这里剩下的职责：消抖 + 边沿检测 + 回调。
 */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "bsp.h"

#include "touch.h"

#define TAG "touch"

#define DEBOUNCE_MS  120

static touch_cb_t s_cb = NULL;
static int64_t s_last_ms = 0;
static bool s_last_state = false;

void touch_init(touch_cb_t cb)
{
    s_cb = cb;

    if (!bsp_has_cap(BSP_CAP_TOUCH)) {
        ESP_LOGW(TAG, "此板无触摸输入");
        return;
    }

    ESP_LOGI(TAG, "触摸就绪（由 BSP 提供）");
}

void touch_poll(void)
{
    if (!bsp_has_cap(BSP_CAP_TOUCH)) return;

    bool pressed = bsp_touch_pressed();
    int64_t now = esp_timer_get_time() / 1000;

    if (pressed != s_last_state) {
        if (now - s_last_ms < DEBOUNCE_MS) return;
        s_last_ms = now;
        s_last_state = pressed;

        ESP_LOGD(TAG, "触摸 %s", pressed ? "按下" : "松开");
        if (s_cb) s_cb(pressed);
    }
}