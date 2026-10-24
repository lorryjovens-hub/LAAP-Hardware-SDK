/*
 * lbp_master.c — LBP 主站实现
 */
#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "lbp_master.h"
#include "lbp_payload.h"

static const char *TAG = "lbp.master";

static inline uint32_t now_us(void)
{
    return (uint32_t)(esp_timer_get_time() & 0xFFFFFFFF);
}

static inline uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* ══════════════════════════════════════════════════════════
 *  发送辅助
 * ══════════════════════════════════════════════════════════ */

static lbp_err_t bus_send_cb(uint32_t can_id, const uint8_t *data,
                             uint8_t dlc, void *user)
{
    lbp_master_t *m = (lbp_master_t *)user;
    return lbp_bus_send(&m->bus, can_id, data, dlc, 20);
}

static lbp_err_t master_send(lbp_master_t *m, uint8_t type, uint8_t dst,
                             lbp_prio_t prio, uint32_t t_exec_us,
                             const uint8_t *payload, uint16_t len)
{
    uint8_t buf[LBP_MAX_FRAME];

    lbp_frame_t f;
    memset(&f, 0, sizeof(f));
    f.type      = type;
    f.src       = LBP_ADDR_MASTER;
    f.dst       = dst;
    f.seq       = m->seq++;
    f.ttl       = 8;
    f.prio      = prio;
    f.t_exec_us = t_exec_us;
    f.len       = len;
    f.payload   = (uint8_t *)payload;

    size_t n = lbp_frame_encode(&f, buf, sizeof(buf));
    if (n == 0) return LBP_ERR_TOO_BIG;

    uint32_t can_id = lbp_tp_can_id(prio, dst);
    return lbp_tp_send(&m->tp, can_id, buf, n, bus_send_cb, m);
}

/* ══════════════ 对端管理 ══════════════ */

lbp_peer_t *lbp_master_find(lbp_master_t *m, uint8_t addr)
{
    for (int i = 0; i < LBP_MASTER_MAX_PEERS; i++) {
        if (m->peers[i].used && m->peers[i].addr == addr) return &m->peers[i];
    }
    return NULL;
}

static lbp_peer_t *peer_alloc(lbp_master_t *m, uint8_t addr)
{
    lbp_peer_t *p = lbp_master_find(m, addr);
    if (p) return p;

    for (int i = 0; i < LBP_MASTER_MAX_PEERS; i++) {
        if (!m->peers[i].used) {
            memset(&m->peers[i], 0, sizeof(m->peers[i]));
            m->peers[i].used = true;
            m->peers[i].addr = addr;
            m->count++;
            return &m->peers[i];
        }
    }
    ESP_LOGW(TAG, "对端表已满（%d），忽略 addr=%u",
             LBP_MASTER_MAX_PEERS, addr);
    return NULL;
}

/* ══════════════════════════════════════════════════════════
 *  帧处理
 * ══════════════════════════════════════════════════════════ */

static void handle_frame(lbp_master_t *m, const lbp_frame_t *f)
{
    switch (f->type) {

    case LBP_MSG_ENUM_ACK: {
        lbp_bmd_t bmd;
        if (lbp_bmd_decode(f->payload, f->len, &bmd) != LBP_OK) {
            m->stat_bad++;
            ESP_LOGW(TAG, "BMD 解码失败（%u B）", f->len);
            return;
        }
        lbp_peer_t *p = peer_alloc(m, f->src);
        if (!p) return;
        p->bmd = bmd;
        p->addr = f->src;
        p->online = true;
        p->dof = bmd.dof;
        p->last_seen_ms = now_ms();
        m->stat_enum_ack++;
        ESP_LOGI(TAG, "发现 addr=%u  %s  %uDOF  %.2fkg  caps=0x%X",
                 f->src, bmd.name, bmd.dof, bmd.mass_kg, (unsigned)bmd.caps);
        break;
    }

    case LBP_MSG_TOPO_ACK: {
        uint8_t addr = 0, port = 0, n = 0;
        uint8_t cp[LBP_TOPO_MAX_CHILDREN], ca[LBP_TOPO_MAX_CHILDREN];
        if (lbp_topo_ack_decode(f->payload, f->len, &addr, &port,
                                cp, ca, &n) != LBP_OK) {
            m->stat_bad++;
            return;
        }
        lbp_peer_t *p = lbp_master_find(m, addr);
        if (!p) p = peer_alloc(m, addr);
        if (!p) return;
        p->mount_port = port;
        p->child_count = n;
        memcpy(p->child_ports, cp, n);
        memcpy(p->child_addrs, ca, n);
        p->last_seen_ms = now_ms();
        m->stat_topo_ack++;
        break;
    }

    case LBP_MSG_TELEM: {
        uint8_t addr = 0, dof = 0;
        float q[LBP_MAX_JOINTS], tq[LBP_MAX_JOINTS];
        int8_t temp = 0;
        if (lbp_telem_decode(f->payload, f->len, &addr, q, tq, &temp,
                             LBP_MAX_JOINTS, &dof) != LBP_OK) {
            m->stat_bad++;
            return;
        }
        lbp_peer_t *p = lbp_master_find(m, addr);
        if (!p) return;
        p->dof = dof;
        memcpy(p->q, q, sizeof(float) * dof);
        memcpy(p->torque, tq, sizeof(float) * dof);
        p->temp_c = temp;
        p->telem_valid = true;
        p->last_seen_ms = now_ms();
        m->stat_telem++;
        break;
    }

    case LBP_MSG_REFLEX: {
        uint8_t addr = 0, code = 0, joint = 0;
        float value = 0;
        if (lbp_reflex_decode(f->payload, f->len, &addr, &code, &joint,
                              &value) != LBP_OK) {
            m->stat_bad++;
            return;
        }
        lbp_peer_t *p = lbp_master_find(m, addr);
        if (p) {
            p->reflex_count++;
            p->last_reflex_code = code;
        }
        m->stat_reflex++;
        ESP_LOGW(TAG, "⚠ REFLEX addr=%u code=0x%02X joint=%u value=%.2f",
                 addr, code, joint, value);
        break;
    }

    case LBP_MSG_HEARTBEAT: {
        lbp_peer_t *p = lbp_master_find(m, f->src);
        if (p) {
            p->last_seen_ms = now_ms();
            p->online = true;
        }
        break;
    }

    default:
        break;
    }
}

