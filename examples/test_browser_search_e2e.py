"""搜索 + 网页 全链路验证"""
import sys
import asyncio

sys.path.insert(0, r"D:\LAAP\laap-hardware")


async def main():
    from laaper.hub.tri_node_daemon import TriNodeDaemon, DaemonConfig

    print("=" * 70)
    print("  搜索 + 网页 全链路验证")
    print("=" * 70)
    print()

    daemon = TriNodeDaemon(DaemonConfig(
        node_id="pc-hub",
        start_lan=False,
        connect_cloud=False,
        enable_computer=True,
        enable_multistep=False,
        enable_browser=True,
        browser_headless=True,
    ))
    await daemon.start()

    cases = [
        ("搜索 LAAP 开源",
         "搜索意图 → GitHub/Bing 出结果 + 摘录"),
        ("打开 www.laap.cn 看看有什么",
         "打开网址 + 视觉描述"),
        ("页面上有什么能点的",
         "看可交互元素"),
        ("点击进入 Studio",
         "DOM 点击 + 确认"),
        ("搜索论文 意识工程",
         "搜索意图 → arxiv/Bing"),
        ("往下翻",
         "浏览器有页面时交互走浏览器"),
    ]

    for text, expect in cases:
        r = await daemon._execute_action("voice_command", {"text": text})
        print(f"[{len(str(text)):>2}] 「{text}」  <- {expect}")
        print(f"     路由: {r.get('route')}  成功: {r.get('success')}")
        print(f"     回复: {r.get('reply', '')[:130]}")
        print()

    st = daemon.browser_agent.get_status() if daemon.browser_agent else {}
    print("浏览器统计:", daemon.browser_agent.stats if daemon.browser_agent else {})

    if daemon.browser_agent:
        await daemon.browser_agent.close()
    await daemon.stop()

    print()
    print("=" * 70)
    print("  验证完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())