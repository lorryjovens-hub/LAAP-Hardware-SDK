/*
 * laap_protocol.c — LDP 编解码实现
 *
 * 只依赖 cJSON，不依赖 ESP-IDF。这让协议逻辑可以在 PC 上单独测试。
 */
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "cJSON.h"
#include "laap_protocol.h"

/* ══════════════ kind 映射 ══════════════ */

typedef struct {
    const char *str;
    laap_msg_kind_t kind;
} kind_map_t;

static const kind_map_t s_kinds[] = {
    {"hello",           LAAP_MSG_HELLO},
    {"hello_ack",       LAAP_MSG_HELLO_ACK},
    {"heartbeat",       LAAP_MSG_HEARTBEAT},
    {"percept",         LAAP_MSG_PERCEPT},
    {"state.report",    LAAP_MSG_STATE_REPORT},
    {"motion.move",     LAAP_MSG_MOTION_MOVE},
    {"motion.pose",     LAAP_MSG_MOTION_POSE},
    {"motion.stop",     LAAP_MSG_MOTION_STOP},
    {"dialogue.text",   LAAP_MSG_DIALOGUE_TEXT},
    {"dialogue.state",  LAAP_MSG_DIALOGUE_STATE},
    {"config",          LAAP_MSG_CONFIG},
    {NULL, LAAP_MSG_UNKNOWN},
};

laap_msg_kind_t laap_kind_from_str(const char *s)
{
    if (!s) return LAAP_MSG_UNKNOWN;
    for (int i = 0; s_kinds[i].str; i++) {
        if (strcmp(s, s_kinds[i].str) == 0) return s_kinds[i].kind;
    }
    return LAAP_MSG_UNKNOWN;
}

const char *laap_kind_to_str(laap_msg_kind_t k)
{
    for (int i = 0; s_kinds[i].str; i++) {
        if (s_kinds[i].kind == k) return s_kinds[i].str;
    }
    return "unknown";
}

/* ══════════════ 安全取字符串 ══════════════ */

static void copy_str(char *dst, size_t dst_len, const cJSON *item)
{
    if (!dst || dst_len == 0) return;
    dst[0] = 0;
    if (!item || !cJSON_IsString(item) || !item->valuestring) return;
    size_t n = strlen(item->valuestring);
    if (n >= dst_len) n = dst_len - 1;
    memcpy(dst, item->valuestring, n);
    dst[n] = 0;
}

static float get_num(const cJSON *obj, const char *key, float def)
{
    const cJSON *it = cJSON_GetObjectItem(obj, key);
    if (!it) return def;
    if (cJSON_IsNumber(it)) return (float)it->valuedouble;
    return def;
}

/* ══════════════ 解析 ══════════════ */

