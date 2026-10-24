# LBP 自检固件
cmake_minimum_required(VERSION 3.16)

# 只引入 lbp 组件 —— 自检不依赖 bsp / laap_core
# （纯逻辑测试，不该被板级配置或 LDP 传输层牵连）
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../components/lbp")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(lbp_selftest)
