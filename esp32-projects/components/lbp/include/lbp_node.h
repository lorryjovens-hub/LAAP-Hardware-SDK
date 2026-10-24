/*
 * lbp_node.h — LBP 从站（一个关节模块 / 一条腿）
 *
 * 职责：
 *   · 上电上报 BMD（ENUM_ACK，自动分片）
 *   · 应答拓扑查询（TOPO_ACK，带自己的挂载端口）
 *   · 收 CMD，等到 T_EXEC 时刻执行
 *   · 回 TELEM（位置/力矩/温度）
 *   · 本地反射：过流/堵转/过温 → 立即卸力 + REFLEX 上报
 *
 * ⚠ 反射必须本地闭环：总线下发的是目标位置 + 安全边界，
 *   1kHz 反射环跑在模块 MCU 里，不走总线（带宽核算已证明不可能）。
 */
#pragma once

#include "lbp_types.h"
#include "lbp_bus.h"
#include "lbp_tp.h"
#include "lbp_frame.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct lbp_node lbp_node_t;

/* ══════════════ 回调 ══════════════ */

/** 收到运动指令，到了执行时刻才回调（节点保证 T_EXEC 语义） */
typedef void (*lbp_node_cmd_cb)(const float *q, uint8_t dof,
                                uint32_t t_exec_us, void *user);

/** 收到 SAFE_STOP */
typedef void (*lbp_node_stop_cb)(void *user);

/* ══════════════ 配置 ══════════════ */

typedef struct {
    lbp_bmd_t    bmd;           /* 模块自描述（会被填 addr） */
    uint8_t      addr;          /* CAN 地址（枚举时分配，默认 0x10 起） */
    uint8_t      mount_port;    /* 物理上插在父模块的第几号口 */
    lbp_bus_cfg_t bus;

    lbp_node_cmd_cb  on_cmd;
    lbp_node_stop_cb on_safe_stop;
    void *user;
} lbp_node_cfg_t;

/* ══════════════ 节点 ══════════════ */

struct lbp_node {
    lbp_node_cfg_t cfg;
    lbp_bus_t      bus;
    lbp_tp_t       tp;
    lbp_reasm_t    reasm;

    /* 待执行的 CMD（T_EXEC 未到） */
    bool     pending;
    uint32_t pending_deadline_us;
    float    pending_q[LBP_MAX_JOINTS];
    uint8_t  pending_dof;

    /* 统计 */
    uint32_t stat_enum;
    uint32_t stat_topo;
    uint32_t stat_cmd;
    uint32_t stat_telem;
    uint32_t stat_reflex;
    uint32_t stat_bad;

    void *task;
    bool  running;
};

/** 启动（内部起接收任务） */
lbp_err_t lbp_node_start(lbp_node_t *node, const lbp_node_cfg_t *cfg);

void lbp_node_stop(lbp_node_t *node);

/** 上报遥测。torque/temp 可为 NULL */
lbp_err_t lbp_node_send_telem(lbp_node_t *node, const float *q,
                              const float *torque, int8_t temp_c,
                              bool has_temp);

/** 上报反射事件（也可在本地反射环里调） */
lbp_err_t lbp_node_send_reflex(lbp_node_t *node, uint8_t code,
                               uint8_t joint, float value);

/**
 * 主循环里调：处理到期的 pending CMD。
 * （如果要精确 T_EXEC，在 1kHz 任务里调这个）
 */
void lbp_node_tick(lbp_node_t *node, uint32_t now_us);

/** 从 ID0/ID1/ID2 三根引脚读端口号（0-7） */
uint8_t lbp_read_port_id(gpio_num_t id0, gpio_num_t id1, gpio_num_t id2);

/** 检测 PRESENT# 是否插入 */
bool lbp_is_present(gpio_num_t present_pin);

#ifdef __cplusplus
}
#endif