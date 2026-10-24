/*
 * bsp_board.h — bsp_base.c 与各 board.c 的内部契约
 *
 * ## 为什么单独一个头文件
 *
 * bsp.h 是给**应用**用的接口，不应让应用看到这些板级钩子。
 * 这个头文件只被 bsp_base.c 和 boards/*/board.c 包含。
 *
 * ## 弱符号机制
 *
 * bsp_base.c 为下面所有钩子提供弱默认实现。
 * 板子用强符号覆盖它真正具备的能力。
 * → 板子只实现自己有的东西，没有的自动降级。
 */
#pragma once

#include "bsp.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 板级信息（板子必须覆盖，否则返回兜底"未识别板子"）。
 *
 * 返回的 caps 决定 bsp_init() 会初始化哪些外设。
 */
const bsp_info_t *bsp_board_info(void);

/**
 * 板级通用初始化（可选覆盖）。
 *
 * 用于电源使能、扩展 IO 芯片复位、codec 上电等
 * 不属于具体外设的板级动作。在 bsp_init() 里最先调用。
 */
esp_err_t bsp_board_init(void);

/**
 * 板级周期任务（可选覆盖）。
 *
 * bsp_tick() 会调它。适合电池采样缓存、按键消抖状态机等
 * 不属于具体外设的周期工作。
 */
void bsp_board_tick(void);

#ifdef __cplusplus
}
#endif