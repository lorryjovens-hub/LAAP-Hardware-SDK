/*
 * laap_types.h — LAAP 硬件核心公共类型
 *
 * This file is part of LAAP Hardware SDK, GPL v3.
 */
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ══════════════ 错误码 ══════════════ */
typedef enum {
    LAAP_OK              = 0,
    LAAP_ERR_INVALID_ARG = 0x1001,
    LAAP_ERR_NO_MEM      = 0x1002,
    LAAP_ERR_NOT_INIT    = 0x1003,
    LAAP_ERR_QUEUE_FULL  = 0x1004,
    LAAP_ERR_TRANSPORT   = 0x1005,
    LAAP_ERR_PARSE       = 0x1006,
    LAAP_ERR_TIMEOUT     = 0x1007,
} laap_err_t;

/* ══════════════ 能力位（设备声明自己会什么）══════════════ */
#define LAAP_CAP_MOTION     (1u << 0)   /* 能移动 */
#define LAAP_CAP_DISPLAY    (1u << 1)   /* 有屏幕 */
#define LAAP_CAP_SPEAK      (1u << 2)   /* 能出声 */
#define LAAP_CAP_HEAR       (1u << 3)   /* 有麦克风 */
#define LAAP_CAP_SEE        (1u << 4)   /* 有摄像头 */
#define LAAP_CAP_TOUCH      (1u << 5)   /* 触摸感知 */
#define LAAP_CAP_IMU        (1u << 6)   /* 姿态感知 */
#define LAAP_CAP_LIGHT      (1u << 7)   /* 光感 */
#define LAAP_CAP_TEMP       (1u << 8)   /* 温度 */
#define LAAP_CAP_PRESSURE   (1u << 9)   /* 压力 */
#define LAAP_CAP_DISTANCE   (1u << 10)  /* 测距 */
#define LAAP_CAP_BATTERY    (1u << 11)  /* 电量 */

/* ══════════════ 运动方式 ══════════════ */
typedef enum {
    LAAP_MOTION_NONE = 0,
    LAAP_MOTION_PANTILT,    /* 云台（宠物） */
    LAAP_MOTION_DIFF,       /* 差速底盘（车） */
    LAAP_MOTION_LEGS,       /* 多足（狗） */
    LAAP_MOTION_BLINK,      /* 只有表情（纯屏角色） */
} laap_motion_kind_t;

/* ══════════════ LDP 消息类型 ══════════════ */
typedef enum {
    LAAP_MSG_UNKNOWN = 0,
    /* 下行（LAAP → 设备） */
    LAAP_MSG_HELLO_ACK,
    LAAP_MSG_MOTION_MOVE,
    LAAP_MSG_MOTION_POSE,
    LAAP_MSG_MOTION_STOP,
    LAAP_MSG_DIALOGUE_TEXT,
    LAAP_MSG_DIALOGUE_STATE,
    LAAP_MSG_CONFIG,
    /* 上行（设备 → LAAP） */
    LAAP_MSG_HELLO,
    LAAP_MSG_HEARTBEAT,
    LAAP_MSG_PERCEPT,
    LAAP_MSG_STATE_REPORT,
} laap_msg_kind_t;

/* ══════════════ 消息结构（已解析，交给应用层）══════════════ */
typedef struct {
    laap_msg_kind_t kind;
    char kind_str[32];          /* 原始 kind 字符串，未知类型也能看 */

    /* motion.move */
    float vx, vy, omega;

    /* motion.pose */
    char pose[24];

    /* dialogue.text / state */
    char text[512];
    char state[24];

    /* percept */
    char sensor[24];
    char data_json[256];        /* 感知数据原始 JSON（小体量） */

    /* 时间戳（ms） */
    int64_t ts_ms;
} laap_msg_t;

/* ══════════════ 连接状态 ══════════════ */
typedef enum {
    LAAP_STATE_DISCONNECTED = 0,
    LAAP_STATE_CONNECTING,
    LAAP_STATE_CONNECTED,
    LAAP_STATE_RECONNECTING,
} laap_state_t;

/* ══════════════ 回调 ══════════════ */
/** 收到 LDP 消息（在主任务上下文，安全调用外设） */
typedef void (*laap_msg_cb_t)(const laap_msg_t *msg, void *user);

/** 连接状态变化 */
typedef void (*laap_state_cb_t)(laap_state_t state, void *user);

/* ══════════════ 下发动作优先级 ══════════════ */
typedef enum {
    LAAP_PRIO_SAFETY   = 0,   /* 急停：最高，立即执行 */
    LAAP_PRIO_MOTION   = 1,
    LAAP_PRIO_DIALOGUE = 2,
    LAAP_PRIO_BACKGROUND = 3,
} laap_prio_t;

#ifdef __cplusplus
}
#endif