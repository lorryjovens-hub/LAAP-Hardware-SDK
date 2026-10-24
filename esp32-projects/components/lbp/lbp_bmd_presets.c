/*
 * lbp_bmd_presets.c — 标准模块 BMD 预设
 *
 * 数值与 laaper/body/module.py 的 make_leg_3dof / make_arm_4dof 完全一致。
 * 改一边必须改另一边 —— 有 tests/test_bmd_parity.py 做校验。
 */
#include <math.h>
#include <string.h>
#include "lbp.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static inline float deg(float d)
{
    return d * (float)M_PI / 180.0f;
}

/* ══════════════════════════════════════════════════════════
 *  3-DOF 腿
 *
 *  物理：3× 微型无刷 + 行星减速，连杆 90mm + 100mm
 *  局部系 +Z 朝外（挂载底面时 = 世界向下），零位足端在 (0,0,0.21)
 * ══════════════════════════════════════════════════════════ */

void lbp_fill_leg_3dof_bmd(lbp_bmd_t *bmd, uint64_t serial)
{
    if (!bmd) return;
    memset(bmd, 0, sizeof(*bmd));

    bmd->ver_major = 1;
    bmd->ver_minor = 0;
    bmd->cls       = LBP_CLS_ACTUATOR;
    bmd->role      = LBP_ROLE_LIMB;
    bmd->vendor_id = 0x1AAB;         /* LAAP */
    bmd->product_id = 0x0010;
    bmd->serial    = serial;

    bmd->dof = 3;

    /* 关节 0：髋外展，绕局部 X（世界前向） */
    strncpy(bmd->joints[0].name, "hip_abduct", 15);
    bmd->joints[0].axis[0] = 1.0f;
    bmd->joints[0].axis[1] = 0.0f;
    bmd->joints[0].axis[2] = 0.0f;
    bmd->joints[0].min_rad       = deg(-30.0f);
    bmd->joints[0].max_rad       = deg(30.0f);
    bmd->joints[0].max_vel_rad_s = 6.0f;
    bmd->joints[0].max_torque_nm = 8.0f;
    bmd->joints[0].offset[2]     = 0.02f;
    bmd->joints[0].link[2]       = 0.02f;

    /* 关节 1：髋屈伸，绕局部 Y */
    strncpy(bmd->joints[1].name, "hip_pitch", 15);
    bmd->joints[1].axis[1] = 1.0f;
    bmd->joints[1].min_rad       = deg(-45.0f);
    bmd->joints[1].max_rad       = deg(90.0f);
    bmd->joints[1].max_vel_rad_s = 12.0f;
    bmd->joints[1].max_torque_nm = 12.0f;
    bmd->joints[1].link[2]       = 0.09f;

    /* 关节 2：膝，与髋同轴向 */
    strncpy(bmd->joints[2].name, "knee", 15);
    bmd->joints[2].axis[1] = 1.0f;
    bmd->joints[2].min_rad       = deg(-150.0f);
    bmd->joints[2].max_rad       = deg(0.0f);
    bmd->joints[2].max_vel_rad_s = 14.0f;
    bmd->joints[2].max_torque_nm = 9.0f;
    bmd->joints[2].link[2]       = 0.10f;

    bmd->port_count = 1;
    bmd->ports[0].pos_id     = 0;
    bmd->ports[0].normal[2]  = 1.0f;
    bmd->ports[0].offset[2]  = 0.21f;

    bmd->mass_kg        = 0.28f;
    bmd->com_offset[2]  = 0.09f;
    bmd->payload_kg     = 0.0f;
    bmd->reach_m        = 0.19f;
    bmd->power_mw       = 900;
    bmd->power_peak_mw  = 9000;      /* 落地冲击可达 10× */
    bmd->bus_profile    = 1;         /* CAN */
    bmd->caps           = 0;         /* 腿本身不声明能力，由拓扑推导 */
    bmd->hw_timestamp   = true;
    strncpy(bmd->name, "leg_3dof", LBP_NAME_LEN - 1);
}

/* ══════════════════════════════════════════════════════════
 *  4-DOF 臂
 *
 *  局部系 +Z 朝外（挂载侧面时 = 世界向左/右），零位末端在 (0,0,0.27)
 * ══════════════════════════════════════════════════════════ */

void lbp_fill_arm_4dof_bmd(lbp_bmd_t *bmd, uint64_t serial)
{
    if (!bmd) return;
    memset(bmd, 0, sizeof(*bmd));

    bmd->ver_major = 1;
    bmd->ver_minor = 0;
    bmd->cls       = LBP_CLS_ACTUATOR;
    bmd->role      = LBP_ROLE_LIMB;
    bmd->vendor_id = 0x1AAB;
    bmd->product_id = 0x0020;
    bmd->serial    = serial;

    bmd->dof = 4;

    strncpy(bmd->joints[0].name, "shoulder_yaw", 15);
    bmd->joints[0].axis[2] = 1.0f;
    bmd->joints[0].min_rad       = deg(-90.0f);
    bmd->joints[0].max_rad       = deg(90.0f);
    bmd->joints[0].max_vel_rad_s = 6.0f;
    bmd->joints[0].max_torque_nm = 6.0f;
    bmd->joints[0].offset[2]     = 0.03f;
    bmd->joints[0].link[2]       = 0.02f;

    strncpy(bmd->joints[1].name, "shoulder_pitch", 15);
    bmd->joints[1].axis[0] = 1.0f;
    bmd->joints[1].min_rad       = deg(-90.0f);
    bmd->joints[1].max_rad       = deg(90.0f);
    bmd->joints[1].max_vel_rad_s = 8.0f;
    bmd->joints[1].max_torque_nm = 8.0f;
    bmd->joints[1].link[2]       = 0.10f;

    strncpy(bmd->joints[2].name, "elbow", 15);
    bmd->joints[2].axis[0] = 1.0f;
    bmd->joints[2].min_rad       = deg(-140.0f);
    bmd->joints[2].max_rad       = deg(0.0f);
    bmd->joints[2].max_vel_rad_s = 10.0f;
    bmd->joints[2].max_torque_nm = 5.0f;
    bmd->joints[2].link[2]       = 0.09f;

    strncpy(bmd->joints[3].name, "wrist_roll", 15);
    bmd->joints[3].axis[2] = 1.0f;
    bmd->joints[3].min_rad       = deg(-180.0f);
    bmd->joints[3].max_rad       = deg(180.0f);
    bmd->joints[3].max_vel_rad_s = 15.0f;
    bmd->joints[3].max_torque_nm = 1.5f;
    bmd->joints[3].link[2]       = 0.03f;

    bmd->port_count = 1;
    bmd->ports[0].pos_id    = 0;
    bmd->ports[0].normal[2] = 1.0f;
    bmd->ports[0].offset[2] = 0.27f;

    bmd->mass_kg        = 0.42f;
    bmd->com_offset[2]  = 0.13f;
    bmd->payload_kg     = 1.2f;
    bmd->reach_m        = 0.27f;
    bmd->power_mw       = 1100;
    bmd->power_peak_mw  = 6000;
    bmd->bus_profile    = 1;
    bmd->caps           = LBP_CAP_MANIPULATION;
    bmd->hw_timestamp   = true;
    strncpy(bmd->name, "arm_4dof", LBP_NAME_LEN - 1);
}