laap_err_t laap_proto_parse(const char *json, size_t len, laap_msg_t *out)
{
    if (!json || !out || len == 0) return LAAP_ERR_INVALID_ARG;

    memset(out, 0, sizeof(*out));

    /* 保证 null 结尾：调用方可能传非结尾片段 */
    char stackbuf[640];
    char *buf = stackbuf;
    bool heap = false;
    if (len >= sizeof(stackbuf)) {
        buf = malloc(len + 1);
        if (!buf) return LAAP_ERR_NO_MEM;
        heap = true;
    }
    memcpy(buf, json, len);
    buf[len] = 0;

    cJSON *root = cJSON_Parse(buf);
    if (heap) free(buf);
    if (!root) return LAAP_ERR_PARSE;

    /* kind */
    copy_str(out->kind_str, sizeof(out->kind_str),
             cJSON_GetObjectItem(root, "kind"));
    out->kind = laap_kind_from_str(out->kind_str);

    /* payload */
    const cJSON *p = cJSON_GetObjectItem(root, "payload");

    switch (out->kind) {
    case LAAP_MSG_MOTION_MOVE:
        if (p) {
            out->vx    = get_num(p, "vx", 0.0f);
            out->vy    = get_num(p, "vy", 0.0f);
            out->omega = get_num(p, "omega", 0.0f);
        }
        break;

    case LAAP_MSG_MOTION_POSE:
        if (p) copy_str(out->pose, sizeof(out->pose),
                        cJSON_GetObjectItem(p, "name"));
        break;

    case LAAP_MSG_DIALOGUE_TEXT:
        if (p) copy_str(out->text, sizeof(out->text),
                        cJSON_GetObjectItem(p, "text"));
        break;

    case LAAP_MSG_DIALOGUE_STATE:
        if (p) copy_str(out->state, sizeof(out->state),
                        cJSON_GetObjectItem(p, "state"));
        break;

    case LAAP_MSG_PERCEPT:
        if (p) {
            copy_str(out->sensor, sizeof(out->sensor),
                     cJSON_GetObjectItem(p, "sensor"));
            const cJSON *d = cJSON_GetObjectItem(p, "data");
            if (d) {
                char *s = cJSON_PrintUnformatted(d);
                if (s) {
                    size_t n = strlen(s);
                    if (n >= sizeof(out->data_json)) n = sizeof(out->data_json) - 1;
                    memcpy(out->data_json, s, n);
                    out->data_json[n] = 0;
                    free(s);
                }
            }
        }
        break;

    case LAAP_MSG_MOTION_STOP:
    case LAAP_MSG_HELLO_ACK:
    case LAAP_MSG_CONFIG:
    default:
        break;
    }

    cJSON_Delete(root);
    return LAAP_OK;
}

/* ══════════════ 构造辅助 ══════════════ */

static size_t finish(cJSON *root, char *out, size_t out_len)
{
    if (!out || out_len == 0) { cJSON_Delete(root); return 0; }
    char *s = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!s) return 0;
    size_t n = strlen(s);
    if (n + 1 > out_len) { free(s); return 0; }
    memcpy(out, s, n + 1);
    free(s);
    return n;
}

static const char *motion_kind_str(laap_motion_kind_t m)
{
    switch (m) {
    case LAAP_MOTION_PANTILT: return "pantilt";
    case LAAP_MOTION_DIFF:    return "diff";
    case LAAP_MOTION_LEGS:    return "legs";
    case LAAP_MOTION_BLINK:   return "blink";
    default:                  return "none";
    }
}

static void add_cap_array(cJSON *caps, const char *key,
                          uint32_t caps_mask, uint32_t cap, const char *name)
{
    if (!(caps_mask & cap)) return;
    cJSON *arr = cJSON_GetObjectItem(caps, key);
    if (!arr) arr = cJSON_AddArrayToObject(caps, key);
    cJSON_AddItemToArray(arr, cJSON_CreateString(name));
}

/* ══════════════ hello ══════════════ */

