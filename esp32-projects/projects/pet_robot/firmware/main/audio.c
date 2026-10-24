/*
 * audio.c — I2S 音频（BSP 版）
 *
 * 改版前：硬编码 I2S 引脚、采样率、声道模式，自己建 i2s_chan。
 * 改版后：从 BSP 拿 tx/rx 句柄（bsp_audio_tx/rx），采样率问
 *        bsp_audio_sample_rate()。**换板子这个文件不用改。**
 *
 * 这里剩下的职责：
 *   · 麦克风采集线程（按帧节流）
 *   · 播放 + 音量提取（驱动说话波形）
 *   · Opus 编解码接入点
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "bsp.h"

#include "audio.h"

#define TAG "audio"

#define FRAME_MS        20

static i2s_chan_handle_t s_tx = NULL;
static i2s_chan_handle_t s_rx = NULL;
static uint32_t s_sample_rate = 16000;
static uint16_t s_frame_samples = 320;   /* 16000 * 20ms / 1000 */
static volatile bool s_mic_on = false;
static volatile uint8_t s_volume = 0;
static TaskHandle_t s_mic_task = NULL;

/* 上行发送回调：由 main.c 提供 */
extern void pet_send_bin(const uint8_t *data, size_t len);

void audio_init(void)
{
    s_sample_rate = bsp_audio_sample_rate();
    s_frame_samples = (uint16_t)(s_sample_rate * FRAME_MS / 1000);

    s_tx = (i2s_chan_handle_t)bsp_audio_tx();
    s_rx = (i2s_chan_handle_t)bsp_audio_rx();

    if (!s_tx && !s_rx) {
        ESP_LOGW(TAG, "此板无音频");
        return;
    }

    ESP_LOGI(TAG, "音频就绪 %u Hz %s%s",
             (unsigned)s_sample_rate,
             s_rx ? "mic " : "", s_tx ? "speaker" : "");
}

/* ── 麦克风采集 ── */
static void mic_task(void *arg)
{
    int16_t *pcm = malloc(s_frame_samples * sizeof(int16_t) * 2);
    size_t frame_bytes = s_frame_samples * sizeof(int16_t);

    if (!pcm) {
        ESP_LOGE(TAG, "麦克风缓冲分配失败");
        vTaskDelete(NULL);
        return;
    }

    while (1) {
        if (!s_mic_on || !s_rx) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        size_t read = 0;
        esp_err_t err = i2s_channel_read(s_rx, pcm, frame_bytes, &read,
                                         pdMS_TO_TICKS(60));
        if (err != ESP_OK || read < frame_bytes) continue;

        /* TODO: Opus 编码（libopus, 24kbps voip）
         * 当前直发 PCM 便于先联通链路：
         *   int n = opus_encode(enc, pcm, s_frame_samples, out, sizeof(out));
         *   pet_send_bin(out, n);
         */
        pet_send_bin((const uint8_t *)pcm, frame_bytes);
    }
}

void audio_start_mic(void)
{
    if (s_mic_on || !s_rx) return;
    s_mic_on = true;
    if (!s_mic_task) {
        xTaskCreatePinnedToCore(mic_task, "mic", 4096, NULL, 5, &s_mic_task, 1);
    }
}

void audio_stop_mic(void) { s_mic_on = false; }

/* ── 播放 ── */
void audio_play_opus(const uint8_t *opus, size_t len)
{
    if (!s_tx || !len) return;

    /* TODO: Opus 解码（当前按 PCM 直通） */
    size_t written = 0;
    i2s_channel_write(s_tx, opus, len, &written, pdMS_TO_TICKS(200));

    /* 峰值估算，驱动说话波形 */
    const int16_t *p = (const int16_t *)opus;
    int n = len / 2;
    if (n > 0) {
        int32_t peak = 0;
        for (int i = 0; i < n; i += 8) {
            int32_t v = p[i] < 0 ? -p[i] : p[i];
            if (v > peak) peak = v;
        }
        s_volume = (uint8_t)((peak * 100) / 32768);
    }
}

uint8_t audio_get_volume(void) { return s_volume; }