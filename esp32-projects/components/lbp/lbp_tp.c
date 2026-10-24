/*
 * lbp_tp.c — CAN 2.0B 分段传输实现（纯逻辑，不依赖 IDF）
 */
#include <string.h>
#include "lbp_tp.h"

size_t lbp_tp_segment_count(size_t lbp_len)
{
    if (lbp_len == 0) return 0;
    if (lbp_len <= 7) return 1;                 /* SINGLE */
    /* FIRST 带 5 字节数据，之后每段 7 字节 */
    size_t rest = lbp_len - 5;
    size_t cont = (rest + 6) / 7;               /* 向上取整 */
    return 1 + cont;
}

void lbp_tp_init(lbp_tp_t *tp, uint32_t timeout_ms)
{
    if (!tp) return;
    memset(tp, 0, sizeof(*tp));
    tp->timeout_ms = timeout_ms ? timeout_ms : 1000;
}

/* ══════════════════════════════════════════════════════════
 *  发送
 * ══════════════════════════════════════════════════════════ */

lbp_err_t lbp_tp_send(lbp_tp_t *tp, uint32_t can_id,
                      const uint8_t *lbp_frame, size_t len,
                      lbp_tp_send_fn send, void *user)
{
    if (!tp || !lbp_frame || !send) return LBP_ERR_INVALID_ARG;
    if (len == 0 || len > LBP_MAX_FRAME) return LBP_ERR_TOO_BIG;

    uint8_t can[LBP_TP_CAN_DLC];
    uint8_t seq = 0;

    /* 小帧：单段 */
    if (len <= 7) {
        memset(can, 0, sizeof(can));
        can[0] = (uint8_t)((seq << 4) | LBP_TP_SINGLE);
        memcpy(&can[1], lbp_frame, len);
        lbp_err_t e = send(can_id, can, LBP_TP_CAN_DLC, user);
        if (e != LBP_OK) return e;
        tp->tx_frames++;
        tp->tx_lbp++;
        return LBP_OK;
    }

    size_t off = 0;

    /* 首段 */
    memset(can, 0, sizeof(can));
    can[0] = (uint8_t)((seq++ << 4) | LBP_TP_FIRST);
    can[1] = (uint8_t)(len & 0xFF);
    can[2] = (uint8_t)((len >> 8) & 0xFF);
    size_t take = (len < 5) ? len : 5;
    memcpy(&can[3], lbp_frame, take);
    off += take;
    if (send(can_id, can, LBP_TP_CAN_DLC, user) != LBP_OK) return LBP_ERR_BUS;
    tp->tx_frames++;

    /* 中间段 + 末段 */
    while (off < len) {
        size_t left = len - off;
        bool last = (left <= 7);
        memset(can, 0, sizeof(can));
        can[0] = (uint8_t)(((seq++ & 0x0F) << 4)
                           | (last ? LBP_TP_LAST : LBP_TP_CONT));
        take = last ? left : 7;
        memcpy(&can[1], lbp_frame + off, take);
        if (send(can_id, can, LBP_TP_CAN_DLC, user) != LBP_OK) return LBP_ERR_BUS;
        tp->tx_frames++;
        off += take;
    }

    tp->tx_lbp++;
    return LBP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  接收
 * ══════════════════════════════════════════════════════════ */

static lbp_tp_slot_t *slot_find(lbp_tp_t *tp, uint8_t src)
{
    for (int i = 0; i < LBP_TP_MAX_PEERS; i++) {
        if (tp->slots[i].used && tp->slots[i].src == src) return &tp->slots[i];
    }
    return NULL;
}

static lbp_tp_slot_t *slot_alloc(lbp_tp_t *tp, uint8_t src,
                                 uint16_t expect_len, uint8_t first_seq)
{
    for (int i = 0; i < LBP_TP_MAX_PEERS; i++) {
        if (!tp->slots[i].used) {
            lbp_tp_slot_t *s = &tp->slots[i];
            memset(s, 0, sizeof(*s));
            s->used = true;
            s->src = src;
            s->expect_len = expect_len;
            s->next_seq = (uint8_t)((first_seq + 1) & 0x0F);
            s->got = 0;
            return s;
        }
    }
    /* 满了：挤掉最旧的 */
    lbp_tp_slot_t *oldest = &tp->slots[0];
    for (int i = 1; i < LBP_TP_MAX_PEERS; i++) {
        if (tp->slots[i].last_ms < oldest->last_ms) oldest = &tp->slots[i];
    }
    tp->drops++;
    memset(oldest, 0, sizeof(*oldest));
    oldest->used = true;
    oldest->src = src;
    oldest->expect_len = expect_len;
    oldest->next_seq = (uint8_t)((first_seq + 1) & 0x0F);
    return oldest;
}

lbp_err_t lbp_tp_feed(lbp_tp_t *tp, uint32_t can_id,
                      const uint8_t *data, uint8_t dlc,
                      lbp_tp_recv_fn on_frame, void *user)
{
    if (!tp || !data || dlc == 0) return LBP_ERR_INVALID_ARG;

    uint8_t hdr = data[0];
    uint8_t type = (uint8_t)(hdr & 0x0F);
    uint8_t seq = (uint8_t)((hdr >> 4) & 0x0F);

    /* 源地址从 CAN ID 的低 8 位取（这里用 ID 的 dst 反推不方便，
     * 所以约定：CAN ID 的 dst 就是接收方，src 从 LBP 帧头里读。
     * 但分段阶段还没解码，所以用 can_id 高几位区分来源不可行。
     * → 用「同一时刻每个 LBP 帧来自一个 src」，靠 LBP 帧头校验兜底。 */

    tp->rx_frames++;

    /* 单段：直接交出 */
    if (type == LBP_TP_SINGLE) {
        size_t n = dlc - 1;
        if (n == 0) return LBP_ERR_FRAME;
        if (on_frame) on_frame(can_id, &data[1], n, user);
        tp->rx_lbp++;
        return LBP_OK;
    }

    if (type == LBP_TP_FIRST) {
        if (dlc < 3) return LBP_ERR_FRAME;
        uint16_t total = (uint16_t)(data[1] | ((uint16_t)data[2] << 8));
        if (total < LBP_MIN_FRAME || total > LBP_MAX_FRAME) {
            return LBP_ERR_FRAME;
        }
        size_t n = dlc - 3;
        if (n > total) n = total;

        /* 用 CAN ID + seq 作为槽位键（CAN ID 已经能区分方向） */
        lbp_tp_slot_t *s = slot_find(tp, (uint8_t)(can_id & 0xFF));
        if (s) {
            /* 同源又来新首段：丢弃旧的 */
            tp->drops++;
            s->used = false;
            s = NULL;
        }
        s = slot_alloc(tp, (uint8_t)(can_id & 0xFF), total, seq);
        if (!s) return LBP_ERR_NO_MEM;
        memcpy(s->buf, &data[3], n);
        s->got = (uint16_t)n;
        return LBP_OK;
    }

    /* CONT / LAST */
    if (type != LBP_TP_CONT && type != LBP_TP_LAST) return LBP_ERR_FRAME;

    lbp_tp_slot_t *s = slot_find(tp, (uint8_t)(can_id & 0xFF));
    if (!s) {
        tp->drops++;
        return LBP_ERR_PARSE;       /* 首段丢了 */
    }

    if (seq != s->next_seq) {
        /* 乱序 / 丢帧：整组作废 */
        tp->drops++;
        s->used = false;
        return LBP_ERR_PARSE;
    }

    size_t n = dlc - 1;
    if ((size_t)s->got + n > s->expect_len) n = s->expect_len - s->got;
    if ((size_t)s->got + n > sizeof(s->buf)) {
        tp->drops++;
        s->used = false;
        return LBP_ERR_TOO_BIG;
    }

    memcpy(&s->buf[s->got], &data[1], n);
    s->got = (uint16_t)(s->got + n);
    s->next_seq = (uint8_t)((s->next_seq + 1) & 0x0F);

    if (type == LBP_TP_LAST || s->got >= s->expect_len) {
        uint16_t total = s->got;
        s->used = false;
        tp->rx_lbp++;
        if (on_frame) on_frame(can_id, s->buf, total, user);
    }

    return LBP_OK;
}

void lbp_tp_tick(lbp_tp_t *tp, uint32_t now_ms)
{
    if (!tp) return;
    for (int i = 0; i < LBP_TP_MAX_PEERS; i++) {
        lbp_tp_slot_t *s = &tp->slots[i];
        if (!s->used) continue;
        if ((now_ms - s->last_ms) > tp->timeout_ms) {
            s->used = false;
            tp->drops++;
        }
    }
}