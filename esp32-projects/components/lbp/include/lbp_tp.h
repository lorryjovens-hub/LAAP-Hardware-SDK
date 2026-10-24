/*
 * lbp_tp.h — CAN 2.0B 分段传输（LBP/TP-8）
 *
 * ## 为什么必须有这一层
 *
 * CAN 2.0B 单帧数据域**只有 8 字节**（CAN FD 才是 64）。
 * 而 LBP 帧最小 23 字节（空载荷）、典型 37~51 字节。
 *
 * 所以 LBP 帧必须被切成多个 CAN 帧。这不是可选的优化，
 * 是协议能不能跑起来的前提。
 *
 * ## 分段格式（每 CAN 帧 8 字节）
 *
 *   byte0 = (seq << 4) | type
 *     type: 0x1 SINGLE  整帧放在一 CAN 帧里（≤7 字节）
 *           0x2 FIRST   首段，byte1..2 = 总长(LE u16)，byte3..7 = 数据(5B)
 *           0x3 CONT    中间段，byte1..7 = 数据(7B)
 *           0x4 LAST    末段，  byte1..7 = 数据(1..7B)
 *
 * 例：23 字节 LBP 帧 → FIRST(5) + CONT(7) + CONT(7) + LAST(4) = 4 个 CAN 帧
 *
 * ## CAN ID 分配（11 位）
 *
 *   id = (priority << 8) | dst
 *
 * priority 0-3 放高位，这样 SAFETY 帧在仲裁时天然抢占总线 ——
 * 不需要软件调度，CAN 硬件仲裁就保证了 SAFETY 优先。
 *
 * ## 顺序假设
 *
 * 单总线上同一 CAN ID 的帧保持发送顺序，所以不做乱序重组。
 * 收到 seq 跳变即视为丢帧，整组作废（宁可重发也不拼错数据）。
 */
#pragma once

#include "lbp_types.h"

#ifdef __cplusplus
extern "C" {
#endif

#define LBP_TP_CAN_DLC      8
#define LBP_TP_MAX_PEERS    8

/* 分段类型 */
#define LBP_TP_SINGLE       0x1
#define LBP_TP_FIRST        0x2
#define LBP_TP_CONT         0x3
#define LBP_TP_LAST         0x4

/** 由优先级和目的地址构造 CAN ID */
static inline uint32_t lbp_tp_can_id(lbp_prio_t prio, uint8_t dst)
{
    return ((uint32_t)(prio & 0x03) << 8) | (uint32_t)dst;
}

/** 从 CAN ID 取目的地（用于过滤） */
static inline uint8_t lbp_tp_can_id_dst(uint32_t id)
{
    return (uint8_t)(id & 0xFF);
}

/** 一段 LBP 帧需要几个 CAN 帧 */
size_t lbp_tp_segment_count(size_t lbp_len);

/* ══════════════ 发送/接收回调 ══════════════ */

/** 真的发一个 CAN 帧 */
typedef lbp_err_t (*lbp_tp_send_fn)(uint32_t can_id, const uint8_t *data,
                                    uint8_t dlc, void *user);

/** 收齐一个完整 LBP 帧 */
typedef void (*lbp_tp_recv_fn)(uint32_t can_id, const uint8_t *lbp_frame,
                               size_t len, void *user);

/* ══════════════ 接收上下文 ══════════════ */

typedef struct {
    bool     used;
    uint8_t  src;
    uint8_t  next_seq;
    uint16_t expect_len;
    uint16_t got;
    uint8_t  buf[LBP_MAX_FRAME];
    uint32_t last_ms;
} lbp_tp_slot_t;

typedef struct {
    lbp_tp_slot_t slots[LBP_TP_MAX_PEERS];
    uint32_t timeout_ms;
    /* 统计（诊断用） */
    uint32_t tx_frames;
    uint32_t rx_frames;
    uint32_t tx_lbp;
    uint32_t rx_lbp;
    uint32_t drops;
} lbp_tp_t;

void lbp_tp_init(lbp_tp_t *tp, uint32_t timeout_ms);

/**
 * 发送一个完整 LBP 帧（自动分段）。
 * @param lbp_frame 已编码好的 LBP 帧
 * @return LBP_OK
 */
lbp_err_t lbp_tp_send(lbp_tp_t *tp, uint32_t can_id,
                      const uint8_t *lbp_frame, size_t len,
                      lbp_tp_send_fn send, void *user);

/**
 * 喂一个收到的 CAN 帧。
 * 集齐一个完整 LBP 帧时调用 on_frame。
 */
lbp_err_t lbp_tp_feed(lbp_tp_t *tp, uint32_t can_id,
                      const uint8_t *data, uint8_t dlc,
                      lbp_tp_recv_fn on_frame, void *user);

/** 清理超时的半成品 */
void lbp_tp_tick(lbp_tp_t *tp, uint32_t now_ms);

#ifdef __cplusplus
}
#endif