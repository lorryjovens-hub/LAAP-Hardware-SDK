/*
 * lbp_node.c — LBP 从站实现
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "lbp_node.h"
#include "lbp_payload.h"

static const char *TAG = "lbp.node";

static inline uint32_t now_us(void)
{
    return (uint32_t)(esp_timer_get_time() & 0xFFFFFFFF);
}

static inline uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* ══════════════════════════════════════════════════════════
 *  端口 ID 读取
 *
 *  硬件：模块侧 ID0/ID1/ID2 三根跳线，接 GND 或悬空；
 *        主机侧 GPIO 上拉输入读电平。
 *  pos_id = ID0 | (ID1<<1) | (ID2<<2)
 * ══════════════════════════════════════════════════════════ */

uint8_t lbp_read_port_id(gpio_num_t id0, gpio_num_t id1, gpio_num_t id2)
{
    uint8_t v = 0;
    if (id0 != GPIO_NUM_NC && gpio_get_level(id0)) v |= 0x01;
    if (id1 != GPIO_NUM_NC && gpio_get_level(id1)) v |= 0x02;
    if (id2 != GPIO_NUM_NC && gpio_get_level(id2)) v |= 0x04;
    return v;
}

bool lbp_is_present(gpio_num_t present_pin)
{
    if (present_pin == GPIO_NUM_NC) return true;      /* 未配则视为在位 */
    /* 模块侧短接 GND，主机侧上拉 → 插入时读到低电平 */
    return gpio_get_level(present_pin) == 0;
}

/* ══════════════════════════════════════════════════════════
 *  发送辅助
 * ══════════════════════════════════════════════════════════ */

static lbp_err_t bus_send_cb(uint32_t can_id, const uint8_t *data,
                             uint8_t dlc, void *user)
{
    lbp_node_t *n = (lbp_node_t *)user;
    return lbp_bus_send(&n->bus, can_id, data, dlc, 20);
}

/** 编码一个 LBP 帧并通过 TP 发出（自动分段） */
static lbp_err_t node_send(lbp_node_t *n, uint8_t type, uint8_t dst,
                           lbp_prio_t prio, uint32_t t_exec_us,
                           const uint8_t *payload, uint16_t len)
{
    static uint8_t s_seq = 0;
    uint8_t buf[LBP_MAX_FRAME];

    lbp_frame_t f;
    memset(&f, 0, sizeof(f));
    f.type      = type;
    f.src       = n->cfg.addr;
    f.dst       = dst;
    f.seq       = s_seq++;
    f.ttl       = 8;
    f.prio      = prio;
    f.t_exec_us = t_exec_us;
    f.len       = len;
    f.payload   = (uint8_t *)payload;

    size_t n_out = lbp_frame_encode(&f, buf, sizeof(buf));
    if (n_out == 0) return LBP_ERR_TOO_BIG;

    uint32_t can_id = lbp_tp_can_id(prio, dst);
    return lbp_tp_send(&n->tp, can_id, buf, n_out, bus_send_cb, n);
}

/* ══════════════════════════════════════════════════════════
 *  帧处理
 * ══════════════════════════════════════════════════════════ */

