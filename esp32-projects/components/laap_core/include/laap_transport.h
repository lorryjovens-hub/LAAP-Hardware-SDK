/*
 * laap_transport.h — WebSocket 传输 + 指数退避重连 + 心跳
 *
 * 这一层解决的问题：网络不可靠。
 *   · 断线自动重连（1→2→4→8→16→32→60s，±30% 抖动防重连风暴）
 *   · 心跳保活 + 失败降级
 *   · 收到消息只入队，不在这里做业务（避免阻塞 WS 线程）
 */
#pragma once

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>
#include "laap_types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *host;           /* 电脑 IP 或域名 */
    uint16_t    port;
    const char *path;           /* 默认 "/" */
    bool        use_tls;        /* wss:// */

    uint32_t    hb_interval_ms;     /* 心跳间隔，0 = 8000 默认 */
    uint32_t    reconnect_min_ms;   /* 首次重连延迟，0 = 1000 */
    uint32_t    reconnect_max_ms;   /* 最大重连延迟，0 = 60000 */
    uint8_t     backoff_factor_x10; /* 退避倍数×10，0 = 20（即 2.0） */

    laap_state_cb_t on_state;
    void *user;
} laap_transport_cfg_t;

/**
 * 启动传输层（内部起 WS 任务 + 心跳任务）。
 * 连接成功后会自动发 hello。
 */
laap_err_t laap_transport_start(const laap_transport_cfg_t *cfg);

/** 停止 */
void laap_transport_stop(void);

/** 是否已连接 */
bool laap_transport_connected(void);

/**
 * 发送文本（线程安全）。
 * @return LAAP_OK / LAAP_ERR_TRANSPORT
 */
laap_err_t laap_transport_send_text(const char *data, size_t len);

/** 发送二进制（音频上行） */
laap_err_t laap_transport_send_bin(const uint8_t *data, size_t len);

/** 传输统计（诊断用） */
typedef struct {
    uint32_t connects;      /* 累计成功连接次数 */
    uint32_t disconnects;   /* 累计断线次数 */
    uint32_t reconnects;    /* 累计重连尝试 */
    uint32_t sent_msgs;
    uint32_t recv_msgs;
    uint32_t send_fail;
    int64_t  last_recv_ms;
} laap_transport_stats_t;

void laap_transport_get_stats(laap_transport_stats_t *out);

/**
 * 注入 hello 构造器（由 laap_core 注册，避免传输层耦合设备信息）。
 * 连上后自动调用它得到注册消息。
 */
typedef size_t (*laap_hello_builder_t)(char *out, size_t out_len);
void laap_transport_set_hello_builder(laap_hello_builder_t fn);

#ifdef __cplusplus
}
#endif