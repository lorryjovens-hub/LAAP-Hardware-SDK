/*
 * motion.c — 云台平滑（BSP 版）
 *
 * ## 改版前后
 *
 * 改版前：文件里硬编码 2 个舵机 GPIO、LEDC timer/channel、
 *        脉宽标定、角度→占空比换算。换板子要改这里。
 *
 * 改版后：只用 bsp_servo_set_angle(ch, deg) 和 bsp_servo_calibrate()。
 *        **引脚、PWM 通道、脉宽全部由 BSP 负责。**
 *
 * 这里剩下的唯一职责：**让动作不生硬**。
 * 一阶低通 + 限位 + 命名姿态，这是"生命感"的来源。
 */
#include <string.h>
#include <math.h>
#include "esp_log.h"
#include "bsp.h"

#include "motion.h"

#define TAG "motion"

/* ── 角度限位（按你的云台机械结构改）── */
#define PAN_MIN    -75.0f
#define PAN_MAX     75.0f
#define TILT_MIN   -25.0f
#define TILT_MAX    55.0f

/* 一阶低通系数：越小越柔（0.18 = 动作柔和不迟钝） */
#define SMOOTH_ALPHA  0.18f

/* 舵机通道语义（对应 BSP 的 ch0/ch1） */
#define CH_PAN   0
#define CH_TILT  1

static float s_pan_cur = 0.0f, s_tilt_cur = 0.0f;
static float s_pan_tgt = 0.0f, s_tilt_tgt = 0.0f;
static bool s_sleeping = false;

void motion_init(void)
{
    if (!bsp_has_cap(BSP_CAP_SERVO)) {
        ESP_LOGW(TAG, "此板无舵机，云台不可用");
        return;
    }

    if (bsp_servo_count() < 2) {
        ESP_LOGW(TAG, "舵机通道不足 2 个（当前 %u），只做单轴", bsp_servo_count());
    }

    /* 上电回中 */
    s_pan_cur = s_pan_tgt = 0.0f;
    s_tilt_cur = s_tilt_tgt = 0.0f;
    motion_tick(16);

    ESP_LOGI(TAG, "云台就绪 %u ch", bsp_servo_count());
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
    if (strcmp(name, "home") == 0)         motion_look_at(0, 0);
    else if (strcmp(name, "look_up") == 0) motion_look_at(0, 25);
    else if (strcmp(name, "look_down") == 0) motion_look_at(0, -22);
    else if (strcmp(name, "think") == 0)   motion_look_at(18, 12);
    else if (strcmp(name, "nod") == 0)     motion_look_at(0, -8);
    else if (strcmp(name, "sleep") == 0) {
        motion_look_at(0, -25);
        s_sleeping = true;
    } else {
        ESP_LOGW(TAG, "未知姿态 %s", name);
    }
}

bool motion_is_sleeping(void) { return s_sleeping; }

void motion_tick(uint32_t dt_ms)
{
    (void)dt_ms;
    if (!bsp_has_cap(BSP_CAP_SERVO)) return;

    /* 一阶低通：目标 → 当前平滑逼近（这是手感的来源） */
    s_pan_cur  += (s_pan_tgt  - s_pan_cur)  * SMOOTH_ALPHA;
    s_tilt_cur += (s_tilt_tgt - s_tilt_cur) * SMOOTH_ALPHA;

    /* 舵机中位 90°，pan 正向偏右，tilt 反向（机械安装决定） */
    bsp_servo_set_angle(CH_PAN,  90.0f + s_pan_cur);
    bsp_servo_set_angle(CH_TILT, 90.0f - s_tilt_cur);
}

void motion_get_angles(float *pan, float *tilt)
{
    if (pan) *pan = s_pan_cur;
    if (tilt) *tilt = s_tilt_cur;
}