/*
 * lbp_frame.c — 帧编解码 / CRC32 / 分片重组
 *
 * 全部纯逻辑，不依赖 ESP-IDF，可在 PC 上单独编译测试。
 */
#include <string.h>
#include "lbp_frame.h"

/* ══════════════════════════════════════════════════════════
 *  CRC-32/ISO-HDLC（zlib 同款）
 *
 *  多项式 0xEDB88320（反射形式），init 0xFFFFFFFF，末尾异或 0xFFFFFFFF。
 *  用表驱动，1KB ROM 换速度——CAN 上每帧都要算，值得。
 * ══════════════════════════════════════════════════════════ */

static uint32_t s_crc_table[256];
static bool s_crc_ready = false;

static void crc32_build_table(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++) {
            c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        }
        s_crc_table[i] = c;
    }
    s_crc_ready = true;
}

uint32_t lbp_crc32(const uint8_t *data, size_t len)
{
    if (!s_crc_ready) crc32_build_table();
    if (!data) return 0;

    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        c = s_crc_table[(c ^ data[i]) & 0xFF] ^ (c >> 8);
    }
    return c ^ 0xFFFFFFFFu;
}

/* ══════════════════════════════════════════════════════════
 *  小端读写
 * ══════════════════════════════════════════════════════════ */

static inline void put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
}

static inline void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
    p[2] = (uint8_t)((v >> 16) & 0xFF);
    p[3] = (uint8_t)((v >> 24) & 0xFF);
}

static inline uint16_t get_u16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static inline uint32_t get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ══════════════════════════════════════════════════════════
 *  编码
 *
 *  偏移  长度  字段
 *  0     1     SOF 0x4C
 *  1     1     VER
 *  2     1     TYPE
 *  3     1     FLAGS  ([7]frag [6:5]prio [4]ack)
 *  4     1     SRC
 *  5     1     DST
 *  6     2     SEQ (LE)
 *  8     1     TTL
 *  9     3     RSVD
 *  12    4     T_EXEC (LE)
 *  16    2     LEN (LE)
 *  18    N     PAYLOAD
 *  18+N  4     CRC32 (LE)
 *  22+N  1     EOF 0xAA
 * ══════════════════════════════════════════════════════════ */

size_t lbp_frame_encode(const lbp_frame_t *f, uint8_t *buf, size_t buf_len)
{
    if (!f || !buf) return 0;
    if (f->len > LBP_MAX_PAYLOAD) return 0;
    if (f->len > 0 && !f->payload) return 0;

    size_t total = lbp_frame_wire_size(f->len);
    if (buf_len < total) return 0;

    uint8_t flags = (uint8_t)(((uint8_t)f->prio & 0x03) << 5);
    if (f->fragment) flags |= LBP_FLAG_FRAGMENT;
    if (f->ack_req)  flags |= LBP_FLAG_ACK_REQ;

    buf[0] = LBP_SOF;
    buf[1] = LBP_VER_BYTE;
    buf[2] = f->type;
    buf[3] = flags;
    buf[4] = f->src;
    buf[5] = f->dst;
    put_u16(&buf[6], f->seq);
    buf[8] = f->ttl;
    buf[9] = buf[10] = buf[11] = 0;
    put_u32(&buf[12], f->t_exec_us);
    put_u16(&buf[16], f->len);

    if (f->len) memcpy(&buf[LBP_HDR_SIZE], f->payload, f->len);

    /* CRC 覆盖 SOF..PAYLOAD（与 Python zlib.crc32(hdr+payload) 一致） */
    uint32_t crc = lbp_crc32(buf, LBP_HDR_SIZE + f->len);
    put_u32(&buf[LBP_HDR_SIZE + f->len], crc);
    buf[LBP_HDR_SIZE + f->len + 4] = LBP_EOF;

    return total;
}

/* ══════════════════════════════════════════════════════════
 *  解码
 * ══════════════════════════════════════════════════════════ */

