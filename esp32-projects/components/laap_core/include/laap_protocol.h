/*
 * laap_protocol.h — LDP 协议编解码（无传输依赖，可单独测试）
 *
 * 设计原则：协议层不认识 WebSocket，只认识字符串 → 结构。
 * 这样在电脑上也能编译测试，不依赖 ESP-IDF。
 */
#pragma once

#include <stddef.h>
#include <stdbool.h>
#include "laap_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/** kind 字符串 → 枚举 */
laap_msg_kind_t laap_kind_from_str(const char *s);

/** 枚举 → kind 字符串 */
const char *laap_kind_to_str(laap_msg_kind_t k);

/**
 * 解析一行 LDP JSON 到 laap_msg_t。
 * @return LAAP_OK / LAAP_ERR_PARSE
 */
laap_err_t laap_proto_parse(const char *json, size_t len, laap_msg_t *out);

/**
 * 构造 hello（注册）消息。
 * @param caps         能力位掩码（LAAP_CAP_*）
 * @param motion       运动方式
 * @param poses        姿态名数组（可为 NULL）
 * @param pose_count   姿态数量
 * @param out          输出缓冲
 * @param out_len      缓冲长度
 * @return 实际写入长度（不含结尾 0），0 表示失败
 */
size_t laap_proto_build_hello(const char *device_id,
                              const char *name,
                              const char *kind,
                              uint32_t caps,
                              laap_motion_kind_t motion,
                              const char *const *poses,
                              size_t pose_count,
                              char *out, size_t out_len);

/** 构造心跳 */
size_t laap_proto_build_heartbeat(const char *device_id,
                                  int battery_pct,
                                  char *out, size_t out_len);

/**
 * 构造感知上报。
 * @param data_json  感知数据 JSON 片段，如 "{\"zone\":\"head\"}"（可为 NULL）
 */
size_t laap_proto_build_percept(const char *device_id,
                                const char *sensor,
                                const char *data_json,
                                char *out, size_t out_len);

/**
 * 构造状态上报。
 * @param state_json 状态 JSON 片段
 */
size_t laap_proto_build_state(const char *device_id,
                              const char *state_json,
                              char *out, size_t out_len);

#ifdef __cplusplus
}
#endif