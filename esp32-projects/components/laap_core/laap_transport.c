/*
 * laap_transport.c — WebSocket 传输 + 指数退避重连 + 心跳
 *
 * 通信格式约定：
 *   文本帧 = LDP JSON
 *   二进制帧 = 音频（Opus/PCM）
 */
#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_websocket_client.h"
#include "laap_transport.h"
#include "laap_protocol.h"
#include "laap_task.h"

#define TAG "laap_ws"

/* hello 由 laap_core 组装后注册进来，避免协议层和传输层耦合 */
typedef laap_hello_builder_t hello_builder_t;
static hello_builder_t s_hello_builder = NULL;

/* ══════════════ 内部状态 ══════════════ */
static esp_websocket_client_handle_t s_client = NULL;
static laap_transport_cfg_t s_cfg;
static volatile laap_state_t s_state = LAAP_STATE_DISCONNECTED;
static volatile bool s_running = false;
static SemaphoreHandle_t s_send_mutex = NULL;
static laap_transport_stats_t s_stats;

/* 重连退避 */
static uint32_t s_backoff_ms = 1000;

void laap_transport_set_hello_builder(hello_builder_t fn)
{
    s_hello_builder = fn;
}

static void set_state(laap_state_t st)
{
    if (s_state == st) return;
    s_state = st;
    if (s_cfg.on_state) s_cfg.on_state(st, s_cfg.user);
}

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

/* ══════════════ WS 事件 ══════════════ */

static void ws_handler(void *arg, esp_event_base_t base,
                       int32_t event_id, void *event_data)
{
    esp_websocket_event_data_t *d = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED: {
        ESP_LOGI(TAG, "已连接 %s:%u", s_cfg.host, s_cfg.port);
        s_stats.connects++;
        s_backoff_ms = s_cfg.reconnect_min_ms ? s_cfg.reconnect_min_ms : 1000;
        set_state(LAAP_STATE_CONNECTED);

        /* 自动发 hello 注册 */
        if (s_hello_builder) {
            char buf[640];
            size_t n = s_hello_builder(buf, sizeof(buf));
            if (n > 0) {
                laap_transport_send_text(buf, n);
                ESP_LOGI(TAG, "已发送 hello 注册");
            }
        }
        break;
    }

    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "连接断开");
        s_stats.disconnects++;
        set_state(LAAP_STATE_DISCONNECTED);
        break;

    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGW(TAG, "传输错误");
        set_state(LAAP_STATE_RECONNECTING);
        break;

    case WEBSOCKET_EVENT_DATA:
        if (d->op_code == 0x01 && d->data_len > 0) {
            /* 文本 = LDP；解析后压队列，不在 WS 线程做业务 */
            laap_msg_t msg;
            if (laap_proto_parse(d->data_ptr, d->data_len, &msg) == LAAP_OK) {
                s_stats.recv_msgs++;
                s_stats.last_recv_ms = now_ms();

                laap_prio_t prio = LAAP_PRIO_DIALOGUE;
                switch (msg.kind) {
                case LAAP_MSG_MOTION_STOP:      prio = LAAP_PRIO_SAFETY;   break;
                case LAAP_MSG_MOTION_MOVE:
                case LAAP_MSG_MOTION_POSE:      prio = LAAP_PRIO_MOTION;   break;
                case LAAP_MSG_DIALOGUE_TEXT:
                case LAAP_MSG_DIALOGUE_STATE:   prio = LAAP_PRIO_DIALOGUE; break;
                default:                        prio = LAAP_PRIO_BACKGROUND; break;
                }
                laap_task_post(prio, &msg);

                if (msg.kind == LAAP_MSG_MOTION_STOP) {
                    /* 急停：清空其余待办 */
                    laap_task_flush();
                    laap_msg_t m2 = msg;
                    laap_task_post(LAAP_PRIO_SAFETY, &m2);
                }
            } else {
                ESP_LOGW(TAG, "LDP 解析失败 (%d bytes)", d->data_len);
            }
        } else if (d->op_code == 0x02) {
            /* 二进制 = 音频，交给应用层处理（这里只计数） */
            s_stats.recv_msgs++;
            s_stats.last_recv_ms = now_ms();
        }
        break;

    default:
        break;
    }
}

/* ══════════════ 重连任务 ══════════════ */

