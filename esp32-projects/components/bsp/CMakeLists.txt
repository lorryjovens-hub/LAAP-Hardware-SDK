# BSP 组件 — 按 Kconfig 选择编译哪块板子
#
# 关键设计：只编译选中的 board.c，其余板子代码不进二进制。
# 应用代码依赖统一的 bsp.h，不依赖任何具体板子。

set(BOARD_DIR "boards/${CONFIG_BSP_BOARD}")

if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/${BOARD_DIR}/board.c")
    message(FATAL_ERROR
        "BSP: 找不到板子实现 ${BOARD_DIR}/board.c\n"
        "请检查 components/bsp/boards/ 下的目录名与 Kconfig 的 CONFIG_BSP_BOARD 是否一致。")
endif()

idf_component_register(
    SRCS
        "bsp_base.c"
        "bsp_common.c"
        "${BOARD_DIR}/board.c"
    INCLUDE_DIRS
        "include"
    PRIV_INCLUDE_DIRS
        "${BOARD_DIR}"
    REQUIRES
        driver
        esp_lcd
        esp_lvgl_port
        lvgl
        esp_timer
        esp_adc
)

# 打印选中的板子，构建时一眼看到
message(STATUS "LAAP BSP: board = ${CONFIG_BSP_BOARD}")
