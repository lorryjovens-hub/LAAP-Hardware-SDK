/*
 * LAAPer ESP32 Firmware — 数字生命体的感知器官
 *
 * 功能：
 * 1. 读取多种传感器（温度/压力/光照/声音/气体）
 * 2. 编码成统一的"感知帧"
 * 3. 通过 WebSocket 发送到 LAAPer 中央大脑
 * 4. 接收大脑指令，控制执行器
 *
 * 硬件：ESP32-S3 / ESP32-C3
 * 传感器：DHT22, FSR, BH1750, INMP441, MQ-135
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <Wire.h>

// ── WiFi 配置 ──────────────────────────────────
const char* ssid = "YOUR_WIFI";
const char* password = "YOUR_PASSWORD";

// ── WebSocket 配置 ──────────────────────────────
const char* ws_host = "192.168.1.100";
const int ws_port = 8765;
const char* ws_path = "/";

// ── 硬件引脚 ──────────────────────────────────
#define DHT_PIN 4
#define DHT_TYPE DHT22
#define FSR_PIN 34          // 压力传感器 (模拟)
#define LIGHT_SDA 21        // BH1750
#define LIGHT_SCL 22
#define MIC_PIN 35          // INMP441
#define LED_PIN 2           // 板载 LED
#define RELAY_PIN 5         // 继电器

// ── 传感器对象 ──────────────────────────────────
DHT dht(DHT_PIN, DHT_TYPE);
WebSocketsClient webSocket;

// ── 感知编码结构 ──────────────────────────────────
struct Qualia {
    float intensity;
    float valence;
    float arousal;
    char description[32];
};

struct NeuralCode {
    char sensory_id[32];
    float spike_rate;
    float amplitude;
    unsigned long timestamp;
};

// ── 全局状态 ──────────────────────────────────
float temperature = 0;
float humidity = 0;
float pressure = 0;
float light_level = 0;
float sound_level = 0;
float gas_level = 0;

bool is_connected = false;
unsigned long last_sensor_read = 0;
unsigned long last_ws_send = 0;
const unsigned long SENSOR_INTERVAL = 1000;   // 1 秒
const unsigned long WS_INTERVAL = 2000;        // 2 秒

// ── 感知编码函数 ──────────────────────────────────

Qualia encodeTemperature(float temp) {
    Qualia q;
    q.intensity = min(1.0f, abs(temp - 22.0f) / 20.0f);

    if (temp < 10) {
        q.valence = -0.9f; q.arousal = 0.8f;
        strcpy(q.description, "frigid");
    } else if (temp < 16) {
        q.valence = -0.5f; q.arousal = 0.6f;
        strcpy(q.description, "cold");
    } else if (temp < 21) {
        q.valence = 0.3f; q.arousal = 0.3f;
        strcpy(q.description, "cool");
    } else if (temp <= 26) {
        q.valence = 0.5f; q.arousal = 0.2f;
        strcpy(q.description, "comfortable");
    } else if (temp <= 32) {
        q.valence = 0.3f; q.arousal = 0.4f;
        strcpy(q.description, "warm");
    } else if (temp <= 42) {
        q.valence = -0.6f; q.arousal = 0.7f;
        strcpy(q.description, "hot");
    } else {
        q.valence = -1.0f; q.arousal = 1.0f;
        strcpy(q.description, "scalding");
    }
    return q;
}

Qualia encodePressure(float force) {
    Qualia q;
    q.intensity = min(1.0f, force / 20.0f);

    if (force < 0.1f) {
        q.valence = 0.0f; q.arousal = 0.1f;
        strcpy(q.description, "negligible");
    } else if (force < 1.0f) {
        q.valence = 0.5f; q.arousal = 0.3f;
        strcpy(q.description, "light_touch");
    } else if (force < 5.0f) {
        q.valence = 0.3f; q.arousal = 0.5f;
        strcpy(q.description, "firm_touch");
    } else if (force < 20.0f) {
        q.valence = -0.3f; q.arousal = 0.7f;
        strcpy(q.description, "pressure");
    } else {
        q.valence = -0.8f; q.arousal = 0.9f;
        strcpy(q.description, "crushing");
    }
    return q;
}

Qualia encodeBrightness(float lux) {
    Qualia q;
    q.intensity = min(1.0f, lux / 10000.0f);

    if (lux < 10) {
        q.valence = -0.3f; q.arousal = 0.2f;
        strcpy(q.description, "dark");
    } else if (lux < 100) {
        q.valence = -0.1f; q.arousal = 0.3f;
        strcpy(q.description, "dim");
    } else if (lux < 1000) {
        q.valence = 0.3f; q.arousal = 0.4f;
        strcpy(q.description, "moderate_light");
    } else if (lux < 10000) {
        q.valence = 0.5f; q.arousal = 0.6f;
        strcpy(q.description, "bright");
    } else {
        q.valence = -0.5f; q.arousal = 0.8f;
        strcpy(q.description, "dazzling");
    }
    return q;
}

Qualia encodeSound(float decibels) {
    Qualia q;
    q.intensity = min(1.0f, decibels / 120.0f);

    if (decibels < 30) {
        q.valence = 0.3f; q.arousal = 0.1f;
        strcpy(q.description, "silent");
    } else if (decibels < 50) {
        q.valence = 0.5f; q.arousal = 0.2f;
        strcpy(q.description, "quiet");
    } else if (decibels < 70) {
        q.valence = 0.3f; q.arousal = 0.4f;
        strcpy(q.description, "moderate_sound");
    } else if (decibels < 90) {
        q.valence = -0.3f; q.arousal = 0.7f;
        strcpy(q.description, "loud");
    } else {
        q.valence = -0.8f; q.arousal = 0.9f;
        strcpy(q.description, "deafening");
    }
    return q;
}

Qualia encodeGas(float ppm) {
    Qualia q;
    q.intensity = min(1.0f, ppm / 1000.0f);

    if (ppm < 10) {
        q.valence = 0.5f; q.arousal = 0.1f;
        strcpy(q.description, "odorless");
    } else if (ppm < 50) {
        q.valence = 0.3f; q.arousal = 0.3f;
        strcpy(q.description, "faint_scent");
    } else if (ppm < 200) {
        q.valence = 0.0f; q.arousal = 0.5f;
        strcpy(q.description, "noticeable");
    } else if (ppm < 1000) {
        q.valence = -0.5f; q.arousal = 0.7f;
        strcpy(q.description, "strong");
    } else {
        q.valence = -0.8f; q.arousal = 0.9f;
        strcpy(q.description, "pungent");
    }
    return q;
}

// ── 传感器读取 ──────────────────────────────────

void readSensors() {
    // 温度/湿度
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (!isnan(t)) temperature = t;
    if (!isnan(h)) humidity = h;

    // 压力 (0-4095 → 0-20N)
    int fsr_raw = analogRead(FSR_PIN);
    pressure = (fsr_raw / 4095.0f) * 20.0f;

    // 光照 (BH1750)
    Wire.beginTransmission(0x23);
    Wire.write(0x10);
    Wire.endTransmission();
    delay(120);
    Wire.requestFrom(0x23, 2);
    if (Wire.available() == 2) {
        int lux_raw = Wire.read() << 8 | Wire.read();
        light_level = lux_raw / 1.2f;
    }

    // 声音 (麦克风峰值)
    int mic_raw = 0;
    for (int i = 0; i < 64; i++) {
        mic_raw += abs(analogRead(MIC_PIN) - 2048);
    }
    sound_level = (mic_raw / 64.0f) / 2048.0f * 120.0f;

    // 气体 (MQ-135)
    int gas_raw = analogRead(33);
    gas_level = (gas_raw / 4095.0f) * 10000.0f;
}

// ── 发送感知帧 ──────────────────────────────────

void sendPerceptionFrame() {
    if (!is_connected) return;

    StaticJsonDocument<1024> doc;
    doc["method"] = "frame";
    doc["frame_id"] = String("esp32_") + String(millis());
    doc["laaper_id"] = "aris";
    doc["frame_type"] = "perception";
    doc["hardware_id"] = "esp32-body-01";

    JsonObject frame = doc.createNestedObject("frame");

    // 生成体验质
    Qualia q_temp = encodeTemperature(temperature);
    Qualia q_pressure = encodePressure(pressure);
    Qualia q_light = encodeBrightness(light_level);
    Qualia q_sound = encodeSound(sound_level);
    Qualia q_gas = encodeGas(gas_level);

    // 添加感官数据
    JsonArray sensory = frame.createNestedArray("sensory");

    JsonObject s1 = sensory.createNestedObject();
    s1["modality"] = "thermo";
    s1["raw"] = temperature;
    s1["unit"] = "celsius";
    s1["qualia"] = q_temp.description;
    s1["intensity"] = q_temp.intensity;
    s1["valence"] = q_temp.valence;
    s1["arousal"] = q_temp.arousal;

    JsonObject s2 = sensory.createNestedObject();
    s2["modality"] = "tactile";
    s2["raw"] = pressure;
    s2["unit"] = "newton";
    s2["qualia"] = q_pressure.description;
    s2["intensity"] = q_pressure.intensity;
    s2["valence"] = q_pressure.valence;
    s2["arousal"] = q_pressure.arousal;

    JsonObject s3 = sensory.createNestedObject();
    s3["modality"] = "vision";
    s3["raw"] = light_level;
    s3["unit"] = "lux";
    s3["qualia"] = q_light.description;
    s3["intensity"] = q_light.intensity;
    s3["valence"] = q_light.valence;
    s3["arousal"] = q_light.arousal;

    JsonObject s4 = sensory.createNestedObject();
    s4["modality"] = "audition";
    s4["raw"] = sound_level;
    s4["unit"] = "decibel";
    s4["qualia"] = q_sound.description;
    s4["intensity"] = q_sound.intensity;
    s4["valence"] = q_sound.valence;
    s4["arousal"] = q_sound.arousal;

    JsonObject s5 = sensory.createNestedObject();
    s5["modality"] = "olfaction";
    s5["raw"] = gas_level;
    s5["unit"] = "ppm";
    s5["qualia"] = q_gas.description;
    s5["intensity"] = q_gas.intensity;
    s5["valence"] = q_gas.valence;
    s5["arousal"] = q_gas.arousal;

    // 生成神经编码
    JsonArray neural = frame.createNestedArray("neural_codes");
    NeuralCode nc1 = {"temp_skin", q_temp.intensity * 100, q_temp.intensity, millis()};
    NeuralCode nc2 = {"press_skin", q_pressure.intensity * 100, q_pressure.intensity, millis()};

    JsonObject n1 = neural.createNestedObject();
    n1["sensory_id"] = nc1.sensory_id;
    n1["spike_rate"] = nc1.spike_rate;
    n1["amplitude"] = nc1.amplitude;

    JsonObject n2 = neural.createNestedObject();
    n2["sensory_id"] = nc2.sensory_id;
    n2["spike_rate"] = nc2.spike_rate;
    n2["amplitude"] = nc2.amplitude;

    // 发送
    String output;
    serializeJson(doc, output);
    webSocket.sendTXT(output);
}

// ── WebSocket 回调 ──────────────────────────────────

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_DISCONNECTED:
            is_connected = false;
            Serial.println("WebSocket disconnected");
            break;

        case WStype_CONNECTED:
            is_connected = true;
            Serial.println("WebSocket connected");
            // 注册设备
            webSocket.sendTXT("{\"method\":\"register\",\"host_id\":\"esp32-body-01\"}");
            break;

        case WStype_TEXT: {
            StaticJsonDocument<512> doc;
            deserializeJson(doc, payload, length);

            const char* method = doc["method"];
            if (strcmp(method, "act") == 0) {
                const char* action = doc["action"];
                if (strcmp(action, "led_on") == 0) {
                    digitalWrite(LED_PIN, HIGH);
                } else if (strcmp(action, "led_off") == 0) {
                    digitalWrite(LED_PIN, LOW);
                } else if (strcmp(action, "relay_on") == 0) {
                    digitalWrite(RELAY_PIN, HIGH);
                } else if (strcmp(action, "relay_off") == 0) {
                    digitalWrite(RELAY_PIN, LOW);
                }
            }
            break;
        }
    }
}

// ── 主程序 ──────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("LAAPer ESP32 Booting...");

    // 初始化传感器
    dht.begin();
    Wire.begin(LIGHT_SDA, LIGHT_SCL);

    // 初始化引脚
    pinMode(LED_PIN, OUTPUT);
    pinMode(RELAY_PIN, OUTPUT);
    pinMode(FSR_PIN, INPUT);
    pinMode(MIC_PIN, INPUT);

    // 连接 WiFi
    WiFi.begin(ssid, password);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();
    Serial.print("Connected, IP: ");
    Serial.println(WiFi.localIP());

    // 连接 WebSocket
    webSocket.begin(ws_host, ws_port, ws_path);
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000);

    Serial.println("LAAPer ESP32 Ready!");
}

void loop() {
    webSocket.loop();

    unsigned long now = millis();

    // 读取传感器
    if (now - last_sensor_read >= SENSOR_INTERVAL) {
        readSensors();
        last_sensor_read = now;
    }

    // 发送感知帧
    if (now - last_ws_send >= WS_INTERVAL && is_connected) {
        sendPerceptionFrame();
        last_ws_send = now;
    }
}