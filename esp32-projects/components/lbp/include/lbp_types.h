/*
 * lbp_types.h — LBP/1.0 公共类型
 *
 * 与 Python 参考实现 (laaper/body/) 逐字节对齐。
 *
 * This file is part of LAAP Hardware SDK, GPL v3.
 */
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ══════════════ 帧格式常量 ══════════════ */

#define LBP_SOF             0x4C        /* 'L' */
#define LBP_EOF             0xAA
#define LBP_VER_MAJOR       1
#define LBP_VER_MINOR       0
#define LBP_VER_BYTE        ((LBP_VER_MAJOR << 4) | LBP_VER_MINOR)

#define LBP_HDR_SIZE        18
#define LBP_TRAILER_SIZE    5           /* CRC32(4) + EOF(1) */
#define LBP_MIN_FRAME       (LBP_HDR_SIZE + LBP_TRAILER_SIZE)

#define LBP_MAX_PAYLOAD     1024
#define LBP_MAX_FRAME       (LBP_HDR_SIZE + LBP_MAX_PAYLOAD + LBP_TRAILER_SIZE)

#define LBP_ADDR_UNASSIGNED 0x00
#define LBP_ADDR_BROADCAST  0xFF
#define LBP_ADDR_MASTER     0x01

/* ══════════════ 错误码 ══════════════ */

typedef enum {
    LBP_OK              = 0,
    LBP_ERR_INVALID_ARG = 0x2001,
    LBP_ERR_NO_MEM      = 0x2002,
    LBP_ERR_NOT_INIT    = 0x2003,
    LBP_ERR_PARSE       = 0x2004,
    LBP_ERR_CRC         = 0x2005,
    LBP_ERR_FRAME       = 0x2006,   /* SOF/EOF/长度错 */
    LBP_ERR_TOO_BIG     = 0x2007,
    LBP_ERR_TIMEOUT     = 0x2008,
    LBP_ERR_BUS         = 0x2009,   /* TWAI 发送/接收失败 */
    LBP_ERR_QUEUE_FULL  = 0x200A,
} lbp_err_t;

/* ══════════════ 消息类型 ══════════════ */

typedef enum {
    LBP_MSG_UNKNOWN       = 0x00,
    LBP_MSG_ENUM_REQ      = 0x01,
    LBP_MSG_ENUM_ACK      = 0x02,
    LBP_MSG_CAPS          = 0x03,
    LBP_MSG_CMD           = 0x04,
    LBP_MSG_TELEM         = 0x05,
    LBP_MSG_CLOCK_SYNC    = 0x06,
    LBP_MSG_TOPO_REQ      = 0x07,
    LBP_MSG_TOPO_ACK      = 0x08,
    LBP_MSG_BODY_SCHEMA   = 0x09,
    LBP_MSG_REFLEX        = 0x0A,
    LBP_MSG_SAFE_STOP     = 0x0B,
    LBP_MSG_FRAG          = 0x0C,
    LBP_MSG_HEARTBEAT     = 0x0D,
    LBP_MSG_OTA           = 0x0E,
} lbp_msg_type_t;

/* ══════════════ 优先级 ══════════════ */

typedef enum {
    LBP_PRIO_SAFETY  = 0,
    LBP_PRIO_CONTROL = 1,
    LBP_PRIO_CONFIG  = 2,
    LBP_PRIO_BULK    = 3,
} lbp_prio_t;

/* ══════════════ flags 位 ══════════════ */

#define LBP_FLAG_FRAGMENT   (1u << 7)
#define LBP_FLAG_ACK_REQ    (1u << 4)
#define LBP_FLAG_MASK       0x90    /* 只这两位是 flags，别用 0xF0 */

/* ══════════════ 关节 / 端口 / 模块 ══════════════ */

#define LBP_MAX_JOINTS      16
#define LBP_MAX_PORTS       8
#define LBP_NAME_LEN        32

/* 模块大类 */
typedef enum {
    LBP_CLS_ACTUATOR  = 0x01,
    LBP_CLS_SENSOR    = 0x02,
    LBP_CLS_COMPUTE   = 0x03,
    LBP_CLS_POWER     = 0x04,
    LBP_CLS_STRUCTURE = 0x05,
    LBP_CLS_WHEEL     = 0x06,
} lbp_module_class_t;

/* 模块角色 */
typedef enum {
    LBP_ROLE_SPINE        = 0x01,
    LBP_ROLE_LIMB         = 0x02,
    LBP_ROLE_JOINT        = 0x03,
    LBP_ROLE_END_EFFECTOR = 0x04,
    LBP_ROLE_EYE          = 0x05,
    LBP_ROLE_EAR          = 0x06,
    LBP_ROLE_SKIN         = 0x07,
    LBP_ROLE_BRAIN        = 0x08,
    LBP_ROLE_WHEEL        = 0x09,
    LBP_ROLE_VOICE        = 0x0A,
} lbp_module_role_t;

/* 能力位 */
#define LBP_CAP_LOCOMOTION    (1u << 0)
#define LBP_CAP_MANIPULATION  (1u << 1)
#define LBP_CAP_VISION        (1u << 2)
#define LBP_CAP_AUDITION      (1u << 3)
#define LBP_CAP_SPEECH        (1u << 4)
#define LBP_CAP_TACTILE       (1u << 5)
#define LBP_CAP_BALANCE       (1u << 6)
#define LBP_CAP_CLIMB         (1u << 7)
#define LBP_CAP_ROLL          (1u << 8)

/* 一个旋转关节 */
typedef struct {
    char    name[16];
    float   axis[3];            /* 单位旋转轴（关节局部系） */
    float   min_rad;
    float   max_rad;
    float   max_vel_rad_s;
    float   max_torque_nm;
    float   offset[3];          /* 上一连杆末端 → 关节中心 */
    float   link[3];            /* 关节中心 → 下一连杆末端 */
} lbp_joint_t;

/* 一个机械对接端口 */
typedef struct {
    uint8_t pos_id;             /* 0-7，3 根 ID 线编码 */
    float   normal[3];          /* 朝外方向 */
    float   offset[3];          /* 端口位置（模块局部系） */
} lbp_port_t;

/* BMD — 模块自描述 */
typedef struct {
    uint8_t  ver_major, ver_minor;
    uint8_t  cls;               /* lbp_module_class_t */
    uint8_t  role;              /* lbp_module_role_t */
    uint16_t vendor_id;
    uint16_t product_id;
    uint64_t serial;            /* 唯一序列号（身份锚定） */

    uint8_t  dof;
    lbp_joint_t joints[LBP_MAX_JOINTS];

    uint8_t  port_count;
    lbp_port_t ports[LBP_MAX_PORTS];

    float    mass_kg;
    float    com_offset[3];
    float    payload_kg;
    float    reach_m;

    uint8_t  bus_profile;       /* 1=CAN 2=ETH 3=SPI */
    uint8_t  bus_addr;          /* 枚举时分配 */
    uint16_t power_mw;
    uint16_t power_peak_mw;

    uint32_t caps;              /* LBP_CAP_* 位掩码 */
    bool     hw_timestamp;

    char     name[LBP_NAME_LEN];
} lbp_bmd_t;

/* ══════════════ 反射码 ══════════════ */

#define LBP_REFLEX_OVER_CURRENT   0x01
#define LBP_REFLEX_STALL          0x02
#define LBP_REFLEX_OVER_TEMP      0x03
#define LBP_REFLEX_COLLISION      0x04
#define LBP_REFLEX_LOST_SYNC      0x05
#define LBP_REFLEX_POSITION_ERROR 0x06

#ifdef __cplusplus
}
#endif