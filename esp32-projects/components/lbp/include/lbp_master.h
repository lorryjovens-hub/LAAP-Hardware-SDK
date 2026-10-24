/*
 * lbp_master.h — LBP 主站（躯干）
 *
 * 职责：
 *   · 枚举：广播 ENUM_REQ，收各模块 BMD
 *   · 拓扑：TOPO_REQ/ACK 收集端口连接
 *   · 下发：CMD 带同一 T_EXEC 让所有关节同步动作
 *   · 收遥测 / 反射事件
 *
 * 身体图式推导和 IK **不在 MCU 上做**（DLS 迭代 + 数值雅可比太吃算力），
 * 主站把拓扑通过 WiFi 发给 PC 上的 laaper.body，PC 算完回 BODY_SCHEMA。
 */
#pragma once

#include "lbp_types.h"
#include "lbp_bus.h"
#include "lbp_tp.h"
#include "lbp_frame.h"

#ifdef __cplusplus
extern "C" {
#endif

#define LBP_MASTER_MAX_PEERS  16

/* 一个被发现的对端模块 */
typedef struct {
    bool     used;
    bool     online;
    uint8_t  addr;
    lbp_bmd_t bmd;

    /* 拓扑 */
    uint8_t  mount_port;            /* 它插在我的哪个口 */
    uint8_t  child_count;
    uint8_t  child_ports[LBP_TOPO_MAX_CHILDREN];
    uint8_t  child_addrs[LBP_TOPO_MAX_CHILDREN];

    /* 遥测 */
    bool     telem_valid;
    uint8_t  dof;
    float    q[LBP_MAX_JOINTS];
    float    torque[LBP_MAX_JOINTS];
    int8_t   temp_c;
    bool     has_temp;

    /* 反射 */
    uint32_t reflex_count;
    uint8_t  last_reflex_code;

    uint32_t last_seen_ms;
} lbp_peer_t;

typedef struct {
    lbp_bus_t  bus;
    lbp_tp_t   tp;
    lbp_reasm_t reasm;

    lbp_peer_t peers[LBP_MASTER_MAX_PEERS];
    uint8_t    count;

    uint32_t   stat_enum_ack;
    uint32_t   stat_topo_ack;
    uint32_t   stat_telem;
    uint32_t   stat_reflex;
    uint32_t   stat_bad;

    uint8_t    seq;
} lbp_master_t;

/* ══════════════ 生命周期 ══════════════ */

lbp_err_t lbp_master_init(lbp_master_t *m, const lbp_bus_cfg_t *cfg);
void      lbp_master_deinit(lbp_master_t *m);

/* ══════════════ 枚举与拓扑 ══════════════ */

/**
 * 广播枚举，收集 BMD。
 * @param timeout_ms 等待时间
 * @return 发现的模块数（<0 表示错误）
 */
int lbp_master_enumerate(lbp_master_t *m, uint32_t timeout_ms);

/**
 * 逐个查询端口连接。
 * @return 成功应答的模块数
 */
int lbp_master_query_topology(lbp_master_t *m, uint32_t timeout_ms);

/* ══════════════ 控制 ══════════════ */

/**
 * 给一个模块下发关节目标。
 * @param t_exec_us 全局执行时刻（0 = 立即）。多条 CMD 用同一值即可同步
 */
lbp_err_t lbp_master_send_cmd(lbp_master_t *m, uint8_t addr,
                              const float *q, uint8_t dof,
                              uint32_t t_exec_us);

/** 广播 SAFE_STOP（最高优先级） */
lbp_err_t lbp_master_broadcast_stop(lbp_master_t *m);

/** 广播时钟同步 */
lbp_err_t lbp_master_clock_sync(lbp_master_t *m, uint32_t now_us);

/* ══════════════ 轮询与查询 ══════════════ */

/** 处理收到的帧（在主循环里调） */
void lbp_master_poll(lbp_master_t *m, uint32_t timeout_ms);

lbp_peer_t *lbp_master_find(lbp_master_t *m, uint8_t addr);

/** 打印拓扑（调试用，格式与 lbp_sim.py 对齐） */
void lbp_master_print_topology(lbp_master_t *m);

/** 导出拓扑为 JSON（发给 PC 用） */
size_t lbp_master_topology_json(lbp_master_t *m, char *out, size_t out_len);

#ifdef __cplusplus
}
#endif