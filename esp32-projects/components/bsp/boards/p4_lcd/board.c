/*
 * board.c — ESP32-P4 + LCD 大屏终端
 *
 * 能力：大屏（MIPI-DSI）+ 触摸 + 音频
 * 没有：舵机、电机
 *
 * ## 用途
 *
 * 这是「远程办公终端」的板子 —— 屏幕显示电脑桌面流，
 * 语音控制电脑（配合 laaper/hub/screen_stream.py + computer_use）。
 *
 * ## 两个必须知道的事
 *
 * 1. **没有 WiFi**：P4 必须外挂 ESP32-C6 + esp_hosted 组件。
 *    BSP 不管网络，应用层自己起 esp_hosted。
 *
 * 2. **DSI 屏驱动要单独加**：MIPI-DSI 面板驱动（ST7703 等）不在
 *    esp_lcd 主线，需要 idf.py add-dependency 对应的 esp_lcd_xxx。
 *    这里给出 DSI 配置结构，驱动未接时会降级为「无显示」。
 */
#include "esp_log.h"
#include "bsp.h"
#include "bsp_board.h"
#include "bsp_common.h"
#include "board_pins.h"

static const char *TAG = "bsp.p4lcd";

static void *s_panel = NULL;
static void *s_tx = NULL, *s_rx = NULL;
static void *s_i2c_bus = NULL;

static const bsp_info_t s_info = {
    .name = "ESP32-P4 大屏终端",
    .id = "p4_lcd",
    .chip = "esp32p4",
    .caps = BSP_CAP_DISPLAY | BSP_CAP_TOUCH | BSP_CAP_AUDIO_OUT
          | BSP_CAP_AUDIO_IN | BSP_CAP_I2C,
    .display_w = BSP_LCD_W,
    .display_h = BSP_LCD_H,
    .display_driver = "mipi-dsi",
    .servo_count = 0,
    .note = "P4 无内置 WiFi，必须外挂 ESP32-C6 + esp_hosted",
};

const bsp_info_t *bsp_board_info(void)
{
    return &s_info;
}

/* ══════════════ 显示（MIPI-DSI）══════════════ */

esp_err_t bsp_display_init(void)
{
#if defined(CONFIG_BSP_P4_DSI) && CONFIG_BSP_P4_DSI
    /* MIPI-DSI 初始化（需 esp_lcd 的 DSI + 面板驱动）
     *
     * esp_lcd_dsi_bus_handle_t dsi_bus = NULL;
     * esp_lcd_dsi_bus_config_t bus_cfg = {
     *     .bus_id = 0,
     *     .num_data_lanes = BSP_MIPI_DSI_LANE_NUM,
     *     .phy_clk_src = MIPI_DSI_PHY_CLK_SRC_DEFAULT,
     *     .lane_bit_rate_mbps = BSP_MIPI_DSI_LANE_MBPS,
     * };
     * esp_lcd_new_dsi_bus(&bus_cfg, &dsi_bus);
     *
     * esp_lcd_panel_io_dsi_config_t io_cfg = { .bus = dsi_bus };
     * esp_lcd_new_panel_io_dsi(dsi_bus, &io_cfg, &io);
     *
     * esp_lcd_new_panel_st7703(io, &panel_cfg, &panel);   // 面板驱动要另装
     * esp_lcd_panel_reset(panel);
     * esp_lcd_panel_init(panel);
     * esp_lcd_panel_disp_on_off(panel, true);
     *
     * 然后 lvgl_port_add_disp(...) 注册，尺寸 1024x600。
     */
    ESP_LOGW(TAG, "CONFIG_BSP_P4_DSI 已开，DSI 面板驱动待接入");
    return ESP_ERR_NOT_SUPPORTED;
#else
    ESP_LOGW(TAG, "P4 DSI 屏未启用（需 CONFIG_BSP_P4_DSI + 面板驱动组件）");
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t bsp_display_set_brightness(uint8_t percent)
{
    return bsp_common_lcd_set_brightness(BSP_LEDC_CH_BL, percent);
}

void *bsp_display_panel(void) { return s_panel; }

/* ══════════════ I2C（触摸 + codec）══════════════ */

esp_err_t bsp_i2c_init(void)
{
    if (s_i2c_bus) return ESP_OK;

    i2c_master_bus_config_t cfg = {
        .i2c_port = 0,
        .sda_io_num = BSP_I2C_SDA,
        .scl_io_num = BSP_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus = NULL;
    esp_err_t e = i2c_new_master_bus(&cfg, &bus);
    if (e == ESP_OK) {
        s_i2c_bus = (void *)bus;
        ESP_LOGI(TAG, "I2C 就绪（触摸/codec）");
    }
    return e;
}

void *bsp_i2c_bus(void) { return s_i2c_bus; }

/* ══════════════ 音频 ══════════════ */

esp_err_t bsp_audio_init(void)
{
    bsp_i2s_cfg_t cfg = {
        .bclk = BSP_I2S_BCLK,
        .lrck = BSP_I2S_LRCK,
        .dout = BSP_I2S_DOUT,
        .din = BSP_I2S_DIN,
        .sample_rate = BSP_I2S_SAMPLE_RATE,
        .port = 0,
        .mono = false,
    };
    return bsp_common_i2s_init(&cfg, &s_tx, &s_rx);
}

void *bsp_audio_tx(void) { return s_tx; }
void *bsp_audio_rx(void) { return s_rx; }
uint32_t bsp_audio_sample_rate(void) { return BSP_I2S_SAMPLE_RATE; }

/* ══════════════ 触摸（GT911，走 I2C）══════════════ */

esp_err_t bsp_touch_init(void)
{
    esp_err_t e = bsp_common_gpio_in(BSP_TOUCH_INT, true, false);
    if (e != ESP_OK) return e;

    /* GT911 需要走 I2C 读坐标，完整实现要用 esp_lcd_touch_gt911 组件。
     * 这里先把 INT 引脚配好，坐标读取留给应用层。 */
    ESP_LOGI(TAG, "触摸 INT 就绪（GT911 坐标读取需 esp_lcd_touch 组件）");
    return ESP_OK;
}

bool bsp_touch_pressed(void)
{
    /* GT911 的 INT 低电平有效 */
    return gpio_get_level(BSP_TOUCH_INT) == 0;
}