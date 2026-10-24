/*
 * motion.h — 双舵机云台
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

void motion_init(void);

/** 看向指定角度（度），pan 左右 tilt 上下 */
void motion_look_at(float pan, float tilt);

/** 相对当前目标微调 */
void motion_look_delta(float d_pan, float d_tilt);

/** 命名姿态：home/look_up/look_down/think/nod/sleep */
void motion_pose(const char *name);

/** 是否处于睡眠姿态 */
bool motion_is_sleeping(void);

/** 周期调用（建议 40Hz / 25ms） */
void motion_tick(uint32_t dt_ms);

void motion_get_angles(float *pan, float *tilt);

#ifdef __cplusplus
}
#endif