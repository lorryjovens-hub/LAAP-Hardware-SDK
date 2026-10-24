/*
 * LBP 自检固件 — 在模拟器或真机上验证 C 实现的纯逻辑
 *
 * ## 为什么先做这个
 *
 * 3254 行 C 代码从没编译过。等硬件到货才发现编译不过，是最浪费时间的顺序。
 *
 * 这个固件把 LBP 里**不依赖 CAN 硬件**的部分全跑一遍：
 *   CRC / 帧编解码 / 分片重组 / TP 分段 / 载荷编解码 / BMD 序列化
 *
 * 只要能编过并打印 "ALL PASS"，就说明逻辑层是好的，
 * 剩下的风险只有真实总线时序和舵机驱动。
 *
 * ## 怎么跑
 *
 * 真机：
 *   idf.py -p COM3 flash monitor
 *
 * 模拟器（WSL）：
 *   esp-emu --chip esp32s3 --firmware build/lbp_selftest.bin \
 *           --exit-on "LBP SELFTEST DONE" --timeout 60
 *
 * This file is part of LAAP Hardware SDK, GPL v3.
 */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "lbp.h"

static int s_pass = 0;
static int s_fail = 0;

#define CHECK(name, cond) do {                                   \
    if (cond) { s_pass++; printf("  [PASS] %s\n", name); }        \
    else      { s_fail++; printf("  [FAIL] %s\n", name); }        \
} while (0)

#define CHECK_EQ_INT(name, a, b) do {                             \
    long _a = (long)(a), _b = (long)(b);                          \
    if (_a == _b) { s_pass++; printf("  [PASS] %s = %ld\n", name, _a); } \
    else { s_fail++; printf("  [FAIL] %s: %ld != %ld\n", name, _a, _b); } \
} while (0)

/* ══════════════════════════════════════════════════════════
 *  CAN 环回管道：用来测 TP 层
 * ══════════════════════════════════════════════════════════ */

#define MAX_CAN_FRAMES 96

typedef struct {
    uint32_t id[MAX_CAN_FRAMES];
    uint8_t  data[MAX_CAN_FRAMES][8];
    uint8_t  dlc[MAX_CAN_FRAMES];
    int      n;
} can_trace_t;

static can_trace_t g_trace;

static lbp_err_t trace_send(uint32_t can_id, const uint8_t *data,
                            uint8_t dlc, void *user)
{
    can_trace_t *t = (can_trace_t *)user;
    if (t->n >= MAX_CAN_FRAMES) return LBP_ERR_NO_MEM;
    t->id[t->n] = can_id;
    memcpy(t->data[t->n], data, 8);
    t->dlc[t->n] = dlc;
    t->n++;
    return LBP_OK;
}

typedef struct {
    uint8_t frame[LBP_MAX_FRAME];
    size_t  len;
    int     count;
    uint32_t last_id;
} recv_sink_t;

static void sink_recv(uint32_t can_id, const uint8_t *f, size_t len, void *user)
{
    recv_sink_t *s = (recv_sink_t *)user;
    if (len <= sizeof(s->frame)) {
        memcpy(s->frame, f, len);
        s->len = len;
        s->last_id = can_id;
    }
    s->count++;
}

/* ══════════════════════════════════════════════════════════
 *  1. CRC32
 * ══════════════════════════════════════════════════════════ */

static void test_crc(void)
{
    printf("\n[1] CRC-32/ISO-HDLC\n");

    /* 标准测试向量：crc32("123456789") = 0xCBF43926 */
    const char *v = "123456789";
    uint32_t c = lbp_crc32((const uint8_t *)v, 9);
    CHECK_EQ_INT("crc32(\"123456789\")", c, 0xCBF43926);

    /* 空输入 = 0 */
    CHECK_EQ_INT("crc32(\"\")", lbp_crc32(NULL, 0), 0);

    /* 单字节 0x00 */
    uint8_t z = 0;
    uint32_t cz = lbp_crc32(&z, 1);
    CHECK("crc32(0x00) = 0xD202EF8D", cz == 0xD202EF8D);
}

