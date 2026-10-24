/*
 * laap_core.c — 把协议 / 传输 / 队列拼成一条可用的接入链
 */
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "laap_core.h"

#define TAG "laap_core"

static laap_core_config_t s_cfg;
static bool s_inited = false;
static char s_hello_buf[640];

/* hello 构造器：传输层连上后会回调这个 */
static size_t build_hello(char *out, size_t out_len)
{
    size_t pose_count = 0;
    if (s_cfg.poses) {
        while (s_cfg.poses[pose_count]) pose_count++;
    }
    return laap_proto_build_hello(
        s_cfg.device_id,
        s_cfg.name,
        s_cfg.kind,
        s_cfg.caps,
        s_cfg.motion,
        s_cfg.poses,
        pose_count,
        out, out_len);
}

/* 传输状态变化 → 上报应用层 */
static void on_transport_state(laap_state_t st, void *user)
{
    (void)user;
    switch (st) {
    case LAAP_STATE_CONNECTED:
        ESP_LOGI(TAG, "已接入 LAAP");
        break;
    case LAAP_STATE_DISCONNECTED:
        ESP_LOGW(TAG, "与 LAAP 断开");
        break;
    case LAAP_STATE_RECONNECTING:
        ESP_LOGI(TAG, "重连中…");
        break;
    default:
        break;
    }
    if (s_cfg.on_state) s_cfg.on_state(st, s_cfg.user);
}

laap_err_t laap_core_start(const laap_core_config_t *cfg)
{
    if (!cfg || !cfg->device_id || !cfg->host || !cfg->on_message) {
        return LAAP_ERR_INVALID_ARG;
    }
    if (s_inited) return LAAP_OK;

    s_cfg = *cfg;
    if (!s_cfg.kind) s_cfg.kind = "generic";
    if (!s_cfg.name) s_cfg.name = s_cfg.device_id;

    /* 1. 任务队列 */
    laap_err_t e = laap_task_init();
    if (e != LAAP_OK) return e;

    /* 2. hello 构造器注入传输层 */
    laap_transport_set_hello_builder(build_hello);

    /* 3. 传输层 */
    laap_transport_cfg_t tc = {
        .host = s_cfg.host,
        .port = s_cfg.port,
        .path = "/",
        .use_tls = s_cfg.use_tls,
        .on_state = on_transport_state,
        .user = NULL,
    };
    e = laap_transport_start(&tc);
    if (e != LAAP_OK) return e;

    s_inited = true;
    ESP_LOGI(TAG, "laap_core 就绪: %s (%s)", s_cfg.device_id, s_cfg.kind);
    return LAAP_OK;
}

void laap_core_tick(void)
{
    if (!s_inited) return;

    laap_msg_t msg;
    /* 一次 tick 最多处理 4 条，避免长时间占住主循环 */
    for (int i = 0; i < 4; i++) {
        if (!laap_task_poll(&msg, 0)) break;
        msg.ts_ms = esp_timer_get_time() / 1000;
        if (s_cfg.on_message) s_cfg.on_message(&msg, s_cfg.user);
    }
}

laap_err_t laap_core_percept(const char *sensor, const char *data_json)
{
    if (!s_inited) return LAAP_ERR_NOT_INIT;
    int n = laap_proto_build_percept(s_cfg.device_id, sensor, data_json,
                                     s_hello_buf, sizeof(s_hello_buf));
    if (n <= 0) return LAAP_ERR_NO_MEM;
    return laap_transport_send_text(s_hello_buf, (size_t)n);
}

laap_err_t laap_core_state(const char *state_json)
{
    if (!s_inited) return LAAP_ERR_NOT_INIT;
    int n = laap_proto_build_state(s_cfg.device_id, state_json,
                                   s_hello_buf, sizeof(s_hello_buf));
    if (n <= 0) return LAAP_ERR_NO_MEM;
    return laap_transport_send_text(s_hello_buf, (size_t)n);
}

laap_err_t laap_core_heartbeat(int battery_pct)
{
    if (!s_inited) return LAAP_ERR_NOT_INIT;
    int n = laap_proto_build_heartbeat(s_cfg.device_id, battery_pct,
                                       s_hello_buf, sizeof(s_hello_buf));
    if (n <= 0) return LAAP_ERR_NO_MEM;
    return laap_transport_send_text(s_hello_buf, (size_t)n);
}

laap_err_t laap_core_send_bin(const uint8_t *data, size_t len)
{
    if (!s_inited) return LAAP_ERR_NOT_INIT;
    return laap_transport_send_bin(data, len);
}

laap_state_t laap_core_state_now(void)
{
    return laap_transport_connected() ? LAAP_STATE_CONNECTED
                                      : LAAP_STATE_DISCONNECTED;
}

void laap_core_stats(laap_transport_stats_t *out)
{
    laap_transport_get_stats(out);
}