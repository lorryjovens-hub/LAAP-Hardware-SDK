# 小智硬件统一服务 · 47 工具

一台小智硬件同时拥有两套能力：
生产版 36 个（ask_aris / tell_hana / pc_run / recall / kemo_music / dev_task ...）
+ LAAP-Agent-Kit 13 个（voice_command / pc_click / pc_type / 浏览器视觉 / 多步任务）。

## 命名冲突的处理

pc_status / pc_windows 两边都有，语义不同：
  生产版 = LAAP 服务健康    kit 版 = 本机窗口/状态
解法：**语义合并** —— 一个工具同时返回两边结果：
  [LAAP] CPU 32.5%... / [本机] 窗口列表...

## 用法

    python xiaozhi_service.py config --token <wss url 或裸 JWT>
    python xiaozhi_service.py install      # 登录自启（免管理员，HKCU Run）
    python xiaozhi_service.py start        # 立即启动
    python xiaozhi_service.py status       # 查看状态
    python xiaozhi_service.py stop         # 停止
    python xiaozhi_service.py uninstall    # 移除自启

调试用：
    python xiaozhi_unified_server.py --token <tok> --check-only
    python xiaozhi_unified_server.py --token <tok>            # 常驻

## 验收结果（2026-10-28，agentId 2568270）

    [1] initialize        ✓  serverInfo 已应答
    [2] initialized       ✓  init_done=True
    [3] tools/list        ✓  返回 47 个
    [4] ping              ✓
    [5] tools/call 分发
        pc_status     ✓  291ms   [LAAP] + [本机] 双栏
        laap_status   ✓ 2272ms   总体 degraded / 在线服务清单
        pc_windows    ✓ 1479ms   [LAAP] 窗口清单
    [6] 未知工具          ✓  正确报错
    [7] 未知方法          ✓  code=-32601
    ✓ 端到端分发链路全通 · 3/3 真实调用 · 0 错误

## 三个踩过的坑（都值得记）

1. MiniXiaozhiBridge 的 device_tools 要 dict，直接给 ToolSpec 会炸在 t.get('name')
   —— 直接构造 MiniXiaozhiConn 才要 ToolSpec。两者不一样。
2. 语义合并时 kit 的 handler 是 async，用同步包装去接会得到
   'coroutine never awaited'，半边结果为空。必须 await。
3. xiaozhi_unified_server.py 最初是验收脚本，跑完就退出，
   导致 xiaozhi_service.py start 一起来就死。服务必须 serve-forever。
