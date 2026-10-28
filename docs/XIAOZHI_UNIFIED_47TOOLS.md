# 小智硬件统一服务 · 49 工具（全部独立命名）

一台小智硬件同时拥有两套能力，互不干扰：

生产版 36 个  ← xiaozhi_mcp_server.py
  ask_aris / tell_hana / check_reply / laap_status / recall / remember
  brief / project / make_website / task / dev_task / home / companion / sensing
  game_start / game_talk / game_state
  kemo_music / kemo_music_status / kemo_play
  pc_write / pc_run / pc_open
  pc_fs / pc_apps / pc_proc / pc_edit / pc_download / pc_backups
  pc_see / pc_input / pc_ui / browser / pc_notify

LAAP-Agent-Kit 13 个  ← 电脑控制 + 浏览器视觉
  voice_command / computer_task
  pc_scroll / pc_click / pc_type / pc_key / pc_hotkey
  pc_look / pc_focus / pc_undo / pc_history

## 冲突处理：全部改名去冲突

pc_status / pc_windows 两边都有且语义不同，改名彻底隔离：

  pc_status  → laap_pc_status   (LAAP 服务健康)     → kit_pc_status   (本机状态)
  pc_windows → laap_pc_windows  (经 LAAP 查窗口)   → kit_pc_windows  (本机窗口)

实测隔离有效：旧名 pc_status 调用会返回「工具 pc_status 未注册」。

## 用法

    python xiaozhi_service.py config --token <wss url 或裸 JWT>
    python xiaozhi_service.py install      # 登录自启（免管理员，HKCU Run）
    python xiaozhi_service.py start        # 立即启动
    python xiaozhi_service.py status       # 查看状态
    python xiaozhi_service.py stop         # 停止
    python xiaozhi_service.py uninstall    # 移除自启

调试：
    python xiaozhi_unified_server.py --token <tok> --check-only   # 验收后退出
    python xiaozhi_unified_server.py --token <tok>                # 常驻

## 验收（2026-10-28，agentId 2568270）

    tools/list          ✓ 49 个
    laap_pc_status      ✓  39ms   CPU/内存/磁盘
    kit_pc_status       ✓ 278ms   屏幕 3840x2160，当前窗口
    laap_pc_windows     ✓ 1197ms  经 LAAP 的窗口清单
    kit_pc_windows      ✓    1ms  本机窗口清单
    laap_status         ✓ 2234ms  在线服务
    pc_click            ✓  68ms
    旧名 pc_status      ✓ 正确拒绝
    改名后分发全通 6/6 · errors=0

## 四个踩过的坑

1. MiniXiaozhiBridge 的 device_tools 要 dict；直接构造 MiniXiaozhiConn 才要 ToolSpec。
2. 语义合并时 kit 的 handler 是 async，同步包装会得到 'coroutine never awaited'，
   半边结果为空。看着成了其实缺一半，最危险。
3. xiaozhi_unified_server.py 最初是验收脚本，跑完就退出，
   导致 service start 一起来就死。服务必须 serve-forever。
4. schtasks /RL HIGHEST 需要管理员，普通权限下 Access denied。
   退到 HKCU Run 键即可，且对本场景更合适（控电脑本来就要登录着）。