size_t laap_proto_build_hello(const char *device_id,
                              const char *name,
                              const char *kind,
                              uint32_t caps,
                              laap_motion_kind_t motion,
                              const char *const *poses,
                              size_t pose_count,
                              char *out, size_t out_len)
{
    if (!device_id || !out) return 0;

    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "kind", "hello");
    cJSON_AddStringToObject(r, "device_id", device_id);

    cJSON *p = cJSON_AddObjectToObject(r, "payload");
    cJSON_AddStringToObject(p, "device_id", device_id);
    cJSON_AddStringToObject(p, "name", name ? name : device_id);
    cJSON_AddStringToObject(p, "kind", kind ? kind : "generic");
    cJSON_AddStringToObject(p, "protocol", "ldp/1.0");

    cJSON *c = cJSON_AddObjectToObject(p, "capabilities");

    /* sensors */
    cJSON *sensors = cJSON_AddArrayToObject(c, "sensors");
    add_cap_array(c, "sensors", caps, LAAP_CAP_TOUCH,    "touch");
    add_cap_array(c, "sensors", caps, LAAP_CAP_IMU,      "imu");
    add_cap_array(c, "sensors", caps, LAAP_CAP_LIGHT,    "light");
    add_cap_array(c, "sensors", caps, LAAP_CAP_TEMP,     "temperature");
    add_cap_array(c, "sensors", caps, LAAP_CAP_PRESSURE, "pressure");
    add_cap_array(c, "sensors", caps, LAAP_CAP_DISTANCE, "distance");
    add_cap_array(c, "sensors", caps, LAAP_CAP_SEE,      "camera");
    add_cap_array(c, "sensors", caps, LAAP_CAP_HEAR,     "microphone");
    add_cap_array(c, "sensors", caps, LAAP_CAP_BATTERY,  "battery");
    (void)sensors;

    /* actuators */
    cJSON *acts = cJSON_AddArrayToObject(c, "actuators");
    if (caps & LAAP_CAP_MOTION)  cJSON_AddItemToArray(acts, cJSON_CreateString("motion"));
    if (caps & LAAP_CAP_DISPLAY) cJSON_AddItemToArray(acts, cJSON_CreateString("display"));
    if (caps & LAAP_CAP_SPEAK)   cJSON_AddItemToArray(acts, cJSON_CreateString("speak"));

    /* poses */
    if (poses && pose_count > 0) {
        cJSON *pa = cJSON_AddArrayToObject(c, "poses");
        for (size_t i = 0; i < pose_count; i++) {
            if (poses[i]) cJSON_AddItemToArray(pa, cJSON_CreateString(poses[i]));
        }
    }

    cJSON_AddStringToObject(c, "motion", motion_kind_str(motion));
    cJSON_AddBoolToObject(c, "dialogue", (caps & LAAP_CAP_SPEAK) != 0);
    cJSON_AddBoolToObject(c, "display",  (caps & LAAP_CAP_DISPLAY) != 0);

    return finish(r, out, out_len);
}

/* ══════════════ heartbeat ══════════════ */

size_t laap_proto_build_heartbeat(const char *device_id,
                                  int battery_pct,
                                  char *out, size_t out_len)
{
    if (!device_id || !out) return 0;
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "kind", "heartbeat");
    cJSON_AddStringToObject(r, "device_id", device_id);
    cJSON *p = cJSON_AddObjectToObject(r, "payload");
    if (battery_pct >= 0) {
        cJSON_AddNumberToObject(p, "battery", battery_pct);
    }
    cJSON_AddBoolToObject(p, "alive", true);
    return finish(r, out, out_len);
}

/* ══════════════ percept ══════════════ */

size_t laap_proto_build_percept(const char *device_id,
                                const char *sensor,
                                const char *data_json,
                                char *out, size_t out_len)
{
    if (!device_id || !sensor || !out) return 0;
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "kind", "percept");
    cJSON_AddStringToObject(r, "device_id", device_id);
    cJSON *p = cJSON_AddObjectToObject(r, "payload");
    cJSON_AddStringToObject(p, "sensor", sensor);

    /* data 可以是任意 JSON 片段；解析失败就当对象用 */
    cJSON *d = NULL;
    if (data_json && data_json[0]) {
        d = cJSON_Parse(data_json);
    }
    if (d) {
        cJSON_AddItemToObject(p, "data", d);
    } else {
        cJSON_AddItemToObject(p, "data", cJSON_CreateObject());
    }
    return finish(r, out, out_len);
}

/* ══════════════ state ══════════════ */

size_t laap_proto_build_state(const char *device_id,
                              const char *state_json,
                              char *out, size_t out_len)
{
    if (!device_id || !out) return 0;
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "kind", "state.report");
    cJSON_AddStringToObject(r, "device_id", device_id);

    cJSON *p = NULL;
    if (state_json && state_json[0]) p = cJSON_Parse(state_json);
    if (!p) p = cJSON_CreateObject();
    cJSON_AddItemToObject(r, "payload", p);

    return finish(r, out, out_len);
}