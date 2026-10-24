/*
 * lbp_payload.h — L2 载荷编解码（小端二进制）
 *
 * 与 laaper/body/payload.py 一致。所有多字节字段均小端。
 *
 * ## 为什么不是 JSON
 *
 * TOPO_ACK 用 JSON 整帧 67B > CAN 上限，发不出去；二进制 3B。
 * BMD 用 JSON 663B；二进制 318B（省 52%，少 10 个分片）。
 */
#pragma once

#include "lbp_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ══════════════ 通用小端读写 ══════════════ */

void     lbp_put_u16(uint8_t *p, uint16_t v);
void     lbp_put_u32(uint8_t *p, uint32_t v);
void     lbp_put_u64(uint8_t *p, uint64_t v);
void     lbp_put_f32(uint8_t *p, float v);
uint16_t lbp_get_u16(const uint8_t *p);
uint32_t lbp_get_u32(const uint8_t *p);
uint64_t lbp_get_u64(const uint8_t *p);
float    lbp_get_f32(const uint8_t *p);

/* ══════════════ BMD 二进制序列化 ══════════════ */

/*
 * 布局（无对齐填充）：
 *   magic       4   'L','B','M','D'
 *   ver_major   1
 *   ver_minor   1
 *   cls         1
 *   role        1
 *   vendor_id   2
 *   product_id  2
 *   serial      8
 *   dof         1
 *   joints      dof × 68
 *                 name[16] axis[3]f32 min f32 max f32 vel f32 torque f32
 *                 offset[3]f32 link[3]f32
 *   port_count  1
 *   ports       n × 25   (pos_id 1 + normal[3]f32 + offset[3]f32)
 *   mass        4
 *   com_offset  12
 *   payload     4
 *   reach       4
 *   bus_profile 1
 *   bus_addr    1
 *   power_mw    2
 *   power_peak  2
 *   caps        4
 *   hw_timestamp 1
 *   name        32
 */
#define LBP_BMD_JOINT_SIZE  68
#define LBP_BMD_PORT_SIZE   25
/*
 * 逐项相加：4 magic + 2 ver + 1 cls + 1 role + 2 vid + 2 pid + 8 serial
 *         + 1 dof + 1 port_count + 4 mass + 12 com + 4 payload + 4 reach
 *         + 1 bus + 1 addr + 2 power + 2 peak + 4 caps + 1 hw_ts + 32 name
 *         = 89
 *
 * ⚠ 早期版本漏了 mass 的 4 字节，导致 encoded_size 少算 4，
 *   编码时长度检查通过但实际越界写 4 字节（缓冲区溢出）。
 *   tests 里的 BMD 字节对齐检查就是为防这个而写的。
 */
#define LBP_BMD_FIXED_SIZE  89

/** 计算 BMD 编码后字节数 */
size_t lbp_bmd_encoded_size(const lbp_bmd_t *bmd);

/** 编码。返回写入字节数，0 失败 */
size_t lbp_bmd_encode(const lbp_bmd_t *bmd, uint8_t *out, size_t out_len);

/** 解码。返回 LBP_OK / LBP_ERR_PARSE */
lbp_err_t lbp_bmd_decode(const uint8_t *data, size_t len, lbp_bmd_t *out);

/* ══════════════ TOPO_ACK ══════════════ */

/*
 * addr(1) mount_port(1) child_count(1) [port(1) child(1)] × N
 * 无子模块时 3 字节。
 */
#define LBP_TOPO_MAX_CHILDREN 16

size_t lbp_topo_ack_encode(uint8_t addr, uint8_t mount_port,
                           const uint8_t *child_ports,
                           const uint8_t *child_addrs, uint8_t n,
                           uint8_t *out, size_t out_len);

lbp_err_t lbp_topo_ack_decode(const uint8_t *data, size_t len,
                              uint8_t *addr, uint8_t *mount_port,
                              uint8_t *child_ports, uint8_t *child_addrs,
                              uint8_t *n_out);

/* ══════════════ CMD ══════════════ */

/* flags(1) dof(1) q(f32) × dof   → 3 DOF 时 14 字节 */
#define LBP_CMD_FLAG_ESTOP  (1u << 0)

size_t lbp_cmd_encode(uint8_t flags, const float *q, uint8_t dof,
                      uint8_t *out, size_t out_len);

lbp_err_t lbp_cmd_decode(const uint8_t *data, size_t len,
                         uint8_t *flags, float *q, uint8_t q_cap,
                         uint8_t *dof_out);

/* ══════════════ TELEM ══════════════ */

/*
 * addr(1) flags(1) dof(1) q(f32)×dof [torque(f32)×dof] [temp(i8)]
 * flags: bit0 = 带力矩，bit1 = 带温度
 */
#define LBP_TELEM_HAS_TORQUE (1u << 0)
#define LBP_TELEM_HAS_TEMP   (1u << 1)

size_t lbp_telem_encode(uint8_t addr, const float *q, const float *torque,
                        int8_t temp_c, bool has_temp, uint8_t dof,
                        uint8_t *out, size_t out_len);

lbp_err_t lbp_telem_decode(const uint8_t *data, size_t len,
                           uint8_t *addr, float *q, float *torque,
                           int8_t *temp_c, uint8_t q_cap, uint8_t *dof_out);

/* ══════════════ REFLEX / CLOCK_SYNC ══════════════ */

size_t lbp_reflex_encode(uint8_t addr, uint8_t code, uint8_t joint,
                         float value, uint8_t *out, size_t out_len);

lbp_err_t lbp_reflex_decode(const uint8_t *data, size_t len,
                            uint8_t *addr, uint8_t *code, uint8_t *joint,
                            float *value);

size_t lbp_clock_sync_encode(uint64_t t1_us, uint8_t *out, size_t out_len);
lbp_err_t lbp_clock_sync_decode(const uint8_t *data, size_t len,
                                uint64_t *t1_us);

#ifdef __cplusplus
}
#endif