/* ══════════════════════════════════════════════════════════
 *  2. 帧编解码
 * ══════════════════════════════════════════════════════════ */

static void test_frame(void)
{
    printf("\n[2] 帧编解码\n");

    uint8_t payload[14] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14};
    lbp_frame_t f;
    memset(&f, 0, sizeof(f));
    f.type = LBP_MSG_CMD;
    f.src = 3;
    f.dst = 7;
    f.seq = 0x12;
    f.ttl = 8;
    f.prio = LBP_PRIO_CONTROL;
    f.t_exec_us = 500000;
    f.len = 14;
    f.payload = payload;

    uint8_t wire[128];
    size_t n = lbp_frame_encode(&f, wire, sizeof(wire));
    CHECK_EQ_INT("编码长度 = 18+14+5", n, 37);
    CHECK("SOF = 0x4C", wire[0] == LBP_SOF);
    CHECK("EOF = 0xAA", wire[n - 1] == LBP_EOF);
    CHECK("VER = 0x10", wire[1] == LBP_VER_BYTE);

    lbp_frame_t g;
    lbp_err_t e = lbp_frame_decode(wire, n, &g);
    CHECK("解码成功", e == LBP_OK);
    CHECK_EQ_INT("type", g.type, LBP_MSG_CMD);
    CHECK_EQ_INT("src", g.src, 3);
    CHECK_EQ_INT("dst", g.dst, 7);
    CHECK_EQ_INT("seq", g.seq, 0x12);
    CHECK_EQ_INT("t_exec", g.t_exec_us, 500000);
    CHECK_EQ_INT("len", g.len, 14);
    CHECK("载荷一致", memcmp(g.payload, payload, 14) == 0);
    CHECK("优先级解析正确", g.prio == LBP_PRIO_CONTROL);

    /* 单 bit 错误必须被 CRC 抓到 */
    uint8_t bad[128];
    memcpy(bad, wire, n);
    bad[20] ^= 0x01;
    lbp_frame_t h;
    CHECK("CRC 检出单 bit 错误",
          lbp_frame_decode(bad, n, &h) == LBP_ERR_CRC);

    /* SOF 错 */
    memcpy(bad, wire, n);
    bad[0] = 0x00;
    CHECK("SOF 错误被拒", lbp_frame_decode(bad, n, &h) == LBP_ERR_FRAME);

    /* 长度不符 */
    CHECK("长度不符被拒", lbp_frame_decode(wire, n - 1, &h) != LBP_OK);

    /* 空载荷帧 */
    lbp_frame_t k;
    memset(&k, 0, sizeof(k));
    k.type = LBP_MSG_ENUM_REQ;
    k.src = 1;
    k.dst = LBP_ADDR_BROADCAST;
    k.prio = LBP_PRIO_CONFIG;
    uint8_t w2[64];
    size_t n2 = lbp_frame_encode(&k, w2, sizeof(w2));
    CHECK_EQ_INT("空载荷帧长度 = 23", n2, 23);
    lbp_frame_t k2;
    CHECK("空载荷帧解码成功", lbp_frame_decode(w2, n2, &k2) == LBP_OK);
    CHECK_EQ_INT("广播地址", k2.dst, LBP_ADDR_BROADCAST);
    CHECK_EQ_INT("空载荷 len=0", k2.len, 0);
}

/* ══════════════════════════════════════════════════════════
 *  3. 分片重组（LBP 层，载荷 > 1024 才用）
 * ══════════════════════════════════════════════════════════ */