static void handle_frame(lbp_node_t *n, const lbp_frame_t *f)
{
    /* 只处理发给我的或广播 */
    if (f->dst != n->cfg.addr && f->dst != LBP_ADDR_BROADCAST) return;

    switch (f->type) {

    case LBP_MSG_ENUM_REQ: {
        /* 回 BMD（自动分片） */
        uint8_t buf[512];
        size_t len = lbp_bmd_encode(&n->cfg.bmd, buf, sizeof(buf));
        if (len == 0) {
            ESP_LOGE(TAG, "BMD 编码失败");
            n->stat_bad++;
            return;
        }
        lbp_err_t e = node_send(n, LBP_MSG_ENUM_ACK, LBP_ADDR_MASTER,
                                LBP_PRIO_CONFIG, 0, buf, (uint16_t)len);
        n->stat_enum++;
        ESP_LOGI(TAG, "ENUM_ACK → 主机（BMD %uB, %s）",
                 (unsigned)len, e == LBP_OK ? "ok" : "失败");
        break;
    }

    case LBP_MSG_TOPO_REQ: {
        uint8_t buf[8];
        size_t len = lbp_topo_ack_encode(n->cfg.addr, n->cfg.mount_port,
                                         NULL, NULL, 0, buf, sizeof(buf));
        node_send(n, LBP_MSG_TOPO_ACK, LBP_ADDR_MASTER,
                  LBP_PRIO_CONFIG, 0, buf, (uint16_t)len);
        n->stat_topo++;
        ESP_LOGD(TAG, "TOPO_ACK port=%u", n->cfg.mount_port);
        break;
    }

    case LBP_MSG_CMD: {
        uint8_t flags = 0;
        uint8_t dof = 0;
        float q[LBP_MAX_JOINTS];
        if (lbp_cmd_decode(f->payload, f->len, &flags, q,
                           LBP_MAX_JOINTS, &dof) != LBP_OK) {
            n->stat_bad++;
            return;
        }
        if (flags & LBP_CMD_FLAG_ESTOP) {
            n->pending = false;
            if (n->cfg.on_safe_stop) n->cfg.on_safe_stop(n->cfg.user);
            return;
        }
        n->stat_cmd++;

        if (f->t_exec_us == 0) {
            /* 立即执行 */
            if (n->cfg.on_cmd) n->cfg.on_cmd(q, dof, 0, n->cfg.user);
        } else {
            /* 存起来等 T_EXEC */
            memcpy(n->pending_q, q, sizeof(float) * dof);
            n->pending_dof = dof;
            n->pending_deadline_us = f->t_exec_us;
            n->pending = true;
        }
        break;
    }

    case LBP_MSG_SAFE_STOP:
        n->pending = false;
        if (n->cfg.on_safe_stop) n->cfg.on_safe_stop(n->cfg.user);
        ESP_LOGW(TAG, "收到 SAFE_STOP");
        break;

    case LBP_MSG_CLOCK_SYNC: {
        uint64_t t1 = 0;
        if (lbp_clock_sync_decode(f->payload, f->len, &t1) == LBP_OK) {
            /* 简化同步：直接把本地时钟对齐到主机的 t1 域。
             * 生产实现应走 PTP 四时间戳，见 LBP_PROTOCOL_SPEC §3.8 */
            ESP_LOGD(TAG, "CLOCK_SYNC t1=%llu（本地 %u）",
                     (unsigned long long)t1, (unsigned)now_us());
        }
        break;
    }

    default:
        break;
    }
}

/* TP 收齐一帧后的回调 */
static void on_tp_frame(uint32_t can_id, const uint8_t *data, size_t len,
                        void *user)
{
    (void)can_id;
    lbp_node_t *n = (lbp_node_t *)user;

    lbp_frame_t f;
    lbp_err_t e = lbp_frame_decode(data, len, &f);
    if (e != LBP_OK) {
        n->stat_bad++;
        ESP_LOGW(TAG, "帧解码失败: 0x%X", e);
        return;
    }

    /* FRAG：交给重组器，再递归处理 */
    if (f.type == LBP_MSG_FRAG) {
        const uint8_t *full = NULL;
        uint16_t flen = 0;
        uint8_t ftype = 0;
        if (lbp_reasm_feed(&n->reasm, &f, &full, &flen, &ftype) == LBP_OK) {
            lbp_frame_t inner;
            memset(&inner, 0, sizeof(inner));
            inner.type      = ftype;
            inner.src       = f.src;
            inner.dst       = f.dst;
            inner.prio      = f.prio;
            inner.t_exec_us = f.t_exec_us;
            inner.len       = flen;
            inner.payload   = (uint8_t *)full;
            handle_frame(n, &inner);
        }
        return;
    }

    handle_frame(n, &f);
}

/* ══════════════════════════════════════════════════════════
 *  接收任务
 * ══════════════════════════════════════════════════════════ */