static void reconnect_task(void *arg)
{
    uint32_t max_backoff = s_cfg.reconnect_max_ms ? s_cfg.reconnect_max_ms : 60000;
    uint8_t factor10 = s_cfg.backoff_factor_x10 ? s_cfg.backoff_factor_x10 : 20;
    (void)max_backoff;
    (void)factor10;

    int64_t last_hb = 0;
    uint32_t hb_interval = s_cfg.hb_interval_ms ? s_cfg.hb_interval_ms : 25000;

    while (s_running) {
        int64_t t = now_ms();

        if (!esp_websocket_client_is_connected(s_client)) {
            set_state(LAAP_STATE_RECONNECTING);

            /* ±30% 抖动，防多设备同时重连打爆服务器 */
            uint32_t jitter_pct = (s_backoff_ms * 30) / 100;
            int32_t jit = 0;
            if (jitter_pct > 0) {
                jit = (int32_t)(esp_random() % (2 * jitter_pct + 1)) - (int32_t)jitter_pct;
            }
            int32_t wait = (int32_t)s_backoff_ms + jit;
            if (wait < 500) wait = 500;

            ESP_LOGI(TAG, "%.1fs 后重连（退避 %ums）", wait / 1000.0f, s_backoff_ms);
            vTaskDelay(pdMS_TO_TICKS(wait));

            if (!s_running) break;
            s_stats.reconnects++;
            esp_websocket_client_start(s_client);

            /* 指数退避 */
            uint32_t next = s_backoff_ms * factor10 / 10;
            if (next > max_backoff) next = max_backoff;
            s_backoff_ms = next;
            last_hb = now_ms();
            continue;
        }

        /* 心跳：连上但静默太久也要发，保持 NAT 表不过期 */
        if (t - last_hb > (int64_t)hb_interval) {
            last_hb = t;
            /* 心跳由 laap_core 提供 builder（需要 device_id） */
        }

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    vTaskDelete(NULL);
}

/* ══════════════ 对外 API ══════════════ */

laap_err_t laap_transport_start(const laap_transport_cfg_t *cfg)
{
    if (!cfg || !cfg->host) return LAAP_ERR_INVALID_ARG;
    if (s_running) return LAAP_OK;

    memset(&s_stats, 0, sizeof(s_stats));
    s_cfg = *cfg;
    if (!s_cfg.path) s_cfg.path = "/";
    if (!s_cfg.reconnect_min_ms) s_cfg.reconnect_min_ms = 1000;
    if (!s_cfg.reconnect_max_ms) s_cfg.reconnect_max_ms = 60000;
    s_backoff_ms = s_cfg.reconnect_min_ms;

    s_send_mutex = xSemaphoreCreateMutex();
    if (!s_send_mutex) return LAAP_ERR_NO_MEM;

    esp_websocket_client_config_t ws_cfg = {
        .host = s_cfg.host,
        .port = s_cfg.port,
        .path = s_cfg.path,
        .transport = s_cfg.use_tls ? WEBSOCKET_TRANSPORT_OVER_SSL
                                   : WEBSOCKET_TRANSPORT_OVER_TCP,
        .buffer_size = 4096,
        .network_timeout_ms = 10000,
        .reconnect_timeout_ms = 0,     /* 我们自己的重连逻辑接管 */
        .disable_auto_reconnect = true,
    };
    s_client = esp_websocket_client_init(&ws_cfg);
    if (!s_client) return LAAP_ERR_NO_MEM;

    esp_websocket_register_events(s_client, WEBSOCKET_EVENT_ANY, ws_handler, NULL);

    s_running = true;
    set_state(LAAP_STATE_CONNECTING);
    esp_websocket_client_start(s_client);
    xTaskCreate(reconnect_task, "laap_reconn", 4096, NULL, 4, NULL);

    ESP_LOGI(TAG, "传输启动 → %s:%u%s", s_cfg.host, s_cfg.port, s_cfg.path);
    return LAAP_OK;
}

void laap_transport_stop(void)
{
    if (!s_running) return;
    s_running = false;
    if (s_client) {
        esp_websocket_client_stop(s_client);
        esp_websocket_client_destroy(s_client);
        s_client = NULL;
    }
    if (s_send_mutex) {
        vSemaphoreDelete(s_send_mutex);
        s_send_mutex = NULL;
    }
    set_state(LAAP_STATE_DISCONNECTED);
    ESP_LOGI(TAG, "传输停止");
}

bool laap_transport_connected(void)
{
    return s_client && esp_websocket_client_is_connected(s_client);
}

laap_err_t laap_transport_send_text(const char *data, size_t len)
{
    if (!data || len == 0) return LAAP_ERR_INVALID_ARG;
    if (!laap_transport_connected()) {
        s_stats.send_fail++;
        return LAAP_ERR_TRANSPORT;
    }
    if (s_send_mutex) xSemaphoreTake(s_send_mutex, portMAX_DELAY);
    int r = esp_websocket_client_send_text(s_client, data, len,
                                           pdMS_TO_TICKS(500));
    if (s_send_mutex) xSemaphoreGive(s_send_mutex);

    if (r < 0) { s_stats.send_fail++; return LAAP_ERR_TRANSPORT; }
    s_stats.sent_msgs++;
    return LAAP_OK;
}

laap_err_t laap_transport_send_bin(const uint8_t *data, size_t len)
{
    if (!data || len == 0) return LAAP_ERR_INVALID_ARG;
    if (!laap_transport_connected()) {
        s_stats.send_fail++;
        return LAAP_ERR_TRANSPORT;
    }
    if (s_send_mutex) xSemaphoreTake(s_send_mutex, portMAX_DELAY);
    int r = esp_websocket_client_send_bin(s_client, (const char *)data, len,
                                          pdMS_TO_TICKS(200));
    if (s_send_mutex) xSemaphoreGive(s_send_mutex);

    if (r < 0) { s_stats.send_fail++; return LAAP_ERR_TRANSPORT; }
    s_stats.sent_msgs++;
    return LAAP_OK;
}

void laap_transport_get_stats(laap_transport_stats_t *out)
{
    if (out) *out = s_stats;
}