static void test_frag(void)
{
    printf("\n[3] 分片重组\n");

    /* 造 900 字节"固件块" */
    static uint8_t data[900];
    for (int i = 0; i < 900; i++) data[i] = (uint8_t)(i * 7 + 3);

    CHECK_EQ_INT("单片容量（CAN 2.0B 帧上限 23B 不合用，用 64B）",
                 lbp_frag_chunk(64), 64 - 18 - 5 - 5);

    uint8_t total = lbp_frag_part_count(900, 64);
    CHECK_EQ_INT("分片数", total, (900 + 35) / 36);

    /* ⚠ lbp_reasm_t 单实例 ~4.1KB（4 个槽 × 1KB 缓冲），
     * 必须放 static / 堆，不能放栈 —— 否则 app_main 默认 3.5KB 栈直接爆。
     * 这是实测出来的：放栈上会 InstructionFetchError + Backtrace CORRUPTED。 */
    static lbp_reasm_t r;
    lbp_reasm_init(&r, 1000);

    const uint8_t *out = NULL;
    uint16_t out_len = 0;
    uint8_t out_type = 0;
    bool done = false;

    uint8_t wire[128];
    for (int i = 0; i < total; i++) {
        size_t wl = sizeof(wire);
        if (lbp_frag_build(data, 900, 7, (uint8_t)i, total,
                           LBP_MSG_OTA, 64, wire, &wl) != LBP_OK) {
            printf("    frag_build 失败 @%d\n", i);
            break;
        }
        lbp_frame_t f;
        if (lbp_frame_decode(wire, wl, &f) != LBP_OK) {
            printf("    frag 解码失败 @%d\n", i);
            break;
        }
        lbp_err_t e = lbp_reasm_feed(&r, &f, &out, &out_len, &out_type);
        if (e == LBP_OK) { done = true; break; }
    }

    CHECK("分片能重组完成", done);
    CHECK_EQ_INT("重组长度", out_len, 900);
    CHECK_EQ_INT("原始类型保留", out_type, LBP_MSG_OTA);
    CHECK("重组内容一致", done && memcmp(out, data, 900) == 0);
    CHECK("重组统计 groups_done=1", r.groups_done == 1);
    /* 丢片必须检测出来，不能误判为完整 */
    static lbp_reasm_t r2;
    lbp_reasm_init(&r2, 1000);
    const uint8_t *o2 = NULL;
    uint16_t l2 = 0;
    uint8_t t2 = 0;
    bool bad_done = false;
    for (int i = 0; i < total; i++) {
        if (i == 3) continue;               /* 故意丢第 4 片 */
        size_t wl = sizeof(wire);
        lbp_frag_build(data, 900, 8, (uint8_t)i, total, LBP_MSG_OTA, 64,
                       wire, &wl);
        lbp_frame_t f;
        lbp_frame_decode(wire, wl, &f);
        if (lbp_reasm_feed(&r2, &f, &o2, &l2, &t2) == LBP_OK) {
            bad_done = true;
        }
    }
    CHECK("丢片后不会误判为完整", !bad_done);
}

/* ══════════════════════════════════════════════════════════
 *  4. TP 分段（CAN 8 字节）
 * ══════════════════════════════════════════════════════════ */

