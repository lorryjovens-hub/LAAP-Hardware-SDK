"""端到端验证：小智语音 → daemon 分流 → 浏览器能看能点

模拟小智先后说：
  1. 「打开 www.laap.cn 看看有什么」  → 浏览器导航 + 感知 + 视觉描述
  2. 「点击进入 Studio」              → DOM 精确点击 + 截图确认
  3. 「页面上有什么能点的」           → 可交互元素摘要
"""
import sys
import asyncio

sys.path.insert(0, r"D:\LAAP\laap-hardware")


async def main():
    from laaper.hub.tri_node_daemon import TriNodeDaemon, DaemonConfig

    print("=" * 70)
    print("  小智语音 → 电脑浏览器 端到端验证")
    print("=" * 70)
    print()

    daemon = TriNodeDaemon(DaemonConfig(
        node_id="pc-hub",
        node_name="LAAP 电脑",
        start_lan=False,           # 不占端口
        connect_cloud=False,       # 纯本地能力验证
        enable_computer=True,
        enable_multistep=False,
        enable_browser=True,
        browser_headless=True,
    ))
    await daemon.start()

    print(f"浏览器代理: {'启用' if daemon.browser_agent else '未启用'}")
    print()

    # ── 1. 打开网页 + 看 ──
    print("[1] 小智说: 「打开 www.laap.cn 看看有什么」")
    r1 = await daemon._execute_action("voice_command", {"text": "打开 www.laap.cn 看看有什么"})
    print(f"    路由: {r1.get('route')}")
    print(f"    成功: {r1.get('success')}")
    print(f"    回复: {r1.get('reply', '')[:160]}")
    print()

    # ── 2. 看页面 ──
    print("[2] 小智说: 「页面上有什么能点的」")
    r2 = await daemon._execute_action("voice_command", {"text": "页面上有什么能点的"})
    print(f"    路由: {r2.get('route')}")
    print(f"    成功: {r2.get('success')}")
    print(f"    回复: {r2.get('reply', '')[:180]}")
    print()

    # ── 3. 点击网页上的元素 ──
    print("[3] 小智说: 「点击进入 Studio」")
    r3 = await daemon._execute_action("voice_command", {"text": "点击进入 Studio"})
    print(f"    路由: {r3.get('route')}")
    print(f"    成功: {r3.get('success')}")
    print(f"    回复: {r3.get('reply', '')[:160]}")
    print()

    # ── 4. 再确认页面变了 ──
    print("[4] 当前浏览器状态")
    st = daemon.browser_agent.get_status() if daemon.browser_agent else {}
    print(f"    URL: {st.get('url')}")
    print(f"    统计: {daemon.browser_agent.stats if daemon.browser_agent else {}}")
    print()

    # ── 5. 桌面意图仍走桌面 ──
    print("[5] 对照: 「往下翻」应走桌面路由")
    r5 = await daemon._execute_action("voice_command", {"text": "往下翻"})
    print(f"    路由: {r5.get('route')}  成功: {r5.get('success')}")
    print()

    if daemon.browser_agent:
        await daemon.browser_agent.close()
    await daemon.stop()

    print("=" * 70)
    print("  验证完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())