/*
 * lbp.h — LBP/1.0 伞头文件
 *
 * 一次包含即可用全部 API。
 *
 * ## 最小用法：从站（一条腿）
 *
 * ```c
 * #include "lbp.h"
 *
 * static void on_cmd(const float *q, uint8_t dof, uint32_t t_exec, void *user) {
 *     for (int i = 0; i < dof; i++) servo_set(i, q[i]);
 *     static float last[3];
 *     for (int i = 0; i < dof; i++) last[i] = q[i];
 *     lbp_node_send_telem(&g_node, last, NULL, 42, true);
 * }
 *
 * static void on_stop(void *user) { servo_release_all(); }
 *
 * void app_main(void) {
 *     lbp_node_t *n = calloc(1, sizeof(lbp_node_t));
 *     lbp_node_cfg_t cfg = {
 *         .addr = CONFIG_LBP_NODE_ADDR,
 *         .mount_port = CONFIG_LBP_MOUNT_PORT,
 *         .bus = {
 *             .gpio_tx = CONFIG_LBP_CAN_TX_GPIO,
 *             .gpio_rx = CONFIG_LBP_CAN_RX_GPIO,
 *             .bitrate = CONFIG_LBP_BITRATE,
 *         },
 *         .on_cmd = on_cmd,
 *         .on_safe_stop = on_stop,
 *     };
 *     lbp_fill_leg_3dof_bmd(&cfg.bmd);       // 或者自己填
 *     lbp_node_start(n, &cfg);
 * }
 * ```
 *
 * ## 最小用法：主站（躯干）
 *
 * ```c
 * lbp_master_t m;
 * lbp_master_init(&m, &bus_cfg);
 *
 * int n = lbp_master_enumerate(&m, 1500);
 * lbp_master_query_topology(&m, 0);
 * lbp_master_print_topology(&m);
 *
 * char json[1024];
 * lbp_master_topology_json(&m, json, sizeof(json));
 * wifi_send(json);                          // 发给 PC 算身体图式
 *
 * // 同步下发：四条腿用同一个 t_exec
 * uint32_t t = now_us() + 100000;
 * lbp_master_send_cmd(&m, 2, q0, 3, t);
 * lbp_master_send_cmd(&m, 3, q1, 3, t);
 * ```
 */
#pragma once

#include "lbp_types.h"
#include "lbp_frame.h"
#include "lbp_payload.h"
#include "lbp_tp.h"
#include "lbp_bus.h"
#include "lbp_node.h"
#include "lbp_master.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 填一个 3-DOF 腿的标准 BMD（与 laaper.body 的 leg_3dof 一致）
 *
 * 几何：髋外展 ±30° / 髋屈伸 -45..90° / 膝 -150..0°
 *       连杆 20+20+90+100 mm，质量 0.28kg，峰值 9W
 *
 * 手写这个函数是因为固件里不想放 JSON 解析器。
 * 自定义模块照这个格式填即可。
 */
void lbp_fill_leg_3dof_bmd(lbp_bmd_t *bmd, uint64_t serial);

/** 填一个 4-DOF 臂的 BMD */
void lbp_fill_arm_4dof_bmd(lbp_bmd_t *bmd, uint64_t serial);

#ifdef __cplusplus
}
#endif