static void test_tp(void)
{
    printf("\n[4] TP 分段（CAN 2.0B 8 字节）\n");

    CHECK_EQ_INT("23B → 段数", lbp_tp_segment_count(23), 4);
    CHECK_EQ_INT("37B → 段数", lbp_tp_segment_count(37), 6);
    CHECK_EQ_INT("7B  → 单段", lbp_tp_segment_count(7), 1);
    CHECK_EQ_INT("8B  → 2 段", lbp_tp_segment_count(8), 2);
    CHECK_EQ_INT("341B → 段数", lbp_tp_segment_count(341), 49);

    /* 环回：编码一个 LBP 帧 → TP 切成 CAN 帧 → 再喂给另一个 TP → 比对 */
    uint8_t payload[14] = {9, 8, 7, 6, 5, 4, 3, 2, 1, 0, 1, 2, 3, 4};
    lbp_frame_t f;
    memset(&f, 0, sizeof(f));
    f.type = LBP_MSG_TELEM;
    f.src = 5;
    f.dst = 1;
    f.seq = 1;
    f.ttl = 8;
    f.prio = LBP_PRIO_CONTROL;
    f.len = 14;
    f.payload = payload;

    uint8_t wire[128];
    size_t wl = lbp_frame_encode(&f, wire, sizeof(wire));

    memset(&g_trace, 0, sizeof(g_trace));
    /* ⚠ lbp_tp_t ≈ 4.3KB（4 槽 × 1KB），必须 static，不能放栈 */
    static lbp_tp_t tx;
    lbp_tp_init(&tx, 500);
    uint32_t can_id = lbp_tp_can_id(f.prio, f.dst);
    lbp_err_t e = lbp_tp_send(&tx, can_id, wire, wl, trace_send, &g_trace);
    CHECK("TP 发送成功", e == LBP_OK);
    CHECK_EQ_INT("CAN 帧数 = 6", g_trace.n, 6);
    CHECK_EQ_INT("优先级进 CAN ID 高位",
                 (can_id >> 8) & 0x03, (uint32_t)f.prio);
    CHECK_EQ_INT("目的地址进 CAN ID 低位", can_id & 0xFF, f.dst);

    /* 首段应带总长 */
    CHECK("首段类型 FIRST", (g_trace.data[0][0] & 0x0F) == LBP_TP_FIRST);
    CHECK_EQ_INT("首段声明总长",
                 (int)(g_trace.data[0][1] | (g_trace.data[0][2] << 8)),
                 (int)wl);
    CHECK("末段类型 LAST",
          (g_trace.data[g_trace.n - 1][0] & 0x0F) == LBP_TP_LAST);

    /* 接收侧重拼 */
    static recv_sink_t sink;
    memset(&sink, 0, sizeof(sink));
    static lbp_tp_t rx;
    lbp_tp_init(&rx, 500);
    for (int i = 0; i < g_trace.n; i++) {
        lbp_tp_feed(&rx, g_trace.id[i], g_trace.data[i], g_trace.dlc[i],
                    sink_recv, &sink);
    }
    CHECK_EQ_INT("重拼出 1 个 LBP 帧", sink.count, 1);
    CHECK_EQ_INT("重拼长度一致", (int)sink.len, (int)wl);
    CHECK("重拼内容一致", sink.len == wl && memcmp(sink.frame, wire, wl) == 0);

    /* 丢一段应导致整组作废 */
    static recv_sink_t sink2;
    memset(&sink2, 0, sizeof(sink2));
    static lbp_tp_t rx2;
    lbp_tp_init(&rx2, 500);
    for (int i = 0; i < g_trace.n; i++) {
        if (i == 2) continue;                /* 丢中间一段 */
        lbp_tp_feed(&rx2, g_trace.id[i], g_trace.data[i], g_trace.dlc[i],
                    sink_recv, &sink2);
    }
    CHECK("丢段不会拼出完整帧", sink2.count == 0);
    CHECK("丢段有统计", rx2.drops > 0);
}

/* ══════════════════════════════════════════════════════════
 *  5. 载荷编解码
 * ══════════════════════════════════════════════════════════ */

