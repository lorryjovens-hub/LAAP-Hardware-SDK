/*
 * LAAPer 感知编码模块实现 (ESP32)
 *
 * 把物理量映射成"体验质"，让 ESP32 成为 LAAPer 的感知器官。
 */

#include "laaper_perception.h"
#include <string.h>
#include <math.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <esp_log.h>

static const char* TAG = "laaper_perception";

// ── 体验质描述表 ──────────────────────────────────

static const char* qualia_descriptions[QUALIA_COUNT] = {
    // 温度
    "酷寒", "冷", "凉爽", "舒适", "温暖", "热", "滚烫",
    // 压力
    "几乎无感", "轻触", "实按", "压迫", "挤压",
    // 亮度
    "黑暗", "昏暗", "适中", "明亮", "刺眼",
    // 声音
    "寂静", "安静", "适中", "嘈杂", "震耳",
};

static const char* qualia_metaphors[QUALIA_COUNT] = {
    // 温度
    "像被冰水浇透", "像冬天的风", "像秋天的清晨",
    "像被温暖的阳光轻抚", "像泡在温水里", "像被太阳直晒", "像被火烤",
    // 压力
    "像微风拂过", "像被羽毛扫过", "像被手掌按住",
    "像被石头压住", "像被重物碾压",
    // 亮度
    "像被蒙上眼睛", "像黄昏", "像白天的室内", "像晴天", "像直视太阳",
    // 声音
    "像深夜的房间", "像图书馆", "像正常谈话", "像繁忙的街道", "像在工厂里",
};

// ── 编码函数 ──────────────────────────────────

qualia_t laaper_encode_temperature(float temp_celsius) {
    qualia_t q;
    q.modality = MODALITY_THERMO;
    q.intensity = fminf(1.0f, fabsf(temp_celsius - 22.0f) / 20.0f);
    q.confidence = 0.95f;

    if (temp_celsius < 10.0f) {
        q.type = QUALIA_FRIGID;
        q.valence = -0.9f;
        q.arousal = 0.8f;
    } else if (temp_celsius < 16.0f) {
        q.type = QUALIA_COLD;
        q.valence = -0.5f;
        q.arousal = 0.6f;
    } else if (temp_celsius < 21.0f) {
        q.type = QUALIA_COOL;
        q.valence = 0.3f;
        q.arousal = 0.3f;
    } else if (temp_celsius <= 26.0f) {
        q.type = QUALIA_NEUTRAL_TEMP;
        q.valence = 0.5f;
        q.arousal = 0.2f;
    } else if (temp_celsius <= 32.0f) {
        q.type = QUALIA_WARM;
        q.valence = 0.3f;
        q.arousal = 0.4f;
    } else if (temp_celsius <= 42.0f) {
        q.type = QUALIA_HOT;
        q.valence = -0.6f;
        q.arousal = 0.7f;
    } else {
        q.type = QUALIA_SCALDING;
        q.valence = -1.0f;
        q.arousal = 1.0f;
    }

    q.description = qualia_descriptions[q.type];
    q.metaphor = qualia_metaphors[q.type];
    return q;
}

qualia_t laaper_encode_pressure(float force_newton) {
    qualia_t q;
    q.modality = MODALITY_TACTILE;
    q.intensity = fminf(1.0f, force_newton / 20.0f);
    q.confidence = 0.92f;

    if (force_newton < 0.1f) {
        q.type = QUALIA_NEGLIGIBLE;
        q.valence = 0.0f;
        q.arousal = 0.1f;
    } else if (force_newton < 1.0f) {
        q.type = QUALIA_LIGHT_TOUCH;
        q.valence = 0.5f;
        q.arousal = 0.3f;
    } else if (force_newton < 5.0f) {
        q.type = QUALIA_FIRM_TOUCH;
        q.valence = 0.3f;
        q.arousal = 0.5f;
    } else if (force_newton < 20.0f) {
        q.type = QUALIA_PRESSURE;
        q.valence = -0.3f;
        q.arousal = 0.7f;
    } else {
        q.type = QUALIA_CRUSHING;
        q.valence = -0.8f;
        q.arousal = 0.9f;
    }

    q.description = qualia_descriptions[q.type];
    q.metaphor = qualia_metaphors[q.type];
    return q;
}

