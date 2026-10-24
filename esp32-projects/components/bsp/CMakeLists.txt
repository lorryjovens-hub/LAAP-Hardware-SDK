# BSP component -- compile only the selected board
#
# Design: only the chosen board.c goes into the binary.
# App code depends on the unified bsp.h, never on a specific board.
#
# NOTE: messages kept ASCII on purpose -- CMake console codepage on Windows
# is not UTF-8, so Chinese text in message() shows up as mojibake and makes
# real errors hard to read.

# --- Case 1: no board configured (e.g. a project that does not use BSP) ---
# Register a header-only component so any component that declares
# REQUIRES bsp still resolves, instead of failing the whole configure step.
if(NOT CONFIG_BSP_BOARD)
    message(STATUS "LAAP BSP: CONFIG_BSP_BOARD not set -> BSP disabled (headers only)")
    idf_component_register(INCLUDE_DIRS "include")
    return()
endif()

set(BOARD_DIR "boards/${CONFIG_BSP_BOARD}")

# --- Case 2: board selected but no implementation ---
if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/${BOARD_DIR}/board.c")
    message(FATAL_ERROR
        "BSP: board implementation not found: ${BOARD_DIR}/board.c . "
        "Check that components/bsp/boards/<name>/ matches CONFIG_BSP_BOARD "
        "(currently '${CONFIG_BSP_BOARD}'), or run 'idf.py menuconfig' and pick a board.")
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

message(STATUS "LAAP BSP: board = ${CONFIG_BSP_BOARD}")
