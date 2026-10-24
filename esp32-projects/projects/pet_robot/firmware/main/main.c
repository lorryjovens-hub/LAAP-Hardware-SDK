/*
 * main.c — LAAP 桌面宠物
 *
 * 链路：
 *    小智硬件/手机/电脑 ──LDP over WS──▶ 本机
 *                                        ├─ motion.move    → 云台转
 *                                        ├─ motion.pose    → 命名姿态
 *                                        ├─ dialogue.state → 表情切换
 *                                        ├─ dialogue.text  → 字幕 + 播报
 *                                        └─ percept(touch) → 上报被摸
 *
 * 设计要点：
 *   · 主循环 50Hz：驱动 display_update + motion_tick + touch_poll
 *   · WS 收到消息只入队，动作在主循环里执行（避免并发写外设）
 *   · 触摸是最高优先级的"感知"——被摸立刻开心
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "esp_websocket_client.h"
#include "cJSON.h"

#include "network.h"
#include "display.h"
#include "motion.h"
#include "touch.h"
#include "audio.h"

#define TAG "pet"

/* ── LDP 消息类型（与 docs/LDP_PROTOCOL.md 对齐）── */
#define KIND_HELLO          "hello"
#define KIND_HELLO_ACK      "hello_ack"
#define KIND_HEARTBEAT      "heartbeat"
#define KIND_PERCEPT        "percept"
#define KIND_MOTION_MOVE    "motion.move"
#define KIND_MOTION_POSE    "motion.pose"
#define KIND_MOTION_STOP    "motion.stop"
#define KIND_DIALOGUE_TEXT  "dialogue.text"
#define KIND_DIALOGUE_STATE "dialogue.state"

#define DEVICE_ID   "pet-01"
#define DEVICE_KIND "pet"

#define CTRL_HZ     50
#define CTRL_MS     (1000 / CTRL_HZ)

static esp_websocket_client_handle_t s_ws = NULL;
static QueueHandle_t s_msg_q = NULL;

/* 空闲计时（长时间无交互 → 打瞌睡） */
static int64_t s_last_interact_ms = 0;
#define SLEEP_AFTER_MS  120000      /* 2 分钟 */

/* ─────────────────── 上行发送 ─────────────────── */

static void ws_send_json(cJSON *root)
{
    if (!s_ws || !esp_websocket_client_is_connected(s_ws)) {
        cJSON_Delete(root);
        return;
    }
    char *s = cJSON_PrintUnformatted(root);
    if (s) {
        esp_websocket_client_send_text(s_ws, s, strlen(s), pdMS_TO_TICKS(200));
        free(s);
    }
    cJSON_Delete(root);
}

static void send_hello(void)
{
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "kind", KIND_HELLO);
    cJSON_AddStringToObject(r, "device_id", DEVICE_ID);
    cJSON *p = cJSON_AddObjectToObject(r, "payload");
    cJSON_AddStringToObject(p, "device_id", DEVICE_ID);
    cJSON_AddStringToObject(p, "name", "LAAP 桌面宠物");
    cJSON_AddStringToObject(p, "kind", DEVICE_KIND);
    cJSON_AddStringToObject(p, "protocol", "ldp/1.0");

    cJSON *caps = cJSON_AddObjectToObject(p, "capabilities");
    cJSON *sensors = cJSON_AddArrayToObject(caps, "sensors");
    const char *sn[] = {"imu", "touch", "light", "dialogue"};
    for (int i = 0; i < 4; i++) cJSON_AddItemToArray(sensors, cJSON_CreateString(sn[i]));
    cJSON *acts = cJSON_AddArrayToObject(caps, "actuators");
    cJSON_AddItemToArray(acts, cJSON_CreateString("motion"));
    cJSON_AddItemToArray(acts, cJSON_CreateString("display"));
    cJSON_AddItemToArray(acts, cJSON_CreateString("speak"));
    cJSON *poses = cJSON_AddArrayToObject(caps, "poses");
    const char *ps[] = {"home", "look_up", "look_down", "think", "sleep", "nod"};
    for (int i = 0; i < 6; i++) cJSON_AddItemToArray(poses, cJSON_CreateString(ps[i]));
    cJSON_AddStringToObject(caps, "motion", "pantilt");
    cJSON_AddBoolToObject(caps, "dialogue", true);
    cJSON_AddBoolToObject(caps, "display", true);

    ws_send_json(r);
    ESP_LOGI(TAG, "已注册 %s", DEVICE_ID);
}

