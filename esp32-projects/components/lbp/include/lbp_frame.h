/*
 * lbp_frame.h — L2 链路层：帧编解码 / CRC32 / 分片
 *
 * 与 laaper/body/frame.py 逐字节一致。
 */
#pragma once

#include "lbp_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ══════════════ 帧 ══════════════ */

typedef struct {
    uint8_t         type;           /* lbp_msg_type_t */
    uint8_t         src;
    uint8_t         dst;
    uint8_t         seq;
    uint8_t         ttl;
    bool            fragment;       /* FRAGMENT 位 */
    bool            ack_req;        /* ACK_REQ 位 */
    lbp_prio_t      prio;
    uint32_t        t_exec_us;      /* 0 = 立即执行 */
    uint16_t        len;
    uint8_t        *payload;        /* 指向调用方缓冲，不拥有 */
} lbp_frame_t;

/** CRC-32/ISO-HDLC（与 zlib.crc32 相同多项式 0xEDB88320） */
uint32_t lbp_crc32(const uint8_t *data, size_t len);

/**
 * 编码一帧到 buf。
 * @return 写入字节数，0 表示失败（buf 太小或载荷超限）
 */
size_t lbp_frame_encode(const lbp_frame_t *f, uint8_t *buf, size_t buf_len);

/**
 * 解码一帧。
 * @param out      输出（out->payload 指向 data 内部，不解引用 NULL）
 * @return LBP_OK / LBP_ERR_FRAME / LBP_ERR_CRC / LBP_ERR_PARSE
 */
lbp_err_t lbp_frame_decode(const uint8_t *data, size_t len, lbp_frame_t *out);

/** 编码后总字节数 */
static inline size_t lbp_frame_wire_size(uint16_t payload_len)
{
    return LBP_HDR_SIZE + payload_len + LBP_TRAILER_SIZE;
}

/* ══════════════ 分片 ══════════════ */

/*
 * 分片头 5 字节：
 *   group_id(2) index(1) total(1) msg_type(1)
 *
 * msg_type 必需 —— 否则接收方重组出数据却不知道该怎么处理。
 * 代价：CAN FD 上每片容量 64-18-5-5 = 36B。
 */
#define LBP_FRAG_HDR        5
#define LBP_FRAG_MAX_PARTS  255

/** 给定整帧上限，单片能装多少数据 */
static inline uint16_t lbp_frag_chunk(uint16_t max_frame_bytes)
{
    int32_t c = (int32_t)max_frame_bytes
                - LBP_HDR_SIZE - LBP_TRAILER_SIZE - LBP_FRAG_HDR;
    return c > 0 ? (uint16_t)c : 0;
}

/** 分片组数 */
uint8_t lbp_frag_part_count(uint16_t data_len, uint16_t max_frame_bytes);

/**
 * 生成第 idx 片到 out（调用方提供 ≥ max_frame_bytes 的缓冲）。
 * @param out_len 输出：写入字节数
 * @return LBP_OK
 */
lbp_err_t lbp_frag_build(const uint8_t *data, uint16_t data_len,
                         uint8_t gid, uint8_t idx, uint8_t total,
                         uint8_t orig_type, uint16_t max_frame_bytes,
                         uint8_t *out, size_t *out_len);

/* ══════════════ 重组器 ══════════════ */

#define LBP_REASM_MAX_GROUPS 4
#define LBP_REASM_BUF_SIZE   (LBP_MAX_PAYLOAD)

typedef struct {
    bool     used;
    uint8_t  gid;
    uint8_t  src;
    uint8_t  next_idx;
    uint8_t  total;
    uint8_t  orig_type;
    uint16_t received;
    uint8_t  buf[LBP_REASM_BUF_SIZE];
    uint32_t last_ms;
} lbp_reasm_slot_t;

typedef struct {
    lbp_reasm_slot_t slots[LBP_REASM_MAX_GROUPS];
    uint32_t timeout_ms;
    /* 统计 */
    uint32_t groups_done;
    uint32_t groups_dropped;
    uint32_t loss_detected;
} lbp_reasm_t;

void lbp_reasm_init(lbp_reasm_t *r, uint32_t timeout_ms);

/**
 * 喂一个 FRAG 帧。
 * 集齐时返回 LBP_OK 并通过 *out_data / *out_len / *out_type 输出；
 * 未集齐返回 LBP_ERR_TIMEOUT（调用方忽略即可）；
 * 出错（丢片）返回 LBP_ERR_PARSE，该组已丢弃。
 */
lbp_err_t lbp_reasm_feed(lbp_reasm_t *r, const lbp_frame_t *frame,
                         const uint8_t **out_data, uint16_t *out_len,
                         uint8_t *out_type);

/** 清理超时的组 */
void lbp_reasm_tick(lbp_reasm_t *r, uint32_t now_ms);

#ifdef __cplusplus
}
#endif