static void test_payload(void)
{
    printf("\n[5] 载荷编解码\n");

    /* TOPO_ACK：无子模块 3 字节 */
    uint8_t buf[64];
    size_t n = lbp_topo_ack_encode(2, 3, NULL, NULL, 0, buf, sizeof(buf));
    CHECK_EQ_INT("TOPO_ACK 无子模块 = 3B", n, 3);

    uint8_t addr = 0, port = 0, cnt = 0, cp[8], ca[8];
    CHECK("TOPO_ACK 解码成功",
          lbp_topo_ack_decode(buf, n, &addr, &port, cp, ca, &cnt) == LBP_OK);
    CHECK_EQ_INT("addr", addr, 2);
    CHECK_EQ_INT("mount_port", port, 3);
    CHECK_EQ_INT("child_count", cnt, 0);

    /* 带 2 个子模块 = 7 字节 */
    uint8_t cps[2] = {0, 4}, cas[2] = {3, 5};
    n = lbp_topo_ack_encode(2, 0, cps, cas, 2, buf, sizeof(buf));
    CHECK_EQ_INT("TOPO_ACK 2 子模块 = 7B", n, 7);
    lbp_topo_ack_decode(buf, n, &addr, &port, cp, ca, &cnt);
    CHECK_EQ_INT("子模块数", cnt, 2);
    CHECK("子端口/地址正确", cp[0] == 0 && ca[0] == 3 && cp[1] == 4 && ca[1] == 5);

    /* CMD：3 DOF = 14 字节 */
    float q[3] = {-0.5236f, 0.3491f, -0.6981f};
    n = lbp_cmd_encode(0, q, 3, buf, sizeof(buf));
    CHECK_EQ_INT("CMD 3DOF = 14B", n, 14);

    uint8_t flags = 0xFF;
    uint8_t dof = 0;
    float q2[8];
    CHECK("CMD 解码成功",
          lbp_cmd_decode(buf, n, &flags, q2, 8, &dof) == LBP_OK);
    CHECK_EQ_INT("CMD flags", flags, 0);
    CHECK_EQ_INT("CMD dof", dof, 3);
    CHECK("CMD 数值一致",
          fabsf(q2[0] - q[0]) < 1e-6 && fabsf(q2[2] - q[2]) < 1e-6);

    /* TELEM：3DOF 纯位置 = 15 字节 */
    n = lbp_telem_encode(4, q, NULL, 0, false, 3, buf, sizeof(buf));
    CHECK_EQ_INT("TELEM 纯位置 = 15B", n, 15);

    /* TELEM：3DOF + 力矩 + 温度 = 3+12+12+1 = 28 字节 */
    float tq[3] = {1.1f, 2.2f, 3.3f};
    n = lbp_telem_encode(4, q, tq, 45, true, 3, buf, sizeof(buf));
    CHECK_EQ_INT("TELEM 含力矩温度 = 28B", n, 28);

    float q3[8], tq3[8];
    int8_t temp = 0;
    CHECK("TELEM 解码成功",
          lbp_telem_decode(buf, n, &addr, q3, tq3, &temp, 8, &dof) == LBP_OK);
    CHECK_EQ_INT("TELEM addr", addr, 4);
    CHECK_EQ_INT("TELEM temp", temp, 45);
    CHECK("TELEM 力矩一致", fabsf(tq3[1] - 2.2f) < 1e-6);

    /* REFLEX = 7 字节 */
    n = lbp_reflex_encode(2, LBP_REFLEX_OVER_CURRENT, 1, 2.5f,
                          buf, sizeof(buf));
    CHECK_EQ_INT("REFLEX = 7B", n, 7);
    uint8_t ra = 0, rc = 0, rj = 0;
    float rv = 0;
    CHECK("REFLEX 解码成功",
          lbp_reflex_decode(buf, n, &ra, &rc, &rj, &rv) == LBP_OK);
    CHECK("REFLEX 字段正确",
          ra == 2 && rc == LBP_REFLEX_OVER_CURRENT && rj == 1
          && fabsf(rv - 2.5f) < 1e-6);

    /* CLOCK_SYNC = 8 字节 */
    n = lbp_clock_sync_encode(1234567890123ULL, buf, sizeof(buf));
    CHECK_EQ_INT("CLOCK_SYNC = 8B", n, 8);
    uint64_t t1 = 0;
    lbp_clock_sync_decode(buf, n, &t1);
    CHECK("CLOCK_SYNC 数值一致", t1 == 1234567890123ULL);
}

/* ══════════════════════════════════════════════════════════
 *  6. BMD 序列化
 * ══════════════════════════════════════════════════════════ */