static void send_percept(const char *sensor, cJSON *data)
{
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "kind", KIND_PERCEPT);
    cJSON_AddStringToObject(r, "device_id", DEVICE_ID);
    cJSON *p = cJSON_AddObjectToObject(r, "payload");
    cJSON_AddStringToObject(p, "sensor", sensor);
    cJSON_AddItemToObject(p, "data", data);
    ws_send_json(r);
}

/** 供 audio.c 上行发二进制（音频） */
void pet_send_bin(const uint8_t *data, size_t len)
{
    if (!s_ws || !esp_websocket_client_is_connected(s_ws)) return;
    esp_websocket_client_send_bin(s_ws, (const char *)data, len,
                                  pdMS_TO_TICKS(100));
}

/* ─────────────────── WS 事件 ─────────────────── */

static void ws_event_handler(void *arg, esp_event_base_t base,
                             int32_t event_id, void *event_data)
{
    esp_websocket_event_data_t *d = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "已连接 LAAP");
        send_hello();
        display_set_status("已连接");
        display_set_expression(EXPR_IDLE);
        audio_start_mic();
        break;

    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "连接断开");
        display_set_status("连接中…");
        display_set_expression(EXPR_THINKING);
        audio_stop_mic();
        break;

    case WEBSOCKET_EVENT_DATA:
        /* 文本 = LDP JSON；二进制 = 音频 */
        if (d->op_code == 0x01 && d->data_len > 0) {
            char *buf = malloc(d->data_len + 1);
            if (!buf) break;
            memcpy(buf, d->data_ptr, d->data_len);
            buf[d->data_len] = 0;
            if (xQueueSend(s_msg_q, &buf, 0) != pdTRUE) {
                free(buf);   /* 队列满就丢，主循环会跟上 */
            }
        } else if (d->op_code == 0x02) {
            audio_play_opus((const uint8_t *)d->data_ptr, d->data_len);
            display_set_expression(EXPR_SPEAKING);
        }
        break;

    default:
        break;
    }
}

/* ─────────────────── 消息处理 ─────────────────── */

static void handle_message(const char *json)
{
    cJSON *root = cJSON_Parse(json);
    if (!root) return;

    cJSON *jk = cJSON_GetObjectItem(root, "kind");
    cJSON *jp = cJSON_GetObjectItem(root, "payload");
    const char *kind = jk ? jk->valuestring : "";
    s_last_interact_ms = esp_timer_get_time() / 1000;

    if (strcmp(kind, KIND_MOTION_MOVE) == 0 && jp) {
        float vx = cJSON_GetObjectItem(jp, "vx") ?
                   (float)cJSON_GetObjectItem(jp, "vx")->valuedouble : 0;
        float omega = cJSON_GetObjectItem(jp, "omega") ?
                      (float)cJSON_GetObjectItem(jp, "omega")->valuedouble : 0;
        /* 宠物没有底盘：把移动指令转成「看向那个方向」 */
        if (vx != 0 || omega != 0) {
            motion_look_delta(omega * 0.5f, -vx * 0.1f);
            display_set_gaze(omega > 0 ? 1.0f : (omega < 0 ? -1.0f : 0),
                             vx > 0 ? -0.5f : 0.5f);
            display_set_expression(EXPR_LISTENING);
        }

    } else if (strcmp(kind, KIND_MOTION_POSE) == 0 && jp) {
        cJSON *jn = cJSON_GetObjectItem(jp, "name");
        if (jn) {
            const char *name = jn->valuestring;
            motion_pose(name);
            /* 姿态 → 表情联动 */
            if (strcmp(name, "look_up") == 0)       display_set_expression(EXPR_LISTENING);
            else if (strcmp(name, "think") == 0)    display_set_expression(EXPR_THINKING);
            else if (strcmp(name, "sleep") == 0)    display_set_expression(EXPR_SLEEP);
            else if (strcmp(name, "nod") == 0)      display_set_expression(EXPR_HAPPY);
            else                                    display_set_expression(EXPR_IDLE);
        }

    } else if (strcmp(kind, KIND_MOTION_STOP) == 0) {
        /* 急停：立即回中 + 停止所有动作 */
        motion_look_at(0, 0);
        display_set_expression(EXPR_IDLE);
        ESP_LOGI(TAG, "急停");

    } else if (strcmp(kind, KIND_DIALOGUE_STATE) == 0 && jp) {
        cJSON *js = cJSON_GetObjectItem(jp, "state");
        if (js) {
            const char *st = js->valuestring;
            if (strcmp(st, "listening") == 0)      display_set_expression(EXPR_LISTENING);
            else if (strcmp(st, "thinking") == 0)  display_set_expression(EXPR_THINKING);
            else if (strcmp(st, "speaking") == 0)  display_set_expression(EXPR_SPEAKING);
            else                                   display_set_expression(EXPR_IDLE);
        }

    } else if (strcmp(kind, KIND_DIALOGUE_TEXT) == 0 && jp) {
        cJSON *jt = cJSON_GetObjectItem(jp, "text");
        if (jt) {
            display_set_subtitle(jt->valuestring);
            display_set_expression(EXPR_SPEAKING);
        }

    } else if (strcmp(kind, KIND_HELLO_ACK) == 0) {
        display_set_status("LAAP 已就绪");

    } else {
        ESP_LOGD(TAG, "未知 kind: %s", kind);
    }

    cJSON_Delete(root);
}