static void on_tp_frame(uint32_t can_id, const uint8_t *data, size_t len,
                        void *user)
{
    (void)can_id;
    lbp_master_t *m = (lbp_master_t *)user;

    lbp_frame_t f;
    if (lbp_frame_decode(data, len, &f) != LBP_OK) {
        m->stat_bad++;
        return;
    }

    if (f.type == LBP_MSG_FRAG) {
        const uint8_t *full = NULL;
        uint16_t flen = 0;
        uint8_t ftype = 0;
        if (lbp_reasm_feed(&m->reasm, &f, &full, &flen, &ftype) == LBP_OK) {
            lbp_frame_t inner;
            memset(&inner, 0, sizeof(inner));
            inner.type    = ftype;
            inner.src     = f.src;
            inner.dst     = f.dst;
            inner.prio    = f.prio;
            inner.len     = flen;
            inner.payload = (uint8_t *)full;
            handle_frame(m, &inner);
        }
        return;
    }

    handle_frame(m, &f);
}

/* ══════════════════════════════════════════════════════════
 *  生命周期
 * ══════════════════════════════════════════════════════════ */

lbp_err_t lbp_master_init(lbp_master_t *m, const lbp_bus_cfg_t *cfg)
{
    if (!m || !cfg) return LBP_ERR_INVALID_ARG;
    memset(m, 0, sizeof(*m));

    lbp_err_t e = lbp_bus_init(&m->bus, cfg);
    if (e != LBP_OK) return e;

    lbp_tp_init(&m->tp, 500);
    lbp_reasm_init(&m->reasm, 2000);
    m->seq = 1;

    ESP_LOGI(TAG, "主站就绪");
    return LBP_OK;
}

void lbp_master_deinit(lbp_master_t *m)
{
    if (m) lbp_bus_deinit(&m->bus);
}

/* ══════════════════════════════════════════════════════════
 *  枚举与拓扑
 * ══════════════════════════════════════════════════════════ */

void lbp_master_poll(lbp_master_t *m, uint32_t timeout_ms)
{
    if (!m) return;
    uint32_t id;
    uint8_t data[8], dlc;
    uint32_t deadline = now_ms() + timeout_ms;

    do {
        lbp_err_t e = lbp_bus_recv(&m->bus, &id, data, &dlc, 10);
        if (e == LBP_OK) {
            lbp_tp_feed(&m->tp, id, data, dlc, on_tp_frame, m);
        }
        lbp_tp_tick(&m->tp, now_ms());
        lbp_reasm_tick(&m->reasm, now_ms());
    } while ((int32_t)(now_ms() - deadline) < 0);
}

int lbp_master_enumerate(lbp_master_t *m, uint32_t timeout_ms)
{
    if (!m) return -1;

    /* 清空旧记录 */
    memset(m->peers, 0, sizeof(m->peers));
    m->count = 0;

    ESP_LOGI(TAG, "广播 ENUM_REQ…");
    lbp_err_t e = master_send(m, LBP_MSG_ENUM_REQ, LBP_ADDR_BROADCAST,
                              LBP_PRIO_CONFIG, 0, NULL, 0);
    if (e != LBP_OK) {
        ESP_LOGE(TAG, "ENUM_REQ 发送失败");
        return -1;
    }

    /* 各模块的 BMD 会分片回传，等到超时 */
    lbp_master_poll(m, timeout_ms ? timeout_ms : 1500);

    int found = 0;
    for (int i = 0; i < LBP_MASTER_MAX_PEERS; i++) {
        if (m->peers[i].used) found++;
    }
    ESP_LOGI(TAG, "枚举完成：%d 个模块", found);
    return found;
}

