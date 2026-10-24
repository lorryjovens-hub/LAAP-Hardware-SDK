/*
 * board.c — ESP32-S3-EYE（乐鑫官方视觉板）
 *
 * 能力：显示 + 摄像头 + 麦克风 + 按键
 * 没有：舵机、电机、扬声器
 *
 * ## 摄像头需要额外组件
 *
 *     idf.py add-dependency "espressif/esp32-camera"
 *
 * 摄像头初始化代码较长（DVP 引脚 + 传感器配置），
 * 这里给出配置结构，实际初始化在 CONFIG_BSP_CAMERA 打开时接入。
 */
#include "esp_log.h"
#include "bsp.h"
#include "bsp_board.h"
#include "bsp_common.h"
#include "board_pins.h"

static const char *TAG = "bsp.s3eye";

static void *s_panel = NULL;
static void *s_rx = NULL;

static const bsp_info_t s_info = {
    .name = "ESP32-S3-EYE 视觉板",
    .id = "s3_eye",
    .chip = "esp32s3",
    .caps = BSP_CAP_DISPLAY | BSP_CAP_CAMERA | BSP_CAP_AUDIO_IN
          | BSP_CAP_BUTTON,
    .display_w = 240,
    .display_h = 240,
    .display_driver = "st7789",
    .servo_count = 0,
    .note = "无扬声器；摄像头需 esp32-camera 组件",
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

/* ══════════════ 音频（只有麦克风）══════════════ */

esp_err_t bsp_audio_init(void)
{
    bsp_i2s_cfg_t cfg = {
        .bclk = BSP_I2S_BCLK,
        .lrck = BSP_I2S_LRCK,
        .dout = -1,                  /* 无扬声器 */
        .din = BSP_I2S_DIN,
        .sample_rate = BSP_I2S_SAMPLE_RATE,
        .port = 0,
        .mono = true,
    };
    return bsp_common_i2s_init(&cfg, NULL, &s_rx);
}

void *bsp_audio_tx(void) { return NULL; }
void *bsp_audio_rx(void) { return s_rx; }
uint32_t bsp_audio_sample_rate(void) { return BSP_I2S_SAMPLE_RATE; }

/* ══════════════ 摄像头 ══════════════ */

esp_err_t bsp_board_init(void)
{
#ifdef CONFIG_BSP_CAMERA
    /* esp32-camera 配置（需先 idf.py add-dependency espressif/esp32-camera）
     *
     * camera_config_t cfg = {
     *     .pin_pwdn = BSP_CAM_PWDN, .pin_reset = BSP_CAM_RESET,
     *     .pin_xclk = BSP_CAM_XCLK,
     *     .pin_sccb_sda = BSP_CAM_SDA, .pin_sccb_scl = BSP_CAM_SCL,
     *     .pin_d7 = BSP_CAM_D7, .pin_d6 = BSP_CAM_D6,
     *     .pin_d5 = BSP_CAM_D5, .pin_d4 = BSP_CAM_D4,
     *     .pin_d3 = BSP_CAM_D3, .pin_d2 = BSP_CAM_D2,
     *     .pin_d1 = BSP_CAM_D1, .pin_d0 = BSP_CAM_D0,
     *     .pin_vsync = BSP_CAM_VSYNC, .pin_href = BSP_CAM_HREF,
     *     .pin_pclk = BSP_CAM_PCLK,
     *     .xclk_freq_hz = 20000000,
     *     .pixel_format = PIXFORMAT_JPEG,
     *     .frame_size = FRAMESIZE_QVGA,   // 320x240，够视觉模型用
     *     .jpeg_quality = 12,
     *     .fb_count = 2,
     *     .fb_location = CAMERA_FB_IN_PSRAM,
     *     .grab_mode = CAMERA_GRAB_LATEST,
     * };
     * if (esp_camera_init(&cfg) != ESP_OK) { ... }
     */
    ESP_LOGW(TAG, "CONFIG_BSP_CAMERA 已开，摄像头初始化待接入");
#endif
    return ESP_OK;
}