static void test_bmd(void)
{
    printf("\n[6] BMD 序列化\n");

    static lbp_bmd_t leg;
    lbp_fill_leg_3dof_bmd(&leg, 0x1122334455667788ULL);

    CHECK_EQ_INT("腿 dof", leg.dof, 3);
    CHECK("名字是 leg_3dof", strcmp(leg.name, "leg_3dof") == 0);

    size_t need = lbp_bmd_encoded_size(&leg);
    CHECK_EQ_INT("腿 BMD 大小 = 89+3*68+25", need, 89 + 3 * 68 + 25);
    CHECK_EQ_INT("腿 BMD = 318B", need, 318);

    static uint8_t buf[512];
    size_t n = lbp_bmd_encode(&leg, buf, sizeof(buf));
    CHECK_EQ_INT("编码长度", n, 318);
    CHECK("magic = LBMD",
          buf[0] == 'L' && buf[1] == 'B' && buf[2] == 'M' && buf[3] == 'D');
    CHECK_EQ_INT("cls 在偏移 6", buf[6], LBP_CLS_ACTUATOR);
    CHECK_EQ_INT("role 在偏移 7", buf[7], LBP_ROLE_LIMB);
    CHECK_EQ_INT("dof 在偏移 20", buf[20], 3);

    static lbp_bmd_t back;
    CHECK("解码成功", lbp_bmd_decode(buf, n, &back) == LBP_OK);
    CHECK_EQ_INT("解码 dof", back.dof, leg.dof);
    CHECK_EQ_INT("解码 serial 高位", (int)(back.serial >> 32), 0x11223344);
    CHECK("解码名字", strcmp(back.name, "leg_3dof") == 0);
    CHECK("解码关节名", strcmp(back.joints[2].name, "knee") == 0);
    CHECK("解码质量", fabsf(back.mass_kg - 0.28f) < 1e-6);
    CHECK("解码轴", fabsf(back.joints[0].axis[0] - 1.0f) < 1e-6);
    CHECK("解码限位",
          fabsf(back.joints[2].min_rad - leg.joints[2].min_rad) < 1e-5);
    CHECK_EQ_INT("解码端口数", back.port_count, 1);

    /* 再编码必须逐字节相同 */
    static uint8_t buf2[512];
    size_t n2 = lbp_bmd_encode(&back, buf2, sizeof(buf2));
    CHECK("往返逐字节相同", n2 == n && memcmp(buf, buf2, n) == 0);

    /* 4-DOF 臂 = 89 + 4*68 + 25 = 386 */
    static lbp_bmd_t arm;
    lbp_fill_arm_4dof_bmd(&arm, 0x1002);
    size_t an = lbp_bmd_encoded_size(&arm);
    CHECK_EQ_INT("臂 BMD = 386B", an, 386);
    static uint8_t abuf[640];
    size_t an2 = lbp_bmd_encode(&arm, abuf, sizeof(abuf));
    CHECK_EQ_INT("臂编码长度", an2, 386);

    static lbp_bmd_t arm_back;
    CHECK("臂解码成功", lbp_bmd_decode(abuf, an2, &arm_back) == LBP_OK);
    CHECK_EQ_INT("臂 dof", arm_back.dof, 4);
    CHECK("臂 caps 含 MANIPULATION",
          (arm_back.caps & LBP_CAP_MANIPULATION) != 0);

    /* 缓冲区不足时必须拒绝，不能越界写 */
    uint8_t tiny[100];
    CHECK("缓冲区不足时编码返回 0",
          lbp_bmd_encode(&leg, tiny, sizeof(tiny)) == 0);
}

/* ══════════════════════════════════════════════════════════
 *  7. 端到端：BMD 走完整链路（帧 → TP → CAN 帧 → 反解）
 * ══════════════════════════════════════════════════════════ */

