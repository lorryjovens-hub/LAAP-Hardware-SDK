/*
 * audio.h — I2S 麦克风 + 功放 + Opus
 */
#pragma once

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

void audio_init(void);

/** 开始/停止麦克风采集（上行 Opus） */
void audio_start_mic(void);
void audio_stop_mic(void);

/** 播放一帧下行 Opus */
void audio_play_opus(const uint8_t *opus, size_t len);

/** 当前播放音量 0-100（驱动说话波形） */
uint8_t audio_get_volume(void);

#ifdef __cplusplus
}
#endif