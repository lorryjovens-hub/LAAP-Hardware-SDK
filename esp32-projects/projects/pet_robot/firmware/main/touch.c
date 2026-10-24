/*
 * touch.c — TTP223 触摸检测（摸头反应）
 *
 * 触摸是宠物最重要的「被感知」通道：
 *   被摸头 → 立刻开心 + 看向手的方向
 * 这个反馈比语音输入更有"活着"的感觉。
 */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "touch.h"

#define TAG "touch"

#define PIN_TOUCH       GPIO_NUM_6
#define DEBOUNCE_MS     120

static touch_cb_t s_cb = NULL;
static int64_t s_last_ms = 0;
static bool s_last_state = false;

void touch_init(touch_cb_t cb)
{
    s_cb = cb;

    gpio_config_t io = {
        .pin_bit_mask = 1ULL << PIN_TOUCH,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,      /* 用轮询，简单可靠 */
    };
    gpio_config(&io);

    ESP_LOGI(TAG, "触摸就绪 pin=%d", PIN_TOUCH);
}

/* 周期调用（建议 20-50ms） */
void touch_poll(void)
{
    bool pressed = gpio_get_level(PIN_TOUCH) != 0;
    int64_t now = esp_timer_get_time() / 1000;

    if (pressed != s_last_state) {
        if (now - s_last_ms < DEBOUNCE_MS) return;   /* 抖动 */
        s_last_ms = now;
        s_last_state = pressed;

        ESP_LOGI(TAG, "触摸 %s", pressed ? "按下" : "松开");
        if (s_cb) s_cb(pressed);
    }
}