static void node_task(void *arg)
{
    lbp_node_t *n = (lbp_node_t *)arg;
    uint32_t id;
    uint8_t data[8], dlc;

    ESP_LOGI(TAG, "节点 %u 启动（挂载端口 %u）", n->cfg.addr, n->cfg.mount_port);

    while (n->running) {
        lbp_err_t e = lbp_bus_recv(&n->bus, &id, data, &dlc, 20);
        if (e == LBP_OK) {
            lbp_tp_feed(&n->tp, id, data, dlc, on_tp_frame, n);
        }
        lbp_tp_tick(&n->tp, now_ms());
        lbp_reasm_tick(&n->reasm, now_ms());

        /* T_EXEC 到期检查（20ms 精度，够技能层用） */
        lbp_node_tick(n, now_us());
    }

    vTaskDelete(NULL);
}

void lbp_node_tick(lbp_node_t *n, uint32_t now)
{
    if (!n || !n->pending) return;
    /* 时间比较要注意 32 位回绕 */
    if ((int32_t)(now - n->pending_deadline_us) >= 0) {
        n->pending = false;
        if (n->cfg.on_cmd) {
            n->cfg.on_cmd(n->pending_q, n->pending_dof,
                          n->pending_deadline_us, n->cfg.user);
        }
    }
}

/* ══════════════════════════════════════════════════════════
 *  对外 API
 * ══════════════════════════════════════════════════════════ */

lbp_err_t lbp_node_start(lbp_node_t *node, const lbp_node_cfg_t *cfg)
{
    if (!node || !cfg) return LBP_ERR_INVALID_ARG;

    memset(node, 0, sizeof(*node));
    node->cfg = *cfg;
    node->cfg.bmd.bus_addr = cfg->addr;
    node->cfg.bmd.bus_profile = 1;      /* CAN */
    if (node->cfg.bmd.name[0] == 0) {
        strncpy(node->cfg.bmd.name, "lbp-node", LBP_NAME_LEN - 1);
    }

    lbp_err_t e = lbp_bus_init(&node->bus, &cfg->bus);
    if (e != LBP_OK) return e;

    lbp_tp_init(&node->tp, 500);
    lbp_reasm_init(&node->reasm, 2000);

    node->running = true;
    if (xTaskCreate(node_task, "lbp_node", 6144, node, 8, NULL) != pdPASS) {
        node->running = false;
        return LBP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "BMD: %s %uDOF %.2fkg ports=%u",
             node->cfg.bmd.name, node->cfg.bmd.dof,
             node->cfg.bmd.mass_kg, node->cfg.bmd.port_count);
    return LBP_OK;
}

void lbp_node_stop(lbp_node_t *node)
{
    if (!node) return;
    node->running = false;
    vTaskDelay(pdMS_TO_TICKS(50));
    lbp_bus_deinit(&node->bus);
}

lbp_err_t lbp_node_send_telem(lbp_node_t *node, const float *q,
                              const float *torque, int8_t temp_c,
                              bool has_temp)
{
    if (!node || !q) return LBP_ERR_INVALID_ARG;

    uint8_t buf[96];
    size_t len = lbp_telem_encode(node->cfg.addr, q, torque, temp_c,
                                  has_temp, node->cfg.bmd.dof,
                                  buf, sizeof(buf));
    if (len == 0) return LBP_ERR_TOO_BIG;

    lbp_err_t e = node_send(node, LBP_MSG_TELEM, LBP_ADDR_MASTER,
                            LBP_PRIO_CONTROL, 0, buf, (uint16_t)len);
    if (e == LBP_OK) node->stat_telem++;
    return e;
}

lbp_err_t lbp_node_send_reflex(lbp_node_t *node, uint8_t code,
                               uint8_t joint, float value)
{
    if (!node) return LBP_ERR_INVALID_ARG;

    uint8_t buf[8];
    size_t len = lbp_reflex_encode(node->cfg.addr, code, joint, value,
                                   buf, sizeof(buf));
    lbp_err_t e = node_send(node, LBP_MSG_REFLEX, LBP_ADDR_MASTER,
                            LBP_PRIO_SAFETY, 0, buf, (uint16_t)len);
    if (e == LBP_OK) {
        node->stat_reflex++;
        ESP_LOGW(TAG, "REFLEX code=0x%02X joint=%u value=%.2f",
                 code, joint, value);
    }
    return e;
}