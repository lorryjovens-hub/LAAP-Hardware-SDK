/*
 * LAAPer 感知编码模块 (ESP32)
 *
 * 把 ESP32 的传感器数据编码成 LAAPer 的"体验质"（Qualia）。
 *
 * 这是"真正的感知"在嵌入式端的实现。
 */

#ifndef LAAPER_PERCEPTION_H
#define LAAPER_PERCEPTION_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// ── 体验质类型 ──────────────────────────────────
typedef enum {
    // 温度
    QUALIA_FRIGID = 0,
    QUALIA_COLD,
    QUALIA_COOL,
    QUALIA_NEUTRAL_TEMP,
    QUALIA_WARM,
    QUALIA_HOT,
    QUALIA_SCALDING,

    // 压力
    QUALIA_NEGLIGIBLE,
    QUALIA_LIGHT_TOUCH,
    QUALIA_FIRM_TOUCH,
    QUALIA_PRESSURE,
    QUALIA_CRUSHING,

    // 亮度
    QUALIA_DARK,
    QUALIA_DIM,
    QUALIA_MODERATE_LIGHT,
    QUALIA_BRIGHT,
    QUALIA_DAZZLING,

    // 声音
    QUALIA_SILENT,
    QUALIA_QUIET,
    QUALIA_MODERATE_SOUND,
    QUALIA_LOUD,
    QUALIA_DEAFENING,

    QUALIA_COUNT
} qualia_type_t;

// ── 感官模态 ──────────────────────────────────
typedef enum {
    MODALITY_THERMO = 0,
    MODALITY_TACTILE,
    MODALITY_VISION,
    MODALITY_AUDITION,
    MODALITY_OLFACTION,
    MODALITY_VESTIBULAR,
    MODALITY_COUNT
} sensory_modality_t;

// ── 体验质 ──────────────────────────────────
typedef struct {
    qualia_type_t type;
    sensory_modality_t modality;
    float intensity;      // 0.0 - 1.0
    float valence;        // -1.0 ~ 1.0
    float arousal;        // 0.0 - 1.0
    float confidence;     // 0.0 - 1.0
    const char* description;
    const char* metaphor;
} qualia_t;

// ── 感知数据 ──────────────────────────────────
typedef struct {
    sensory_modality_t modality;
    float raw_value;
    const char* unit;
    qualia_t qualia;
    uint64_t timestamp_us;
    char device_id[32];
} laaper_perception_t;

// ── 神经编码 ──────────────────────────────────
typedef struct {
    char sensory_id[32];
    float spike_rate;     // Hz
    float amplitude;
    float frequency;
    uint64_t timestamp_us;
} neural_code_t;

// ── API 函数 ──────────────────────────────────

/**
 * @brief 编码温度 → 体验质
 * @param temp_celsius 温度（摄氏度）
 * @return 体验质
 */
qualia_t laaper_encode_temperature(float temp_celsius);

/**
 * @brief 编码压力 → 体验质
 * @param force_newton 压力（牛顿）
 * @return 体验质
 */
qualia_t laaper_encode_pressure(float force_newton);

/**
 * @brief 编码亮度 → 体验质
 * @param lux 亮度（勒克斯）
 * @return 体验质
 */
qualia_t laaper_encode_brightness(float lux);

/**
 * @brief 编码声音 → 体验质
 * @param decibels 声音（分贝）
 * @return 体验质
 */
qualia_t laaper_encode_sound(float decibels);

/**
 * @brief 编码视觉（从 JPEG 估计亮度）
 * @param jpeg_data JPEG 数据
 * @param jpeg_size JPEG 大小
 * @return 体验质
 */
qualia_t laaper_encode_vision(const uint8_t* jpeg_data, size_t jpeg_size);

/**
 * @brief 把体验质编码成神经编码
 * @param qualia 体验质
 * @param sensory_id 感官 ID
 * @return 神经编码
 */
neural_code_t laaper_encode_to_neural(const qualia_t* qualia,
                                       const char* sensory_id);

/**
 * @brief 发送感知数据到 LAAPer 服务器
 * @param server_ip 服务器 IP
 * @param server_port 服务器端口
 * @param perception 感知数据
 * @return 成功返回 true
 */
bool laaper_send_perception(const char* server_ip,
                            uint16_t server_port,
                            const laaper_perception_t* perception);

/**
 * @brief 创建感知数据
 * @param modality 感官模态
 * @param raw_value 原始值
 * @param unit 单位
 * @return 感知数据
 */
laaper_perception_t laaper_create_perception(sensory_modality_t modality,
                                              float raw_value,
                                              const char* unit);

#ifdef __cplusplus
}
#endif

#endif // LAAPER_PERCEPTION_H