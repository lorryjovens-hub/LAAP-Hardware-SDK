/*
 * touch.h — TTP223 触摸
 */
#pragma once

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*touch_cb_t)(bool pressed);

void touch_init(touch_cb_t cb);
void touch_poll(void);

#ifdef __cplusplus
}
#endif