int lbp_master_query_topology(lbp_master_t *m, uint32_t timeout_ms)
{
    if (!m) return -1;

    int acked = 0;
    for (int i = 0; i < LBP_MASTER_MAX_PEERS; i++) {
        if (!m->peers[i].used) continue;
        uint8_t addr = m->peers[i].addr;
        uint32_t before = m->stat_topo_ack;

        master_send(m, LBP_MSG_TOPO_REQ, addr, LBP_PRIO_CONFIG, 0, NULL, 0);
        lbp_master_poll(m, 200);          /* 单个节点等 200ms 够 */

        if (m->stat_topo_ack > before) acked++;
    }

    ESP_LOGI(TAG, "拓扑查询：%d/%d 应答", acked, m->count);
    (void)timeout_ms;
    return acked;
}

/* ══════════════════════════════════════════════════════════
 *  控制
 * ══════════════════════════════════════════════════════════ */

lbp_err_t lbp_master_send_cmd(lbp_master_t *m, uint8_t addr,
                              const float *q, uint8_t dof,
                              uint32_t t_exec_us)
{
    if (!m || !q) return LBP_ERR_INVALID_ARG;

    uint8_t buf[80];
    size_t len = lbp_cmd_encode(0, q, dof, buf, sizeof(buf));
    if (len == 0) return LBP_ERR_TOO_BIG;

    return master_send(m, LBP_MSG_CMD, addr, LBP_PRIO_CONTROL,
                       t_exec_us, buf, (uint16_t)len);
}

lbp_err_t lbp_master_broadcast_stop(lbp_master_t *m)
{
    if (!m) return LBP_ERR_INVALID_ARG;
    return master_send(m, LBP_MSG_SAFE_STOP, LBP_ADDR_BROADCAST,
                       LBP_PRIO_SAFETY, 0, NULL, 0);
}

lbp_err_t lbp_master_clock_sync(lbp_master_t *m, uint32_t t1_us)
{
    if (!m) return LBP_ERR_INVALID_ARG;
    uint8_t buf[8];
    size_t len = lbp_clock_sync_encode(t1_us, buf, sizeof(buf));
    return master_send(m, LBP_MSG_CLOCK_SYNC, LBP_ADDR_BROADCAST,
                       LBP_PRIO_CONFIG, 0, buf, (uint16_t)len);
}

/* ══════════════════════════════════════════════════════════
 *  拓扑导出
 * ══════════════════════════════════════════════════════════ */

void lbp_master_print_topology(lbp_master_t *m)
{
    if (!m) return;
    ESP_LOGI(TAG, "── 拓扑 ──");
    for (int i = 0; i < LBP_MASTER_MAX_PEERS; i++) {
        lbp_peer_t *p = &m->peers[i];
        if (!p->used) continue;
        ESP_LOGI(TAG, "  addr=%2u  port=%u  %-16s %uDOF %.2fkg %s",
                 p->addr, p->mount_port, p->bmd.name, p->bmd.dof,
                 p->bmd.mass_kg, p->telem_valid ? "" : "(无遥测)");
    }
    ESP_LOGI(TAG, "── 合计 %u 模块 ──", m->count);
}

size_t lbp_master_topology_json(lbp_master_t *m, char *out, size_t out_len)
{
    if (!m || !out || out_len < 64) return 0;

    size_t off = 0;
    int n = snprintf(out + off, out_len - off,
                     "{\"root\":%d,\"modules\":[", LBP_ADDR_MASTER);
    if (n < 0 || (size_t)n >= out_len - off) return 0;
    off += (size_t)n;

    bool first = true;
    for (int i = 0; i < LBP_MASTER_MAX_PEERS; i++) {
        lbp_peer_t *p = &m->peers[i];
        if (!p->used) continue;

        n = snprintf(out + off, out_len - off,
                     "%s{\"addr\":%u,\"port\":%u,\"name\":\"%s\","
                     "\"dof\":%u,\"mass\":%.3f,\"caps\":%u,\"serial\":%llu}",
                     first ? "" : ",",
                     p->addr, p->mount_port, p->bmd.name, p->bmd.dof,
                     p->bmd.mass_kg, (unsigned)p->bmd.caps,
                     (unsigned long long)p->bmd.serial);
        if (n < 0 || (size_t)n >= out_len - off) return 0;
        off += (size_t)n;
        first = false;
    }

    n = snprintf(out + off, out_len - off, "]}");
    if (n < 0 || (size_t)n >= out_len - off) return 0;
    off += (size_t)n;

    return off;
}