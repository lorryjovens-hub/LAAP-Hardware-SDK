/*
 * board.c — ESP32-S3-Korvo-2（乐鑫官方语音板）
 *
 * 能力：显示 + 双麦 + 功放 + 按键 + SD
 * 没有：舵机、电机（这是语音板）
 *
 * ## ⚠ codec 初始化需要额外组件
 *
 * Korvo-2 的音频要经过 ES7210（ADC）+ ES8311（DAC），
 * 必须用 esp_codec_dev 配置。启用方法：
 *
 *     idf.py add-dependency "espressif/esp_codec_dev"
 *
 * 然后在 menuconfig 里打开 CONFIG_BSP_KORVO_CODEC。
 * 未启用时音频会走裸 I2S（能出声但音量/增益不受控）。
 */
#include "esp_log.h"
#include "bsp.h"
#include "bsp_board.h"
#include "bsp_common.h"
#include "board_pins.h"

static const char *TAG = "bsp.korvo2";

static void *s_panel = NULL;
static void *s_tx = NULL, *s_rx = NULL;

/* ══════════════ 板级信息 ══════════════ */

static const bsp_info_t s_info = {
    .name = "ESP32-S3-Korvo-2 语音板",
    .id = "s3_korvo2",
    .chip = "esp32s3",
    .caps = BSP_CAP_DISPLAY | BSP_CAP_AUDIO_OUT | BSP_CAP_AUDIO_IN
          | BSP_CAP_BUTTON | BSP_CAP_I2C | BSP_CAP_SDCARD,
    .display_w = 240,
    .display_h = 240,
    .display_driver = "st7789",
    .servo_count = 0,
    .note = "音频经 ES7210/ES8311 codec，需 esp_codec_dev 组件",
};

const bsp_info_t *bsp_board_info(void)
{
    return &s_info;
}

/* ══════════════ 显示 ══════════════ */

esp_err_t bsp_display_init(void)
{
    bsp_lcd_spi_cfg_t cfg = {
        .sclk = BSP_LCD_SCLK,
        .mosi = BSP_LCD_MOSI,
        .cs = BSP_LCD_CS,
        .dc = BSP_LCD_DC,
        .rst = BSP_LCD_RST,
        .bl = BSP_LCD_BL,
        .w = 240, .h = 240,
        .invert_color = false,
        .bgr_order = true,
        .spi_host = 2,
        .pclk_hz = 40000000,
        .bl_timer = BSP_LEDC_TIMER_BL,
        .bl_ch = BSP_LEDC_CH_BL,
        .driver = "st7789",
    };
    return bsp_common_lcd_spi_init(&cfg, &s_panel);
}

esp_err_t bsp_display_set_brightness(uint8_t percent)
{
    return bsp_common_lcd_set_brightness(BSP_LEDC_CH_BL, percent);
}

void *bsp_display_panel(void) { return s_panel; }

/* ══════════════ 音频 ══════════════ */

esp_err_t bsp_audio_init(void)
{
    /* 先用 I2C 起 bus（codec 控制需要） */
    esp_err_t e = bsp_i2c_init();
    if (e != ESP_OK) {
        ESP_LOGW(TAG, "I2C 未起，codec 无法配置");
    }

#ifdef CONFIG_BSP_KORVO_CODEC
    /* TODO: 用 esp_codec_dev 初始化 ES8311 + ES7210
     *
     *   esp_codec_dev_cfg_t out_cfg = {
     *       .dev_type = ESP_CODEC_DEV_TYPE_OUT,
     *       .codec_if = get_i2s_codec_if(),
     *       .data_if  = get_i2s_data_if(),
     *   };
     *   out = esp_codec_dev_new(&out_cfg);
     *   esp_codec_dev_set_out_vol(out, 70);
     *
     * 未接这一步会音量很小、麦克风无增益。
     */
    ESP_LOGW(TAG, "CONFIG_BSP_KORVO_CODEC 已开，但 codec 初始化待接入");
#endif

    bsp_i2s_cfg_t cfg = {
        .bclk = BSP_I2S_BCLK,
        .lrck = BSP_I2S_LRCK,
        .dout = BSP_I2S_DOUT,
        .din = BSP_I2S_DIN,
        .sample_rate = BSP_I2S_SAMPLE_RATE,
        .port = 0,
        .mono = false,           /* Korvo-2 codec 走立体声 */
    };
    return bsp_common_i2s_init(&cfg, &s_tx, &s_rx);
}

void *bsp_audio_tx(void) { return s_tx; }
void *bsp_audio_rx(void) { return s_rx; }
uint32_t bsp_audio_sample_rate(void) { return BSP_I2S_SAMPLE_RATE; }

/* ══════════════ I2C ══════════════ */

static void *s_i2c_bus = NULL;

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
        ESP_LOGI(TAG, "I2C 就绪 (codec/扩展IO)");
    }
    return e;
}

void *bsp_i2c_bus(void) { return s_i2c_bus; }