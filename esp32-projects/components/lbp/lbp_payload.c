/*
 * lbp_payload.c — 载荷编解码实现
 */
#include <string.h>
#include "lbp_payload.h"

/* ══════════════════════════════════════════════════════════
 *  小端读写
 * ══════════════════════════════════════════════════════════ */

void lbp_put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
}

void lbp_put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
    p[2] = (uint8_t)((v >> 16) & 0xFF);
    p[3] = (uint8_t)((v >> 24) & 0xFF);
}

void lbp_put_u64(uint8_t *p, uint64_t v)
{
    for (int i = 0; i < 8; i++) p[i] = (uint8_t)((v >> (8 * i)) & 0xFF);
}

void lbp_put_f32(uint8_t *p, float v)
{
    uint32_t bits;
    memcpy(&bits, &v, sizeof(bits));
    lbp_put_u32(p, bits);
}

uint16_t lbp_get_u16(const uint8_t *p)
{
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

uint32_t lbp_get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint64_t lbp_get_u64(const uint8_t *p)
{
    uint64_t v = 0;
    for (int i = 7; i >= 0; i--) v = (v << 8) | p[i];
    return v;
}

float lbp_get_f32(const uint8_t *p)
{
    uint32_t bits = lbp_get_u32(p);
    float v;
    memcpy(&v, &bits, sizeof(v));
    return v;
}

static void put_vec3(uint8_t *p, const float v[3])
{
    lbp_put_f32(p, v[0]);
    lbp_put_f32(p + 4, v[1]);
    lbp_put_f32(p + 8, v[2]);
}

static void get_vec3(const uint8_t *p, float v[3])
{
    v[0] = lbp_get_f32(p);
    v[1] = lbp_get_f32(p + 4);
    v[2] = lbp_get_f32(p + 8);
}

static void put_name(char *dst, size_t cap, const char *src)
{
    memset(dst, 0, cap);
    if (!src) return;
    size_t n = strlen(src);
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
}

/* ══════════════════════════════════════════════════════════
 *  BMD
 * ══════════════════════════════════════════════════════════ */

#define BMD_MAGIC0 'L'
#define BMD_MAGIC1 'B'
#define BMD_MAGIC2 'M'
#define BMD_MAGIC3 'D'

size_t lbp_bmd_encoded_size(const lbp_bmd_t *bmd)
{
    if (!bmd) return 0;
    return (size_t)LBP_BMD_FIXED_SIZE
         + (size_t)bmd->dof * LBP_BMD_JOINT_SIZE
         + (size_t)bmd->port_count * LBP_BMD_PORT_SIZE;
}

size_t lbp_bmd_encode(const lbp_bmd_t *bmd, uint8_t *out, size_t out_len)
{
    if (!bmd || !out) return 0;
    if (bmd->dof > LBP_MAX_JOINTS) return 0;
    if (bmd->port_count > LBP_MAX_PORTS) return 0;

    size_t need = lbp_bmd_encoded_size(bmd);
    if (out_len < need) return 0;

    uint8_t *p = out;

    *p++ = BMD_MAGIC0; *p++ = BMD_MAGIC1;
    *p++ = BMD_MAGIC2; *p++ = BMD_MAGIC3;
    *p++ = bmd->ver_major ? bmd->ver_major : 1;
    *p++ = bmd->ver_minor;
    *p++ = bmd->cls;
    *p++ = bmd->role;
    lbp_put_u16(p, bmd->vendor_id);           p += 2;
    lbp_put_u16(p, bmd->product_id);          p += 2;
    lbp_put_u64(p, bmd->serial);              p += 8;
    *p++ = bmd->dof;

    for (uint8_t i = 0; i < bmd->dof; i++) {
        const lbp_joint_t *j = &bmd->joints[i];
        put_name((char *)p, 16, j->name);     p += 16;
        put_vec3(p, j->axis);                 p += 12;
        lbp_put_f32(p, j->min_rad);           p += 4;
        lbp_put_f32(p, j->max_rad);           p += 4;
        lbp_put_f32(p, j->max_vel_rad_s);     p += 4;
        lbp_put_f32(p, j->max_torque_nm);     p += 4;
        put_vec3(p, j->offset);               p += 12;
        put_vec3(p, j->link);                 p += 12;
    }

    *p++ = bmd->port_count;
    for (uint8_t i = 0; i < bmd->port_count; i++) {
        const lbp_port_t *pt = &bmd->ports[i];
        *p++ = pt->pos_id;
        put_vec3(p, pt->normal);              p += 12;
        put_vec3(p, pt->offset);              p += 12;
    }

    lbp_put_f32(p, bmd->mass_kg);             p += 4;
    put_vec3(p, bmd->com_offset);             p += 12;
    lbp_put_f32(p, bmd->payload_kg);          p += 4;
    lbp_put_f32(p, bmd->reach_m);             p += 4;
    *p++ = bmd->bus_profile;
    *p++ = bmd->bus_addr;
    lbp_put_u16(p, bmd->power_mw);            p += 2;
    lbp_put_u16(p, bmd->power_peak_mw);       p += 2;
    lbp_put_u32(p, bmd->caps);                p += 4;
    *p++ = bmd->hw_timestamp ? 1 : 0;
    put_name((char *)p, LBP_NAME_LEN, bmd->name); p += LBP_NAME_LEN;

    return (size_t)(p - out);
}

lbp_err_t lbp_bmd_decode(const uint8_t *data, size_t len, lbp_bmd_t *out)
{
    if (!data || !out) return LBP_ERR_INVALID_ARG;
    if (len < 4) return LBP_ERR_PARSE;
    if (data[0] != BMD_MAGIC0 || data[1] != BMD_MAGIC1 ||
        data[2] != BMD_MAGIC2 || data[3] != BMD_MAGIC3) {
        return LBP_ERR_PARSE;
    }

    memset(out, 0, sizeof(*out));
    const uint8_t *p = data + 4;

    /* 先读固定头部里决定变长的字段：先跑到 dof */
    out->ver_major = p[0];
    out->ver_minor = p[1];
    out->cls       = p[2];
    out->role      = p[3];
    out->vendor_id = lbp_get_u16(p + 4);
    out->product_id = lbp_get_u16(p + 6);
    out->serial    = lbp_get_u64(p + 8);
    out->dof       = p[16];
    p += 17;

    if (out->dof > LBP_MAX_JOINTS) return LBP_ERR_PARSE;
    if ((size_t)(p - data) + (size_t)out->dof * LBP_BMD_JOINT_SIZE > len) {
        return LBP_ERR_PARSE;
    }

    for (uint8_t i = 0; i < out->dof; i++) {
        lbp_joint_t *j = &out->joints[i];
        memcpy(j->name, p, 15);
        j->name[15] = 0;
        p += 16;
        get_vec3(p, j->axis);       p += 12;
        j->min_rad        = lbp_get_f32(p); p += 4;
        j->max_rad        = lbp_get_f32(p); p += 4;
        j->max_vel_rad_s  = lbp_get_f32(p); p += 4;
        j->max_torque_nm  = lbp_get_f32(p); p += 4;
        get_vec3(p, j->offset);     p += 12;
        get_vec3(p, j->link);       p += 12;
    }

    if ((size_t)(p - data) + 1 > len) return LBP_ERR_PARSE;
    out->port_count = *p++;
    if (out->port_count > LBP_MAX_PORTS) return LBP_ERR_PARSE;
    if ((size_t)(p - data) + (size_t)out->port_count * LBP_BMD_PORT_SIZE > len) {
        return LBP_ERR_PARSE;
    }

    for (uint8_t i = 0; i < out->port_count; i++) {
        lbp_port_t *pt = &out->ports[i];
        pt->pos_id = *p++;
        get_vec3(p, pt->normal);    p += 12;
        get_vec3(p, pt->offset);    p += 12;
    }

    if ((size_t)(p - data) + 4 + 12 + 4 + 4 + 1 + 1 + 2 + 2 + 4 + 1
            + LBP_NAME_LEN > len) {
        return LBP_ERR_PARSE;
    }

    out->mass_kg     = lbp_get_f32(p); p += 4;
    get_vec3(p, out->com_offset);      p += 12;
    out->payload_kg  = lbp_get_f32(p); p += 4;
    out->reach_m     = lbp_get_f32(p); p += 4;
    out->bus_profile = *p++;
    out->bus_addr    = *p++;
    out->power_mw      = lbp_get_u16(p); p += 2;
    out->power_peak_mw = lbp_get_u16(p); p += 2;
    out->caps        = lbp_get_u32(p); p += 4;
    out->hw_timestamp = (*p++ != 0);
    memcpy(out->name, p, LBP_NAME_LEN - 1);
    out->name[LBP_NAME_LEN - 1] = 0;

    return LBP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  TOPO_ACK
 * ══════════════════════════════════════════════════════════ */

size_t lbp_topo_ack_encode(uint8_t addr, uint8_t mount_port,
                           const uint8_t *child_ports,
                           const uint8_t *child_addrs, uint8_t n,
                           uint8_t *out, size_t out_len)
{
    if (!out) return 0;
    if (n > LBP_TOPO_MAX_CHILDREN) n = LBP_TOPO_MAX_CHILDREN;
    if (n > 0 && (!child_ports || !child_addrs)) return 0;

    size_t need = 3 + (size_t)n * 2;
    if (out_len < need) return 0;

    out[0] = addr;
    out[1] = mount_port;
    out[2] = n;
    for (uint8_t i = 0; i < n; i++) {
        out[3 + i * 2]     = child_ports[i];
        out[3 + i * 2 + 1] = child_addrs[i];
    }
    return need;
}

lbp_err_t lbp_topo_ack_decode(const uint8_t *data, size_t len,
                              uint8_t *addr, uint8_t *mount_port,
                              uint8_t *child_ports, uint8_t *child_addrs,
                              uint8_t *n_out)
{
    if (!data || len < 3) return LBP_ERR_PARSE;
    uint8_t n = data[2];
    if (n > LBP_TOPO_MAX_CHILDREN) return LBP_ERR_PARSE;
    if (len < 3 + (size_t)n * 2) return LBP_ERR_PARSE;

    if (addr) *addr = data[0];
    if (mount_port) *mount_port = data[1];
    if (n_out) *n_out = n;
    for (uint8_t i = 0; i < n; i++) {
        if (child_ports) child_ports[i] = data[3 + i * 2];
        if (child_addrs) child_addrs[i] = data[3 + i * 2 + 1];
    }
    return LBP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  CMD
 * ══════════════════════════════════════════════════════════ */

size_t lbp_cmd_encode(uint8_t flags, const float *q, uint8_t dof,
                      uint8_t *out, size_t out_len)
{
    if (!out || (dof > 0 && !q)) return 0;
    if (dof > LBP_MAX_JOINTS) return 0;

    size_t need = 2 + (size_t)dof * 4;
    if (out_len < need) return 0;

    out[0] = flags;
    out[1] = dof;
    for (uint8_t i = 0; i < dof; i++) {
        lbp_put_f32(&out[2 + i * 4], q[i]);
    }
    return need;
}

lbp_err_t lbp_cmd_decode(const uint8_t *data, size_t len,
                         uint8_t *flags, float *q, uint8_t q_cap,
                         uint8_t *dof_out)
{
    if (!data || len < 2) return LBP_ERR_PARSE;
    uint8_t dof = data[1];
    if (dof > q_cap) return LBP_ERR_PARSE;
    if (len < 2 + (size_t)dof * 4) return LBP_ERR_PARSE;

    if (flags) *flags = data[0];
    if (dof_out) *dof_out = dof;
    for (uint8_t i = 0; i < dof; i++) {
        if (q) q[i] = lbp_get_f32(&data[2 + i * 4]);
    }
    return LBP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  TELEM
 * ══════════════════════════════════════════════════════════ */

size_t lbp_telem_encode(uint8_t addr, const float *q, const float *torque,
                        int8_t temp_c, bool has_temp, uint8_t dof,
                        uint8_t *out, size_t out_len)
{
    if (!out || (dof > 0 && !q)) return 0;
    if (dof > LBP_MAX_JOINTS) return 0;

    uint8_t flags = 0;
    if (torque) flags |= LBP_TELEM_HAS_TORQUE;
    if (has_temp) flags |= LBP_TELEM_HAS_TEMP;

    size_t need = 3 + (size_t)dof * 4;
    if (torque) need += (size_t)dof * 4;
    if (has_temp) need += 1;
    if (out_len < need) return 0;

    out[0] = addr;
    out[1] = flags;
    out[2] = dof;
    uint8_t *p = &out[3];

    for (uint8_t i = 0; i < dof; i++) { lbp_put_f32(p, q[i]); p += 4; }
    if (torque) {
        for (uint8_t i = 0; i < dof; i++) { lbp_put_f32(p, torque[i]); p += 4; }
    }
    if (has_temp) { *p++ = (uint8_t)temp_c; }

    return (size_t)(p - out);
}

lbp_err_t lbp_telem_decode(const uint8_t *data, size_t len,
                           uint8_t *addr, float *q, float *torque,
                           int8_t *temp_c, uint8_t q_cap, uint8_t *dof_out)
{
    if (!data || len < 3) return LBP_ERR_PARSE;
    uint8_t flags = data[1];
    uint8_t dof = data[2];
    if (dof > q_cap) return LBP_ERR_PARSE;

    size_t off = 3;
    if (len < off + (size_t)dof * 4) return LBP_ERR_PARSE;

    if (addr) *addr = data[0];
    if (dof_out) *dof_out = dof;
    for (uint8_t i = 0; i < dof; i++) {
        if (q) q[i] = lbp_get_f32(&data[off + i * 4]);
    }
    off += (size_t)dof * 4;

    if ((flags & LBP_TELEM_HAS_TORQUE) && torque) {
        if (len >= off + (size_t)dof * 4) {
            for (uint8_t i = 0; i < dof; i++) {
                torque[i] = lbp_get_f32(&data[off + i * 4]);
            }
            off += (size_t)dof * 4;
        }
    }

    if ((flags & LBP_TELEM_HAS_TEMP) && temp_c && len > off) {
        *temp_c = (int8_t)data[off];
    }

    return LBP_OK;
}

/* ══════════════════════════════════════════════════════════
 *  REFLEX / CLOCK_SYNC
 * ══════════════════════════════════════════════════════════ */

size_t lbp_reflex_encode(uint8_t addr, uint8_t code, uint8_t joint,
                         float value, uint8_t *out, size_t out_len)
{
    if (!out || out_len < 7) return 0;
    out[0] = addr;
    out[1] = code;
    out[2] = joint;
    lbp_put_f32(&out[3], value);
    return 7;
}

lbp_err_t lbp_reflex_decode(const uint8_t *data, size_t len,
                            uint8_t *addr, uint8_t *code, uint8_t *joint,
                            float *value)
{
    if (!data || len < 7) return LBP_ERR_PARSE;
    if (addr) *addr = data[0];
    if (code) *code = data[1];
    if (joint) *joint = data[2];
    if (value) *value = lbp_get_f32(&data[3]);
    return LBP_OK;
}

size_t lbp_clock_sync_encode(uint64_t t1_us, uint8_t *out, size_t out_len)
{
    if (!out || out_len < 8) return 0;
    lbp_put_u64(out, t1_us);
    return 8;
}

lbp_err_t lbp_clock_sync_decode(const uint8_t *data, size_t len,
                                uint64_t *t1_us)
{
    if (!data || len < 8) return LBP_ERR_PARSE;
    if (t1_us) *t1_us = lbp_get_u64(data);
    return LBP_OK;
}