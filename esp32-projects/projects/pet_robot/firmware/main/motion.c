/*
 * motion.c — 双舵机云台（pan/tilt）+ 一阶低通平滑
 *
 * 生命感的关键不在动作幅度，在「不生硬」：
 *   所有目标角度都经过一阶低通，绝不瞬间跳变。
 *
 * 舵机：SG90 / MG90S，50Hz PWM，脉宽 500-2500us 对应 0-180°
 */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include <math.h>

#include "motion.h"

#define TAG "motion"

#define PIN_SERVO_PAN   GPIO_NUM_4
#define PIN_SERVO_TILT  GPIO_NUM_5

#define SERVO_LEDC_TIMER    LEDC_TIMER_1
#define SERVO_LEDC_MODE     LEDC_LOW_SPEED_MODE
#define SERVO_CH_PAN        LEDC_CHANNEL_2
#define SERVO_CH_TILT       LEDC_CHANNEL_3

/* 舵机脉宽参数（按你的舵机实测微调） */
#define SERVO_MIN_US    500
#define SERVO_MAX_US    2500
#define SERVO_FREQ_HZ   50
#define SERVO_PERIOD_US (1000000 / SERVO_FREQ_HZ)   /* 20000us */
#define SERVO_RES_BITS  LEDC_TIMER_14_BIT            /* 16384 级，够精细 */

/* 角度限位与标定（真机标定后改这里） */
#define PAN_MIN    -75.0f
#define PAN_MAX     75.0f
#define TILT_MIN   -25.0f
#define TILT_MAX    55.0f
#define PAN_OFFSET   0.0f
#define TILT_OFFSET  0.0f

/* 一阶低通系数：越小越柔（0.18 = 动作柔和不迟钝） */
#define SMOOTH_ALPHA  0.18f

static float s_pan_cur = 0.0f, s_tilt_cur = 0.0f;
static float s_pan_tgt = 0.0f, s_tilt_tgt = 0.0f;
static bool s_sleeping = false;

static inline uint32_t angle_to_duty(float deg)
{
    if (deg < 0) deg = 0;
    if (deg > 180) deg = 180;
    uint32_t us = SERVO_MIN_US +
        (uint32_t)((deg / 180.0f) * (SERVO_MAX_US - SERVO_MIN_US));
    /* duty = us / period * (2^res - 1) */
    return (uint32_t)((float)us / SERVO_PERIOD_US * ((1 << SERVO_RES_BITS) - 1));
}

static void servo_init_channel(ledc_channel_t ch, gpio_num_t pin)
{
    ledc_channel_config_t c = {
        .gpio_num = pin,
        .speed_mode = SERVO_LEDC_MODE,
        .channel = ch,
        .timer_sel = SERVO_LEDC_TIMER,
        .duty = angle_to_duty(90.0f),
        .hpoint = 0,
    };
    ledc_channel_config(&c);
}

void motion_init(void)
{
    ledc_timer_config_t t = {
        .speed_mode = SERVO_LEDC_MODE,
        .duty_resolution = SERVO_RES_BITS,
        .timer_num = SERVO_LEDC_TIMER,
        .freq_hz = SERVO_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&t);

    servo_init_channel(SERVO_CH_PAN, PIN_SERVO_PAN);
    servo_init_channel(SERVO_CH_TILT, PIN_SERVO_TILT);

    /* 上电先回中位 */
    s_pan_cur = s_pan_tgt = 0.0f;
    s_tilt_cur = s_tilt_tgt = 0.0f;
    motion_tick(16);

    ESP_LOGI(TAG, "云台就绪 pan=%d tilt=%d", PIN_SERVO_PAN, PIN_SERVO_TILT);
}

void motion_look_at(float pan, float tilt)
{
    if (pan < PAN_MIN) pan = PAN_MIN;
    if (pan > PAN_MAX) pan = PAN_MAX;
    if (tilt < TILT_MIN) tilt = TILT_MIN;
    if (tilt > TILT_MAX) tilt = TILT_MAX;
    s_pan_tgt = pan;
    s_tilt_tgt = tilt;
    s_sleeping = false;
}

void motion_look_delta(float d_pan, float d_tilt)
{
    motion_look_at(s_pan_tgt + d_pan, s_tilt_tgt + d_tilt);
}

void motion_pose(const char *name)
{
    if (!name) return;
    if (strcmp(name, "home") == 0)        motion_look_at(0, 0);
    else if (strcmp(name, "look_up") == 0)  motion_look_at(0, 25);
    else if (strcmp(name, "look_down") == 0) motion_look_at(0, -22);
    else if (strcmp(name, "think") == 0)    motion_look_at(18, 12);
    else if (strcmp(name, "nod") == 0)      motion_look_at(0, -8);
    else if (strcmp(name, "sleep") == 0) {
        motion_look_at(0, -25);
        s_sleeping = true;
    } else {
        ESP_LOGW(TAG, "未知姿态 %s", name);
    }
}

bool motion_is_sleeping(void)
{
    return s_sleeping;
}

/* 周期调用：40Hz 比较顺（25ms） */
void motion_tick(uint32_t dt_ms)
{
    (void)dt_ms;
    /* 一阶低通：目标 → 当前平滑逼近 */
    s_pan_cur  += (s_pan_tgt  - s_pan_cur)  * SMOOTH_ALPHA;
    s_tilt_cur += (s_tilt_tgt - s_tilt_cur) * SMOOTH_ALPHA;

    /* 舵机角度 = 90 + 偏移（90 是中位） */
    float pan_deg  = 90.0f + s_pan_cur + PAN_OFFSET;
    float tilt_deg = 90.0f - s_tilt_cur + TILT_OFFSET;   /* tilt 反向 */

    ledc_set_duty(SERVO_LEDC_MODE, SERVO_CH_PAN, angle_to_duty(pan_deg));
    ledc_update_duty(SERVO_LEDC_MODE, SERVO_CH_PAN);
    ledc_set_duty(SERVO_LEDC_MODE, SERVO_CH_TILT, angle_to_duty(tilt_deg));
    ledc_update_duty(SERVO_LEDC_MODE, SERVO_CH_TILT);
}

void motion_get_angles(float *pan, float *tilt)
{
    if (pan) *pan = s_pan_cur;
    if (tilt) *tilt = s_tilt_cur;
}