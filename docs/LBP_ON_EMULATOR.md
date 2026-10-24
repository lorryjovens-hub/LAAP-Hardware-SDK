# LBP C 实现 — 真机工具链 + 模拟器验证（108/108）

## 结论
3254 行 LBP C 实现，经 ESP-IDF v5.4.4 真实工具链编译 + esp-emu 模拟器运行，
**108 项自检全部 PASS**。无硬件即可验证协议层。

## 验证环境
- 芯片：ESP32-S3（esp-emu 支持 C3/C5/C6/H2/P4/S3/S31）
- IDF：v5.4.4（乐鑫官方完整源码包，含子模块）
- 工具链：xtensa-esp-elf 14.2.0 + riscv32-esp-elf 14.2.0
- 模拟器：esp-emu 0.50.0（WSL Ubuntu-24.04）

## 踩过的环境坑（都有救法）
1. git clone 的 IDF 缺 mbedtls 等子模块，cmake configure 会自动 git submodule update
   从 GitHub 拉，55KB/s 要几小时 → 下乐鑫官方源码包 esp-idf-v5.4.4.zip（1.85GB，
   镜像 dl.espressif.cn 78MB/s，24 秒），含全部子模块。
2. IDF_SKIP_CHECK_SUBMODULES=1 禁用子模块检查（注意是复数 SUBMODULES）。
3. IDF_COMPONENT_MANAGER=0 禁用组件管理器（国内会卡 registry）。
4. 工具链用 IDF_GITHUB_ASSETS=dl.espressif.cn/github_assets 镜像（280× 提速）。
5. install.bat esp32s3 不装 riscv32-esp-elf-gdb，export 会硬失败 →
   `idf_tools.py install riscv32-esp-elf-gdb` 补上。

## 踩过的代码坑
1. lbp_master.h 用了 LBP_TOPO_MAX_CHILDREN（定义在 lbp_payload.h）没 include → 补 include。
2. lbp_reasm_t ≈4.1KB / lbp_tp_t ≈8.5KB（8 槽×1KB），放栈上直接把 app_main 栈踩爆：
   - 第一次：InstructionFetchError + Backtrace CORRUPTED（PC 变成垃圾值）
   - 第二次：FreeRTOS assert 'Uninitialized lock used'（锁结构被踩坏）
   → 修复：LBP_TP_MAX_PEERS 8→4；头文件加 size 警告；自检代码全部改 static；
     CONFIG_ESP_MAIN_TASK_STACK_SIZE=8192。
3. bsp 组件 CMakeLists 在 CONFIG_BSP_BOARD 未设置时直接 fatal → 改为 header-only
   降级注册，不再炸掉整个构建。

## 结果
结果: 108 通过 / 0 失败 / 共 108 项
- CRC-32：标准向量 0xCBF43926 ✓
- 帧编解码：往返/单bit检错/SOF/EOF/长度 ✓
- 分片重组：900B 分 25 片重组 ✓ 丢片检测 ✓ 原类型保留 ✓
- TP 分段：23B→4 段 / 341B→49 段 ✓ CAN ID 优先级 ✓ 环回 ✓
- 载荷：TOPO_ACK 3B / CMD 14B / TELEM 28B / REFLEX 7B / CLOCK 8B ✓
- BMD：318B/386B 字节对齐 ✓ 往返逐字节相同 ✓ 越界拒绝 ✓
- 端到端：BMD 318B → LBP 帧 341B → 49 个 CAN 帧 → 解回 ✓

## 复现
```
cd esp32-projects/tests/lbp_selftest
# Windows：I:\Espressif\build_lbp_selftest.ps1（build+merge+run 全流程）
# 模拟器：esp-emu --chip esp32s3 --firmware build/merged-binary.bin
#         --exit-on "LBP SELFTEST DONE" --timeout 180
```
