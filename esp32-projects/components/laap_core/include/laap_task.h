/*
 * laap_task.h — 延迟动作队列（优先级）
 *
 * ## 为什么需要这个
 *
 * 在 WebSocket 回调里直接驱动舵机/屏幕是错的：
 *   · WS 回调在独立任务，和主控制循环并发写外设 → 竞态
 *   · 回调里做慢操作会阻塞网络接收 → 丢包
 *
 * 所以：WS 回调只把动作压进队，主控制循环按优先级取出执行。
 *
 * 优先级的意义：
 *   急停（SAFETY）必须插队到最前面，
 *   背景任务（BACKGROUND）可以丢。
 */
#pragma once

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>
#include "laap_types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct laap_task laap_task_t;

/** 任务执行回调（在主任务上下文调用，可安全操作外设） */
typedef void (*laap_task_fn)(const laap_msg_t *msg, void *user);

laap_err_t laap_task_init(void);

/**
 * 投递任务。
 * @return LAAP_ERR_QUEUE_FULL 表示队列满（BACKGROUND 任务会被丢弃）
 */
laap_err_t laap_task_post(laap_prio_t prio, const laap_msg_t *msg);

/**
 * 取出一个待执行任务（按优先级）。
 * @param timeout_ms 0 = 不等待
 * @return true 表示取到
 */
bool laap_task_poll(laap_msg_t *out, uint32_t timeout_ms);

/** 当前队列深度 */
size_t laap_task_pending(void);

/** 清空（急停时用） */
void laap_task_flush(void);

/** 注册执行器（框架内部用） */
void laap_task_set_executor(laap_task_fn fn, void *user);

#ifdef __cplusplus
}
#endif