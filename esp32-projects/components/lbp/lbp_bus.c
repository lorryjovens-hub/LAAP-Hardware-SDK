/*
 * lbp_bus.c — TWAI 驱动封装
 */
#include "esp_log.h"
#include "esp_check.h"
#include "driver/twai.h"
#include "lbp_bus.h"

static const char *TAG = "lbp.bus";

lbp_err_t lbp_bus_init(lbp_bus_t *bus, const lbp_bus_cfg_t *cfg)
{
    if (!bus || !cfg) return LBP_ERR_INVALID_ARG;
    if (bus->inited) return LBP_OK;

    twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT(
        cfg->gpio_tx, cfg->gpio_rx,
        cfg->loopback ? TWAI_MODE_NO_ACK : TWAI_MODE_NORMAL);
    /* NO_ACK 模式：不发 ACK，可用于单节点自测（不接总线也不报错） */

    twai_timing_config_t t;
    switch (cfg->bitrate) {
    case 1000000: t = (twai_timing_config_t)TWAI_TIMING_CONFIG_1MBITS(); break;
    case 500000:  t = (twai_timing_config_t)TWAI_TIMING_CONFIG_500KBITS(); break;
    case 250000:  t = (twai_timing_config_t)TWAI_TIMING_CONFIG_250KBITS(); break;
    case 125000:  t = (twai_timing_config_t)TWAI_TIMING_CONFIG_125KBITS(); break;
    default:
        ESP_LOGE(TAG, "不支持的速率 %u（1M/500k/250k/125k）",
                 (unsigned)cfg->bitrate);
        return LBP_ERR_INVALID_ARG;
    }

    twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t e = twai_driver_install(&g, &t, &f);
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "twai_driver_install: %s", esp_err_to_name(e));
        return LBP_ERR_BUS;
    }
    e = twai_start();
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "twai_start: %s", esp_err_to_name(e));
        return LBP_ERR_BUS;
    }

    bus->inited = true;
    bus->tx_count = bus->rx_count = bus->tx_fail = 0;
    ESP_LOGI(TAG, "TWAI 就绪 %u bps（CAN 2.0B，TX=%d RX=%d）",
             (unsigned)cfg->bitrate, cfg->gpio_tx, cfg->gpio_rx);
    return LBP_OK;
}

void lbp_bus_deinit(lbp_bus_t *bus)
{
    if (!bus || !bus->inited) return;
    twai_stop();
    twai_driver_uninstall();
    bus->inited = false;
}

lbp_err_t lbp_bus_send(lbp_bus_t *bus, uint32_t can_id,
                       const uint8_t *data, uint8_t dlc,
                       uint32_t timeout_ms)
{
    if (!bus || !bus->inited || !data) return LBP_ERR_INVALID_ARG;
    if (dlc > 8) dlc = 8;

    twai_message_t m = {0};
    m.identifier = can_id & 0x7FF;      /* 标准帧 11 位 */
    m.extd = 0;
    m.data_length_code = dlc;
    for (int i = 0; i < dlc; i++) m.data[i] = data[i];

    esp_err_t e = twai_transmit(&m, pdMS_TO_TICKS(timeout_ms ? timeout_ms : 10));
    if (e != ESP_OK) {
        bus->tx_fail++;
        return LBP_ERR_BUS;
    }
    bus->tx_count++;
    return LBP_OK;
}

lbp_err_t lbp_bus_recv(lbp_bus_t *bus, uint32_t *can_id,
                       uint8_t *data, uint8_t *dlc, uint32_t timeout_ms)
{
    if (!bus || !bus->inited || !can_id || !data || !dlc) {
        return LBP_ERR_INVALID_ARG;
    }

    twai_message_t m = {0};
    esp_err_t e = twai_receive(&m, pdMS_TO_TICKS(timeout_ms));
    if (e == ESP_ERR_TIMEOUT) return LBP_ERR_TIMEOUT;
    if (e != ESP_OK) return LBP_ERR_BUS;

    *can_id = m.identifier;
    *dlc = m.data_length_code > 8 ? 8 : m.data_length_code;
    for (int i = 0; i < *dlc; i++) data[i] = m.data[i];
    bus->rx_count++;
    return LBP_OK;
}

void lbp_bus_status(lbp_bus_t *bus, uint32_t *arb_lost,
                    uint32_t *bus_err, uint32_t *tx_err, uint32_t *rx_err)
{
    (void)bus;
    twai_status_info_t st;
    if (twai_get_status_info(&st) != ESP_OK) return;
    if (arb_lost) *arb_lost = st.arb_lost_count;
    if (bus_err)  *bus_err  = st.bus_error_count;
    if (tx_err)   *tx_err   = st.tx_error_counter;
    if (rx_err)   *rx_err   = st.rx_error_counter;
}