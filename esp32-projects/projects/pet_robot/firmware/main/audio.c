/*
 * audio.c — I2S 麦克风采集（上行 Opus）+ 功放播放（下行 Opus）
 *
 * 协议与电脑侧 laaper/hub/screen_stream.py / xiaozhi_audio_stream.py 对齐：
 *   16 kHz / mono / 20ms 帧
 *
 * 引脚按你的板改。
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#include "esp_log.h"

#include "audio.h"

#define TAG "audio"

#define PIN_I2S_BCLK    GPIO_NUM_18
#define PIN_I2S_LRCK    GPIO_NUM_17
#define PIN_I2S_DOUT    GPIO_NUM_19    /* → MAX98357A DIN（喇叭） */
#define PIN_I2S_DIN     GPIO_NUM_16    /* ← INMP441 SD（麦克风） */

#define SAMPLE_RATE     16000
#define FRAME_MS        20
#define FRAME_SAMPLES   (SAMPLE_RATE * FRAME_MS / 1000)   /* 320 */
#define FRAME_BYTES     (FRAME_SAMPLES * 2)

static i2s_chan_handle_t s_tx = NULL;
static i2s_chan_handle_t s_rx = NULL;
static volatile bool s_mic_on = false;
static volatile uint8_t s_volume = 0;
static TaskHandle_t s_mic_task = NULL;

/* 上行发送回调：由 main.c 提供 */
extern void pet_send_bin(const uint8_t *data, size_t len);

void audio_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &s_tx, &s_rx));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_I2S_BCLK,
            .ws = PIN_I2S_LRCK,
            .dout = PIN_I2S_DOUT,
            .din = PIN_I2S_DIN,
            .invert_flags = {0},
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_tx, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_rx, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(s_tx));
    ESP_ERROR_CHECK(i2s_channel_enable(s_rx));

    ESP_LOGI(TAG, "音频就绪 %d Hz mono", SAMPLE_RATE);
}

/* ── 上行：麦克风采集线程 ── */
static void mic_task(void *arg)
{
    int16_t pcm[FRAME_SAMPLES];

    while (1) {
        if (!s_mic_on) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        size_t read = 0;
        esp_err_t err = i2s_channel_read(s_rx, pcm, FRAME_BYTES, &read,
                                         pdMS_TO_TICKS(60));
        if (err != ESP_OK || read < FRAME_BYTES) continue;

        /* TODO: 这里做 Opus 编码（libopus, 24kbps voip）
         * 当前直接发 PCM 便于先联通；接上 opus 组件后改成编码后发送。
         *    int n = opus_encode(enc, pcm, FRAME_SAMPLES, out, sizeof(out));
         *    pet_send_bin(out, n);
         */
        pet_send_bin((const uint8_t *)pcm, FRAME_BYTES);
    }
}

void audio_start_mic(void)
{
    if (s_mic_on) return;
    s_mic_on = true;
    if (!s_mic_task) {
        xTaskCreatePinnedToCore(mic_task, "mic", 4096, NULL, 5, &s_mic_task, 1);
    }
}

void audio_stop_mic(void)
{
    s_mic_on = false;
}

/* ── 下行：播放远端音频 ── */
void audio_play_opus(const uint8_t *opus, size_t len)
{
    if (!s_tx || !len) return;

    /* TODO: Opus 解码（当前按 PCM 直通） */
    size_t written = 0;
    i2s_channel_write(s_tx, opus, len, &written, pdMS_TO_TICKS(200));

    /* 粗略音量估算（驱动说话波形） */
    int16_t *p = (int16_t *)opus;
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

uint8_t audio_get_volume(void)
{
    return s_volume;
}