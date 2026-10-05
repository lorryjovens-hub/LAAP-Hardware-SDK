# LAAPer ESP32 烧录测试方案

基于乐鑫官方 `esp-webrtc-solution` 的 `local_jpeg_stream` 示例。

## 一、硬件准备

### 推荐开发板

| 板型 | 芯片 | 摄像头 | 价格 | 推荐度 |
|------|------|--------|------|--------|
| **ESP32-S3-Korvo-V2** | ESP32-S3 | OV2640/OV3660 | ¥150 | ⭐⭐⭐⭐⭐ |
| **ESP32-S3-EYE** | ESP32-S3 | OV2640 | ¥100 | ⭐⭐⭐⭐ |
| **M5Stack Unit Cam** | ESP32-S3 | OV2640 | ¥120 | ⭐⭐⭐⭐ |
| **ESP32-CAM** | ESP32 | OV2640 | ¥30 | ⭐⭐⭐ |

### 需要的设备

```
1. ESP32-S3 开发板（带摄像头）
2. USB-C 数据线
3. 电脑（Windows/Mac/Linux）
4. WiFi 网络（2.4GHz）
```

## 二、软件准备

### 1. 安装 ESP-IDF

```bash
# Windows（PowerShell）
cd D:\LAAP
git clone -b v5.4 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.ps1 esp32s3

# Mac/Linux
git clone -b v5.4 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32s3
```

### 2. 激活 ESP-IDF 环境

```bash
# Windows
. D:\LAAP\esp-idf\export.ps1

# Mac/Linux
source D:\LAAP/esp-idf/export.sh
```

### 3. 下载 ESP-WebRTC Solution

```bash
cd D:\LAAP
git clone --recursive https://github.com/espressif/esp-webrtc-solution.git
cd esp-webrtc-solution/solutions/local_jpeg_stream
```

## 三、配置 LAAPer 固件

### 1. 修改 WiFi 配置

编辑 `main/settings.h`：

```c
// WiFi 配置
#define WIFI_SSID       "你的WiFi名"
#define WIFI_PASSWORD   "你的WiFi密码"

// LAAPer 配置
#define LAAPER_DEVICE_ID    "esp32-body-01"
#define LAAPER_SERVER_IP    "192.168.1.100"  // LAAPer 服务器 IP
#define LAAPER_SERVER_PORT  8765

// 视频配置
#define VIDEO_WIDTH     1280
#define VIDEO_HEIGHT    720
#define VIDEO_FPS       12
#define VIDEO_SEND_RECV true  // 双向视频
```

### 2. 配置摄像头（硬件 JPEG）

```bash
idf.py menuconfig
```

路径：
```
Espressif Camera Sensors Configurations
  → Camera Sensor Configuration
    → Select and Set Camera Sensor
      → OV2640 (或你的摄像头型号)
    → Choose supported formats for DVP interface
      → [x] DVP 1280x720 12fps, JPEG
    → Select default output format
      → DVP 1280x720 12fps, JPEG
```

### 3. 集成 LAAPer 感知编码

修改 `main/app_main.c`，添加 LAAPer 感知编码：

```c
#include "laaper_perception.h"  // 我们要创建的模块

// 在视频帧回调中
void on_video_frame(camera_fb_t *fb) {
    // 发送 JPEG 到浏览器（原有的）
    webrtc_send_jpeg(fb->buf, fb->len);

    // 同时发送 LAAPer 感知数据
    laaper_perception_t perception = {
        .modality = "vision",
        .raw_value = fb->buf,
        .raw_size = fb->len,
        .timestamp = esp_timer_get_time() / 1000000.0,
    };

    // 编码成体验质
    qualia_t qualia = laaper_encode_vision(fb->buf, fb->len);
    perception.qualia = qualia;

    // 发送到 LAAPer 服务器
    laaper_send_perception(LAAPER_SERVER_IP, LAAPER_SERVER_PORT, &perception);
}
```

## 四、编译和烧录

### 1. 编译

```bash
cd esp-webrtc-solution/solutions/local_jpeg_stream

# 设置目标芯片
idf.py set-target esp32s3

# 编译
idf.py build
```

### 2. 烧录

```bash
# 查找串口
# Windows: 设备管理器 → 端口 (COM3, COM4...)
# Mac: ls /dev/tty.usb*
# Linux: ls /dev/ttyUSB*

# 烧录（替换 COM3 为你的串口）
idf.py -p COM3 flash monitor
```

### 3. 监控输出

```bash
idf.py monitor
```

预期输出：
```
I (500) wifi: connected to WiFi
I (1000) webrtc: Signaling started
I (1000) webrtc: Use browser to enter https://192.168.1.100/webrtc/test
I (1200) laaper: LAAPer perception stream started
```

## 五、测试验证

### 1. 浏览器测试

1. 打开 Chrome/Edge
2. 访问 `https://<设备IP>/webrtc/test`
3. 点击 **Connect Signaling**
4. 在串口输入 `cmd ring`
5. 浏览器点击 **Accept Call**
6. 看到实时视频流！

### 2. LAAPer 感知测试

```bash
# 在 LAAPer 服务器运行
cd D:\LAAP\laap-hardware
python test_av_stream.py
```

预期输出：
```
[1] 创建感知流
    添加 1 个流源:
      - ESP32 摄像头 (video)
[2] 模拟接收音视频帧
      感知: 明亮 (attention=medium)
      感知: 明亮 (attention=medium)
```

### 3. 完整链路测试

```bash
# 1. ESP32 烧录完成
# 2. LAAPer 服务器运行
python -c "
import sys; sys.path.insert(0, 'laaper')
from laaper.media.perception_stream import PerceptionStream

stream = PerceptionStream('aris')
stream.on_perception(lambda f: print(f'感知: {f.qualia}'))
await stream.add_video_source('esp32', 'wss://<设备IP>/webrtc')
await stream.start()
"
```

## 六、故障排查

### 问题 1：编译失败

```bash
# 清理并重新编译
idf.py fullclean
idf.py build
```

### 问题 2：WiFi 连接失败

```bash
# 在串口控制台输入
wifi 你的WiFi名 你的WiFi密码
```

### 问题 3：浏览器无法连接

1. 确认设备和电脑在同一 WiFi
2. Chrome 关闭 mDNS：
   - `chrome://flags/#enable-webrtc-hide-local-ips-with-mdns`
   - 设为 **Disabled**

### 问题 4：视频卡顿

降低分辨率：
```c
#define VIDEO_WIDTH     640
#define VIDEO_HEIGHT    480
#define VIDEO_FPS       10
```

## 七、下一步集成

烧录成功后：

1. **接入 LAAPer 感知系统** — 实时帧→体验质→意识流帧
2. **世界模型** — 从视频流中学习因果关系
3. **多设备汇聚** — 多个 ESP32 组成感知网络
4. **云端大脑** — ESP32 → 云电脑 → LAAPer 认知引擎

---

## 硬件采购建议

**淘宝/京东搜索：**
- "ESP32-S3 开发板 摄像头"
- "ESP32-S3-Korvo"
- "M5Stack Unit Cam"

**预算：¥100-200 即可开始**

**我推荐：ESP32-S3-Korvo-V2（¥150）**
- 官方支持最好
- OV2640/OV3660 摄像头
- 麦克风 + 扬声器
- 丰富的传感器接口