lbp_err_t lbp_frame_decode(const uint8_t *data, size_t len, lbp_frame_t *out)
{
    if (!data || !out) return LBP_ERR_INVALID_ARG;
    if (len < LBP_MIN_FRAME) return LBP_ERR_FRAME;
    if (data[0] != LBP_SOF) return LBP_ERR_FRAME;
    if (data[len - 1] != LBP_EOF) return LBP_ERR_FRAME;

    uint16_t plen = get_u16(&data[16]);
    if (plen > LBP_MAX_PAYLOAD) return LBP_ERR_TOO_BIG;

    size_t expect = lbp_frame_wire_size(plen);
    if (len != expect) return LBP_ERR_FRAME;

    uint32_t crc_recv = get_u32(&data[LBP_HDR_SIZE + plen]);
    uint32_t crc_calc = lbp_crc32(data, LBP_HDR_SIZE + plen);
    if (crc_recv != crc_calc) return LBP_ERR_CRC;

    uint8_t ver = data[1];
    if ((ver >> 4) != LBP_VER_MAJOR) return LBP_ERR_PARSE;

    uint8_t flags = data[3];

    memset(out, 0, sizeof(*out));
    out->type       = data[2];
    out->fragment   = (flags & LBP_FLAG_FRAGMENT) != 0;
    out->ack_req    = (flags & LBP_FLAG_ACK_REQ) != 0;
    out->prio       = (lbp_prio_t)((flags >> 5) & 0x03);
    out->src        = data[4];
    out->dst        = data[5];
    out->seq        = (uint8_t)(get_u16(&data[6]) & 0xFF);   /* 8 位够用 */
    out->ttl        = data[8];
    out->t_exec_us  = get_u32(&data[12]);
    out->len        = plen;
    /* 注意：payload 指向输入缓冲内部，调用方要保证 data 生命周期 */
    out->payload    = plen ? (uint8_t *)&data[LBP_HDR_SIZE] : NULL;

    return LBP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  分片
 * ══════════════════════════════════════════════════════════ */

uint8_t lbp_frag_part_count(uint16_t data_len, uint16_t max_frame_bytes)
{
    uint16_t chunk = lbp_frag_chunk(max_frame_bytes);
    if (chunk == 0) return 0;
    uint32_t n = ((uint32_t)data_len + chunk - 1) / chunk;
    return (uint8_t)(n > LBP_FRAG_MAX_PARTS ? LBP_FRAG_MAX_PARTS : n);
}

lbp_err_t lbp_frag_build(const uint8_t *data, uint16_t data_len,
                         uint8_t gid, uint8_t idx, uint8_t total,
                         uint8_t orig_type, uint16_t max_frame_bytes,
                         uint8_t *out, size_t *out_len)
{
    if (!data || !out || !out_len) return LBP_ERR_INVALID_ARG;
    if (idx >= total || total == 0) return LBP_ERR_INVALID_ARG;

    uint16_t chunk = lbp_frag_chunk(max_frame_bytes);
    if (chunk == 0) return LBP_ERR_INVALID_ARG;

    uint32_t off = (uint32_t)idx * chunk;
    if (off >= data_len) return LBP_ERR_INVALID_ARG;
    uint32_t take = data_len - off;
    if (take > chunk) take = chunk;

    uint8_t hdr[LBP_FRAG_HDR];
    put_u16(&hdr[0], gid);
    hdr[2] = idx;
    hdr[3] = total;
    hdr[4] = orig_type;

    size_t need = lbp_frame_wire_size((uint16_t)(LBP_FRAG_HDR + take));
    if (*out_len < need) return LBP_ERR_NO_MEM;

    /* 临时拷到 out 里再整体编码，避免两次拷贝到栈上大缓冲 */
    memcpy(out, hdr, LBP_FRAG_HDR);
    memcpy(out + LBP_FRAG_HDR, data + off, take);

    lbp_frame_t f;
    memset(&f, 0, sizeof(f));
    f.type      = LBP_MSG_FRAG;
    f.src       = 0;                /* 调用方填 */
    f.dst       = LBP_ADDR_BROADCAST;
    f.seq       = idx;
    f.ttl       = 8;
    f.fragment  = true;
    f.prio      = LBP_PRIO_CONFIG;
    f.len       = (uint16_t)(LBP_FRAG_HDR + take);
    f.payload   = out;

    /* 编码到 out 自身所需的临时区：用调用方给的 out 尾部不够，
     * 所以这里要求调用方额外提供一个同尺寸缓冲。为了不增加接口复杂度，
     * 用静态小缓冲分段编码（帧头 18B + 尾 5B 固定，中间 memmove）。 */
    uint8_t tmp[LBP_HDR_SIZE];
    {
        uint8_t flags = (uint8_t)(((uint8_t)f.prio & 0x03) << 5) | LBP_FLAG_FRAGMENT;
        tmp[0] = LBP_SOF;
        tmp[1] = LBP_VER_BYTE;
        tmp[2] = f.type;
        tmp[3] = flags;
        tmp[4] = f.src;
        tmp[5] = f.dst;
        put_u16(&tmp[6], f.seq);
        tmp[8] = f.ttl;
        tmp[9] = tmp[10] = tmp[11] = 0;
        put_u32(&tmp[12], f.t_exec_us);
        put_u16(&tmp[16], f.len);
    }

    /* 把载荷往后挪 18 字节，前面放帧头 */
    memmove(out + LBP_HDR_SIZE, out, LBP_FRAG_HDR + take);
    memcpy(out, tmp, LBP_HDR_SIZE);
    /* 尾巴：CRC + EOF */
    uint32_t crc = lbp_crc32(out, LBP_HDR_SIZE + LBP_FRAG_HDR + take);
    put_u32(out + LBP_HDR_SIZE + LBP_FRAG_HDR + take, crc);
    out[LBP_HDR_SIZE + LBP_FRAG_HDR + take + 4] = LBP_EOF;

    *out_len = need;
    return LBP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  重组
 * ══════════════════════════════════════════════════════════ */

void lbp_reasm_init(lbp_reasm_t *r, uint32_t timeout_ms)
{
    if (!r) return;
    memset(r, 0, sizeof(*r));
    r->timeout_ms = timeout_ms ? timeout_ms : 2000;
}

static lbp_reasm_slot_t *reasm_find(lbp_reasm_t *r, uint8_t src, uint8_t gid)
{
    for (int i = 0; i < LBP_REASM_MAX_GROUPS; i++) {
        if (r->slots[i].used && r->slots[i].src == src
                && r->slots[i].gid == gid) {
            return &r->slots[i];
        }
    }
    return NULL;
}

static lbp_reasm_slot_t *reasm_alloc(lbp_reasm_t *r)
{
    for (int i = 0; i < LBP_REASM_MAX_GROUPS; i++) {
        if (!r->slots[i].used) {
            memset(&r->slots[i], 0, sizeof(r->slots[i]));
            r->slots[i].used = true;
            return &r->slots[i];
        }
    }
    /* 满了：踢掉最旧的 */
    lbp_reasm_slot_t *oldest = &r->slots[0];
    for (int i = 1; i < LBP_REASM_MAX_GROUPS; i++) {
        if (r->slots[i].last_ms < oldest->last_ms) oldest = &r->slots[i];
    }
    r->groups_dropped++;
    memset(oldest, 0, sizeof(*oldest));
    oldest->used = true;
    return oldest;
}

lbp_err_t lbp_reasm_feed(lbp_reasm_t *r, const lbp_frame_t *frame,
                         const uint8_t **out_data, uint16_t *out_len,
                         uint8_t *out_type)
{
    if (!r || !frame) return LBP_ERR_INVALID_ARG;
    if (frame->type != LBP_MSG_FRAG) return LBP_ERR_PARSE;
    if (frame->len < LBP_FRAG_HDR) return LBP_ERR_PARSE;

    const uint8_t *p = frame->payload;
    uint16_t gid     = get_u16(&p[0]);
    uint8_t  idx     = p[2];
    uint8_t  total   = p[3];
    uint8_t  mtype   = p[4];
    const uint8_t *chunk = p + LBP_FRAG_HDR;
    uint16_t chunk_len = (uint16_t)(frame->len - LBP_FRAG_HDR);

    if (total == 0 || idx >= total) return LBP_ERR_PARSE;

    lbp_reasm_slot_t *s = reasm_find(r, frame->src, (uint8_t)(gid & 0xFF));

    if (idx == 0) {
        /* 首片：新建或重置 */
        s = reasm_alloc(r);
        if (!s) return LBP_ERR_NO_MEM;
        s->gid       = (uint8_t)(gid & 0xFF);
        s->src       = frame->src;
        s->total     = total;
        s->orig_type = mtype;
        s->next_idx  = 0;
        s->received  = 0;
    }

    if (!s) {
        /* 首片丢了 */
        r->loss_detected++;
        return LBP_ERR_PARSE;
    }

    /* 严格顺序：乱序即视为丢片，整组作废 */
    if (idx != s->next_idx) {
        r->loss_detected++;
        s->used = false;
        return LBP_ERR_PARSE;
    }

    if ((uint32_t)s->received + chunk_len > LBP_REASM_BUF_SIZE) {
        s->used = false;
        r->groups_dropped++;
        return LBP_ERR_TOO_BIG;
    }

    memcpy(&s->buf[s->received], chunk, chunk_len);
    s->received = (uint16_t)(s->received + chunk_len);
    s->next_idx++;

    if (s->next_idx < s->total) return LBP_ERR_TIMEOUT;   /* 还没齐 */

    /* 齐了 */
    if (out_data) *out_data = s->buf;
    if (out_len)  *out_len = s->received;
    if (out_type) *out_type = s->orig_type;
    s->used = false;
    r->groups_done++;
    return LBP_OK;
}

void lbp_reasm_tick(lbp_reasm_t *r, uint32_t now_ms)
{
    if (!r) return;
    for (int i = 0; i < LBP_REASM_MAX_GROUPS; i++) {
        lbp_reasm_slot_t *s = &r->slots[i];
        if (!s->used) continue;
        if ((now_ms - s->last_ms) > r->timeout_ms) {
            s->used = false;
            r->groups_dropped++;
        }
    }
}