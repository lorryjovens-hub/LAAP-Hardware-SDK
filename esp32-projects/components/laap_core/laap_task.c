/*
 * laap_task.c — 优先级延迟队列
 *
 * 实现：四个独立的 FreeRTOS 队列（每优先级一个），poll 时从高到低查。
 * 简单、无锁竞争、行为可预期。比单个优先队列更省心。
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "laap_task.h"

#define TAG "laap_task"

#define Q_DEPTH_SAFETY      4
#define Q_DEPTH_MOTION      12
#define Q_DEPTH_DIALOGUE    8
#define Q_DEPTH_BACKGROUND  4

typedef struct {
    QueueHandle_t q;
    uint32_t depth;
    uint32_t drop_count;
} prio_queue_t;

static prio_queue_t s_queues[4];
static bool s_inited = false;
static laap_task_fn s_executor = NULL;
static void *s_exec_user = NULL;

laap_err_t laap_task_init(void)
{
    if (s_inited) return LAAP_OK;

    const uint32_t depths[4] = {
        Q_DEPTH_SAFETY, Q_DEPTH_MOTION, Q_DEPTH_DIALOGUE, Q_DEPTH_BACKGROUND
    };
    for (int i = 0; i < 4; i++) {
        s_queues[i].q = xQueueCreate(depths[i], sizeof(laap_msg_t));
        s_queues[i].depth = depths[i];
        s_queues[i].drop_count = 0;
        if (!s_queues[i].q) {
            ESP_LOGE(TAG, "队列 %d 创建失败", i);
            return LAAP_ERR_NO_MEM;
        }
    }
    s_inited = true;
    ESP_LOGI(TAG, "任务队列就绪 (4 优先级)");
    return LAAP_OK;
}

laap_err_t laap_task_post(laap_prio_t prio, const laap_msg_t *msg)
{
    if (!s_inited) return LAAP_ERR_NOT_INIT;
    if (!msg) return LAAP_ERR_INVALID_ARG;
    if (prio > LAAP_PRIO_BACKGROUND) prio = LAAP_PRIO_BACKGROUND;

    /* 队列满：SAFETY/MOTION 必须挤进去（踢掉最旧的），其余丢弃 */
    if (xQueueSend(s_queues[prio].q, msg, 0) == pdTRUE) {
        return LAAP_OK;
    }

    s_queues[prio].drop_count++;

    if (prio <= LAAP_PRIO_MOTION) {
        laap_msg_t discard;
        xQueueReceive(s_queues[prio].q, &discard, 0);   /* 丢最旧 */
        if (xQueueSend(s_queues[prio].q, msg, 0) == pdTRUE) {
            ESP_LOGW(TAG, "队列 %d 满，挤掉最旧任务", prio);
            return LAAP_OK;
        }
    }
    ESP_LOGW(TAG, "队列 %d 满，任务丢弃 (累计 %u)",
             prio, (unsigned)s_queues[prio].drop_count);
    return LAAP_ERR_QUEUE_FULL;
}

bool laap_task_poll(laap_msg_t *out, uint32_t timeout_ms)
{
    if (!s_inited || !out) return false;

    /* 先看高优先级的（不等待） */
    for (int p = 0; p <= LAAP_PRIO_DIALOGUE; p++) {
        if (xQueueReceive(s_queues[p].q, out, 0) == pdTRUE) return true;
    }

    /* 都没有，则按 timeout 等背景队列（等价于等任意队列） */
    TickType_t ticks = timeout_ms ? pdMS_TO_TICKS(timeout_ms) : 0;
    if (ticks == 0) {
        return xQueueReceive(s_queues[LAAP_PRIO_BACKGROUND].q, out, 0) == pdTRUE;
    }

    /* 有等待时：轮询所有队列（每 5ms 一轮，简单可靠） */
    TickType_t elapsed = 0;
    const TickType_t step = pdMS_TO_TICKS(5);
    while (elapsed <= ticks) {
        for (int p = 0; p < 4; p++) {
            if (xQueueReceive(s_queues[p].q, out, 0) == pdTRUE) return true;
        }
        vTaskDelay(step);
        elapsed += step;
    }
    return false;
}

size_t laap_task_pending(void)
{
    if (!s_inited) return 0;
    size_t total = 0;
    for (int i = 0; i < 4; i++) total += uxQueueMessagesWaiting(s_queues[i].q);
    return total;
}

void laap_task_flush(void)
{
    if (!s_inited) return;
    laap_msg_t tmp;
    for (int i = 0; i < 4; i++) {
        while (xQueueReceive(s_queues[i].q, &tmp, 0) == pdTRUE) { }
    }
}

void laap_task_set_executor(laap_task_fn fn, void *user)
{
    s_executor = fn;
    s_exec_user = user;
}