/* ─────────────────── 触摸：被摸头的反应 ─────────────────── */

static void on_touch(bool pressed)
{
    if (!pressed) return;
    s_last_interact_ms = esp_timer_get_time() / 1000;

    /* 被摸 → 开心 + 抬头看 + 上报 */
    display_set_expression(EXPR_HAPPY);
    motion_look_at(0, 18);

    cJSON *data = cJSON_CreateObject();
    cJSON_AddStringToObject(data, "zone", "head");
    cJSON_AddBoolToObject(data, "pressed", true);
    send_percept("touch", data);

    /* 1.2 秒后恢复正常 */
    vTaskDelay(pdMS_TO_TICKS(1200));
    if (display_get_expression() == EXPR_HAPPY) {
        display_set_expression(EXPR_IDLE);
    }
}

/* ─────────────────── 主循环 ─────────────────── */

static void control_loop(void *arg)
{
    char *msg = NULL;
    int64_t last_hb = 0;
    uint8_t vol_phase = 0;

    s_last_interact_ms = esp_timer_get_time() / 1000;

    while (1) {
        /* 1. 处理 WS 消息（非阻塞） */
        if (xQueueReceive(s_msg_q, &msg, 0) == pdTRUE) {
            handle_message(msg);
            free(msg);
        }

        /* 2. 外设刷新 */
        display_update(CTRL_MS);
        motion_tick(CTRL_MS);
        touch_poll();

        /* 3. 说话波形随音量起伏（示意：真实实现从 I2S 播放回调取 RMS） */
        if (display_get_expression() == EXPR_SPEAKING) {
            vol_phase += 7;
            display_set_volume(30 + (vol_phase % 60));
        }

        /* 4. 心跳（每 25s） */
        int64_t now = esp_timer_get_time() / 1000;
        if (now - last_hb > 25000) {
            last_hb = now;
            cJSON *r = cJSON_CreateObject();
            cJSON_AddStringToObject(r, "kind", KIND_HEARTBEAT);
            cJSON_AddStringToObject(r, "device_id", DEVICE_ID);
            cJSON *p = cJSON_AddObjectToObject(r, "payload");
            cJSON_AddNumberToObject(p, "ts", (double)now / 1000.0);
            ws_send_json(r);
        }

        /* 5. 长时间无交互 → 打瞌睡 */
        if (now - s_last_interact_ms > SLEEP_AFTER_MS) {
            if (display_get_expression() != EXPR_SLEEP) {
                display_set_expression(EXPR_SLEEP);
                motion_pose("sleep");
            }
        }

        vTaskDelay(pdMS_TO_TICKS(CTRL_MS));
    }
}

/* ─────────────────── app_main ─────────────────── */

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());

    s_msg_q = xQueueCreate(8, sizeof(char *));
    configASSERT(s_msg_q);

    display_init();
    motion_init();
    audio_init();
    touch_init(on_touch);

    display_set_status("连接中…");
    display_set_expression(EXPR_THINKING);

    network_wifi_init();

    esp_websocket_client_config_t cfg = {
        .host = CONFIG_PET_WS_HOST,
        .port = CONFIG_PET_WS_PORT,
        .path = "/",
        .transport = WEBSOCKET_TRANSPORT_OVER_TCP,
        .reconnect_timeout_ms = 5000,
        .network_timeout_ms = 10000,
        .buffer_size = 4096,
    };
    s_ws = esp_websocket_client_init(&cfg);
    esp_websocket_register_events(s_ws, WEBSOCKET_EVENT_ANY,
                                  ws_event_handler, NULL);
    esp_websocket_client_start(s_ws);

    xTaskCreatePinnedToCore(control_loop, "ctrl", 8192, NULL, 6, NULL, 1);

    ESP_LOGI(TAG, "LAAP 桌面宠物已启动");
}