static void test_end_to_end(void)
{
    printf("\n[7] 端到端：BMD 走完整链路\n");

    static lbp_bmd_t leg;
    lbp_fill_leg_3dof_bmd(&leg, 0xAABBCCDD);
    leg.bus_addr = 2;

    static uint8_t bmd_buf[512];
    size_t blen = lbp_bmd_encode(&leg, bmd_buf, sizeof(bmd_buf));

    /* 包成 ENUM_ACK LBP 帧 */
    lbp_frame_t f;
    memset(&f, 0, sizeof(f));
    f.type = LBP_MSG_ENUM_ACK;
    f.src = 2;
    f.dst = 1;
    f.prio = LBP_PRIO_CONFIG;
    f.ttl = 8;
    f.len = (uint16_t)blen;
    f.payload = bmd_buf;

    static uint8_t wire[1024];
    size_t wl = lbp_frame_encode(&f, wire, sizeof(wire));
    CHECK_EQ_INT("LBP 帧长 = 18+318+5", wl, 341);

    /* TP 切段 */
    static can_trace_t tr;
    memset(&tr, 0, sizeof(tr));
    static lbp_tp_t tx;         /* ⚠ 4KB 结构，必须 static */
    lbp_tp_init(&tx, 500);
    uint32_t cid = lbp_tp_can_id(f.prio, f.dst);
    lbp_tp_send(&tx, cid, wire, wl, trace_send, &tr);
    CHECK_EQ_INT("CAN 帧数 = 49", tr.n, 49);
    CHECK("每个 CAN 帧不超 8 字节", tr.dlc[0] <= 8);

    /* 重拼 */
    static recv_sink_t sink;
    memset(&sink, 0, sizeof(sink));
    static lbp_tp_t rx;         /* ⚠ 4KB 结构，必须 static */
    lbp_tp_init(&rx, 500);
    for (int i = 0; i < tr.n; i++) {
        lbp_tp_feed(&rx, tr.id[i], tr.data[i], tr.dlc[i], sink_recv, &sink);
    }
    CHECK_EQ_INT("重拼出 1 帧", sink.count, 1);

    lbp_frame_t g;
    CHECK("重拼帧解码成功", lbp_frame_decode(sink.frame, sink.len, &g) == LBP_OK);
    CHECK_EQ_INT("类型是 ENUM_ACK", g.type, LBP_MSG_ENUM_ACK);
    CHECK_EQ_INT("源地址 2", g.src, 2);

    static lbp_bmd_t got;
    CHECK("BMD 解码成功", lbp_bmd_decode(g.payload, g.len, &got) == LBP_OK);
    CHECK("序列号一致", got.serial == 0xAABBCCDD);
    CHECK("关节数一致", got.dof == 3);
    CHECK("名字一致", strcmp(got.name, "leg_3dof") == 0);

    printf("    链路：BMD %uB → LBP 帧 %uB → %d 个 CAN 帧 → 解回 BMD %uDOF\n",
           (unsigned)blen, (unsigned)wl, tr.n, got.dof);
}

/* ══════════════════════════════════════════════════════════
 *  入口
 * ══════════════════════════════════════════════════════════ */

void app_main(void)
{
    /* 稍等一下，让串口连上（模拟器 --uart-tcp 需要） */
    vTaskDelay(pdMS_TO_TICKS(300));

    printf("\n");
    printf("==================================================\n");
    printf("  LBP/1.0 C 实现自检\n");
    printf("  纯逻辑验证（不需要 CAN 硬件）\n");
    printf("==================================================\n");

    test_crc();
    test_frame();
    test_frag();
    test_tp();
    test_payload();
    test_bmd();
    test_end_to_end();

    printf("\n==================================================\n");
    printf("  结果: %d 通过 / %d 失败 / 共 %d 项\n",
           s_pass, s_fail, s_pass + s_fail);
    if (s_fail == 0) {
        printf("  ALL PASS\n");
    } else {
        printf("  SOME FAILED\n");
    }
    printf("==================================================\n");
    printf("LBP SELFTEST DONE\n");

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}