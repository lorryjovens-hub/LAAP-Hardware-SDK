/*
 * laap_core.h — LAAP 硬件核心统一入口
 *
 * ## 一条调用接入 LAAP
 *
 * ```c
 * static void on_msg(const laap_msg_t *m, void *user) {
 *     if (m->kind == LAAP_MSG_MOTION_POSE) motion_pose(m->pose);
 *     else if (m->kind == LAAP_MSG_DIALOGUE_STATE) display_set_expression(...);
 * }
 *
 * void app_main(void) {
 *     laap_core_config_t cfg = {
 *         .device_id = "pet-01",
 *         .kind      = "pet",
 *         .name      = "LAAP 桌面宠物",
 *         .host      = CONFIG_PET_WS_HOST,
 *         .port      = CONFIG_PET_WS_PORT,
 *         .caps      = LAAP_CAP_MOTION | LAAP_CAP_DISPLAY | LAAP_CAP_SPEAK
 *                    | LAAP_CAP_HEAR | LAAP_CAP_TOUCH,
 *         .motion    = LAAP_MOTION_PANTILT,
 *         .poses     = (const char*[]){"home","look_up","think","sleep","nod",NULL},
 *         .on_message = on_msg,
 *     };
 *     laap_core_start(&cfg);
 *
 *     // 主循环 50Hz
 *     while (1) {
 *         laap_core_tick();          // 处理下行消息（按优先级）
 *         display_update(20); motion_tick(20); touch_poll();
 *         vTaskDelay(pdMS_TO_TICKS(20));
 *     }
 * }
 * ```
 *
 * 应用层不用管 WiFi、WS、重连、心跳、协议解析、并发——只管动作。
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "laap_types.h"
#include "laap_protocol.h"
#include "laap_transport.h"
#include "laap_task.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *device_id;      /* 必填，如 "pet-01" */
    const char *kind;           /* 必填，pet/car/dog/desktop */
    const char *name;           /* 可选，显示名 */

    const char *host;           /* 必填，LAAP 侧地址 */
    uint16_t    port;
    bool        use_tls;

    uint32_t    caps;           /* LAAP_CAP_* 位掩码 */
    laap_motion_kind_t motion;
    const char *const *poses;   /* 姿态名数组，NULL 结尾 */

    laap_msg_cb_t   on_message; /* 必填 */
    laap_state_cb_t on_state;   /* 可选 */
    void *user;
} laap_core_config_t;

/** 启动（内部会初始化 WiFi 之外的传输/任务层） */
laap_err_t laap_core_start(const laap_core_config_t *cfg);

/** 在主循环里周期调用：取出并处理下行消息 */
void laap_core_tick(void);

/** 上行：感知上报 */
laap_err_t laap_core_percept(const char *sensor, const char *data_json);

/** 上行：状态上报 */
laap_err_t laap_core_state(const char *state_json);

/** 上行：心跳（内部自动，也可手动触发） */
laap_err_t laap_core_heartbeat(int battery_pct);

/** 二进制上行（音频） */
laap_err_t laap_core_send_bin(const uint8_t *data, size_t len);

/** 当前连接状态 */
laap_state_t laap_core_state_now(void);

/** 传输统计 */
void laap_core_stats(laap_transport_stats_t *out);

#ifdef __cplusplus
}
#endif