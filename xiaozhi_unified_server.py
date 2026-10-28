"""
xiaozhi_unified_server.py — 一台小智硬件挂 47 个工具

生产版 36 + LAAP-Agent-Kit 13，冲突的 2 个用语义合并。

定案（可改）：
  范围   全开 36 + 13 = 47
  冲突   pc_status / pc_windows → 一个工具同时报「LAAP 健康」与「本机状态」
  理由   用户选的是「两套合并、能力最全」，全开 + 语义合并是它的字面含义

用法：
  python xiaozhi_unified_server.py --token <wss url 或裸 JWT>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\user\Desktop\LAAP-Agent-Kit")

from xiaozhi_merged_tools import (  # noqa: E402
    CollisionStrategy, MergeResult, build_merged_tools,
)
from mini_xiaozhi import MiniXiaozhiBridge  # noqa: E402


def to_tool_specs(result: MergeResult) -> list[dict]:
    """MiniXiaozhiBridge 的 device_tools 要原始 dict（不是 ToolSpec），
    它内部会自己包成 ToolSpec。传错类型会炸在 t.get("name")。"""
    return [t.to_mcp() for t in result.tools]


def make_dispatch(result: MergeResult) -> Dict[str, Any]:
    """名字 → 异步处理器。同步 handler 包一层，统一成 async。"""
    out: Dict[str, Any] = {}
    for t in result.tools:
        fn = t.handler

        async def _run(args: Dict[str, Any], _fn=fn, _name=t.name) -> str:
            try:
                r = _fn(args or {})
                if asyncio.iscoroutine(r):
                    r = await r
                if not isinstance(r, str):
                    r = json.dumps(r, ensure_ascii=False)
                return r
            except Exception as e:
                return f"[{_name}] 执行失败: {type(e).__name__}: {e}"

        out[t.name] = _run
    return out


async def run(token_url: str, node_id: str = "xiaozhi-unified",
              serve: bool = True) -> int:
    print("=" * 64)
    print("  LAAP 小智统一服务 · 47 工具")
    print("=" * 64)

    print("\n[1/4] 合并工具集")
    result = build_merged_tools(CollisionStrategy.MERGE_SEMANTIC)
    print(f"      生产版 {result.prod_count} + kit {result.kit_count}"
          f" → 合并后 {result.count} 个")
    print(f"      语义合并: {['pc_status', 'pc_windows']}")
    if result.warnings:
        for w in result.warnings[:6]:
            print(f"      ⚠ {w}")

    by_origin: Dict[str, int] = {}
    for t in result.tools:
        by_origin[t.origin] = by_origin.get(t.origin, 0) + 1
    print(f"      来源分布: {by_origin}")

    print("\n[2/4] 挂载处理器")
    dispatch = make_dispatch(result)
    print(f"      {len(dispatch)} 个 handler 就绪")

    print("\n[3/4] 连接 broker")
    bridge = MiniXiaozhiBridge(
        device_tools=to_tool_specs(result),
        endpoints={node_id: token_url},
    )
    for conn in bridge.connections.values():
        conn.set_tool_callbacks(dispatch)

    await bridge.start()
    await asyncio.sleep(2.5)

    print("\n[4/4] 验收")
    ok = 0
    total = 0
    for name, conn in bridge.connections.items():
        st = conn.status()
        total += 1
        print(f"      [{name}]")
        for k in ("online", "init_done", "tools", "registered", "rx", "tx", "errors"):
            print(f"          {k:<11} {st.get(k)}")
        if st.get("online") and st.get("init_done") and st.get("errors", 0) == 0:
            ok += 1

    # 抽查几个 handler 真能跑
    print("\n      抽查处理器（本地直调，不经 broker）:")
    for probe in ("pc_status", "laap_status", "pc_windows"):
        if probe in dispatch:
            t0 = time.time()
            try:
                r = await dispatch[probe]({})
                dt = (time.time() - t0) * 1000
                head = str(r).replace("\n", " / ")[:96]
                print(f"          {probe:<13} ✓ {dt:.0f}ms  {head}")
            except Exception as e:
                print(f"          {probe:<13} ✗ {type(e).__name__}: {str(e)[:50]}")

    await bridge.stop()

    print()
    print("=" * 64)
    print(f"  {'✓ 就绪' if ok == total else '⚠ 部分异常'}  "
          f"{result.count} 个工具 · {ok}/{total} 端点在线")
    print("=" * 64)

    # 关键：验收完不能退出。这是**服务**，不是一次性脚本。
    # 之前就是跑完就 return，导致 xiaozhi_service.py start 一起来就死。
    if not serve or ok != total:
        return 0 if ok == total else 1

    print("\n进入常驻模式（Ctrl+C 退出）…")
    try:
        while True:
            await asyncio.sleep(30)
            h = bridge.health()
            online = h.get("online", 0)
            calls = sum(d.get("tool_calls", 0) for d in h.get("detail", {}).values())
            print(f"  [{time.strftime('%H:%M:%S')}] 在线 {online}/{h.get('endpoints', 0)}"
                  f"  累计工具调用 {calls}")
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n\n  正在退出…")
    finally:
        await bridge.stop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True, help="wss URL 或裸 JWT")
    ap.add_argument("--node-id", default="xiaozhi-unified")
    ap.add_argument("--check-only", action="store_true",
                    help="只做验收后退出（不常驻），用于调试")
    args = ap.parse_args()

    tok = args.token.strip()
    if not tok.startswith(("ws://", "wss://")):
        tok = "wss://api.xiaozhi.me/mcp/?token=" + tok
    return asyncio.run(run(tok, args.node_id, serve=not args.check_only))


if __name__ == "__main__":
    sys.exit(main())