qualia_t laaper_encode_brightness(float lux) {
    qualia_t q;
    q.modality = MODALITY_VISION;
    q.intensity = fminf(1.0f, lux / 10000.0f);
    q.confidence = 0.88f;

    if (lux < 10.0f) {
        q.type = QUALIA_DARK;
        q.valence = -0.3f;
        q.arousal = 0.2f;
    } else if (lux < 100.0f) {
        q.type = QUALIA_DIM;
        q.valence = -0.1f;
        q.arousal = 0.3f;
    } else if (lux < 1000.0f) {
        q.type = QUALIA_MODERATE_LIGHT;
        q.valence = 0.3f;
        q.arousal = 0.4f;
    } else if (lux < 10000.0f) {
        q.type = QUALIA_BRIGHT;
        q.valence = 0.5f;
        q.arousal = 0.6f;
    } else {
        q.type = QUALIA_DAZZLING;
        q.valence = -0.5f;
        q.arousal = 0.8f;
    }

    q.description = qualia_descriptions[q.type];
    q.metaphor = qualia_metaphors[q.type];
    return q;
}

qualia_t laaper_encode_sound(float decibels) {
    qualia_t q;
    q.modality = MODALITY_AUDITION;
    q.intensity = fminf(1.0f, decibels / 120.0f);
    q.confidence = 0.85f;

    if (decibels < 30.0f) {
        q.type = QUALIA_SILENT;
        q.valence = 0.3f;
        q.arousal = 0.1f;
    } else if (decibels < 50.0f) {
        q.type = QUALIA_QUIET;
        q.valence = 0.5f;
        q.arousal = 0.2f;
    } else if (decibels < 70.0f) {
        q.type = QUALIA_MODERATE_SOUND;
        q.valence = 0.3f;
        q.arousal = 0.4f;
    } else if (decibels < 90.0f) {
        q.type = QUALIA_LOUD;
        q.valence = -0.3f;
        q.arousal = 0.7f;
    } else {
        q.type = QUALIA_DEAFENING;
        q.valence = -0.8f;
        q.arousal = 0.9f;
    }

    q.description = qualia_descriptions[q.type];
    q.metaphor = qualia_metaphors[q.type];
    return q;
}

qualia_t laaper_encode_vision(const uint8_t* jpeg_data, size_t jpeg_size) {
    // 简化：从 JPEG 大小估计亮度
    // 实际应该解析 JPEG 像素
    float estimated_lux = 500.0f;  // 默认值

    if (jpeg_size > 50000) {
        estimated_lux = 2000.0f;  // 大帧可能是复杂/明亮场景
    } else if (jpeg_size < 10000) {
        estimated_lux = 100.0f;   // 小帧可能是暗场景
    }

    return laaper_encode_brightness(estimated_lux);
}

neural_code_t laaper_encode_to_neural(const qualia_t* qualia,
                                       const char* sensory_id) {
    neural_code_t nc;
    strncpy(nc.sensory_id, sensory_id, sizeof(nc.sensory_id) - 1);
    nc.spike_rate = qualia->intensity * 100.0f;
    nc.amplitude = qualia->intensity;
    nc.frequency = nc.spike_rate / 10.0f;
    nc.timestamp_us = 0;  // 调用时设置
    return nc;
}

laaper_perception_t laaper_create_perception(sensory_modality_t modality,
                                              float raw_value,
                                              const char* unit) {
    laaper_perception_t p;
    memset(&p, 0, sizeof(p));
    p.modality = modality;
    p.raw_value = raw_value;
    p.unit = unit;
    p.timestamp_us = 0;  // 调用时设置
    return p;
}

bool laaper_send_perception(const char* server_ip,
                            uint16_t server_port,
                            const laaper_perception_t* perception) {
    // 创建 UDP socket
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        ESP_LOGE(TAG, "Failed to create socket");
        return false;
    }

    // 目标地址
    struct sockaddr_in server_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(server_port),
    };
    inet_pton(AF_INET, server_ip, &server_addr.sin_addr);

    // 构建 JSON 消息
    char json_buffer[512];
    snprintf(json_buffer, sizeof(json_buffer),
        "{\"method\":\"perception\","
        "\"device_id\":\"%s\","
        "\"modality\":\"%d\","
        "\"value\":%.2f,"
        "\"qualia_type\":\"%d\","
        "\"qualia_desc\":\"%s\","
        "\"intensity\":%.3f,"
        "\"valence\":%.3f,"
        "\"arousal\":%.3f,"
        "\"timestamp\":%llu}",
        perception->device_id,
        perception->modality,
        perception->raw_value,
        perception->qualia.type,
        perception->qualia.description,
        perception->qualia.intensity,
        perception->qualia.valence,
        perception->qualia.arousal,
        perception->timestamp_us);

    // 发送
    ssize_t sent = sendto(sock, json_buffer, strlen(json_buffer), 0,
                          (struct sockaddr*)&server_addr, sizeof(server_addr));

    close(sock);

    if (sent < 0) {
        ESP_LOGE(TAG, "Failed to send perception");
        return false;
    }

    ESP_LOGI(TAG, "Perception sent: %s", perception->qualia.description);
    return true;
}