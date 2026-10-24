/*
 * display.h — GC9A01 圆屏眼睛表情
 */
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** 表情状态 */
typedef enum {
    EXPR_IDLE = 0,      /* 呼吸 + 随机眨眼 + 瞳孔游移 */
    EXPR_LISTENING,     /* 瞳孔放大、看向声源 */
    EXPR_THINKING,      /* 瞳孔左右缓移 */
    EXPR_SPEAKING,      /* 底部波形随音量 */
    EXPR_HAPPY,         /* 弯成 ^ ^ */
    EXPR_SLEEP,         /* 闭眼、呼吸变慢 */
} expression_t;

void display_init(void);

/** 周期调用（建议 30-50Hz），驱动呼吸/眨眼/波形动画 */
void display_update(uint32_t dt_ms);

void display_set_expression(expression_t e);
expression_t display_get_expression(void);

/** 瞳孔注视方向，-1..1 归一化 */
void display_set_gaze(float nx, float ny);

/** 说话音量 0-100（驱动波形） */
void display_set_volume(uint8_t vol);

void display_set_status(const char *text);
void display_set_subtitle(const char *text);
void display_set_brightness(uint8_t percent);

#ifdef __cplusplus
}
#endif