/*
 * lbp_bus.h — TWAI（CAN 2.0B）驱动封装
 *
 * ⚠ ESP32 系列的 TWAI 只支持 CAN 2.0B（最高 1 Mbps），**不支持 CAN FD**。
 *   需要 CAN FD 时必须外挂 MCP2518FD（SPI 接）。
 *
 * 发射/接收都是阻塞式，超时由调用方控制。
 */
#pragma once

#include "lbp_types.h"
#include "driver/gpio.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    gpio_num_t gpio_tx;
    gpio_num_t gpio_rx;
    uint32_t   bitrate;         /* 通常 1000000 */
    bool       loopback;        /* 自测用：自发自收，不接总线 */
} lbp_bus_cfg_t;

typedef struct {
    bool     inited;
    uint32_t tx_count;
    uint32_t rx_count;
    uint32_t tx_fail;
} lbp_bus_t;

lbp_err_t lbp_bus_init(lbp_bus_t *bus, const lbp_bus_cfg_t *cfg);
void      lbp_bus_deinit(lbp_bus_t *bus);

/** 发一个 CAN 帧（标准帧 11 位 ID） */
lbp_err_t lbp_bus_send(lbp_bus_t *bus, uint32_t can_id,
                       const uint8_t *data, uint8_t dlc,
                       uint32_t timeout_ms);

/** 收一个 CAN 帧。timeout_ms=0 表示立即返回 */
lbp_err_t lbp_bus_recv(lbp_bus_t *bus, uint32_t *can_id,
                       uint8_t *data, uint8_t *dlc, uint32_t timeout_ms);

/** 总线状态（错误计数等） */
void lbp_bus_status(lbp_bus_t *bus, uint32_t *arb_lost,
                    uint32_t *bus_err, uint32_t *tx_err, uint32_t *rx_err);

#ifdef __cplusplus
}
#endif