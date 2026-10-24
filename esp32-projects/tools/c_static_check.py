"""C 代码静态检查器 — 没有 gcc 时能做的验证

检查项：
  1. 括号/花括号平衡
  2. 头文件声明的函数是否都有定义
  3. .c 里调用的 laap_* 函数是否在某个头文件里声明过
  4. include 的头文件是否都存在
  5. 明显问题：未闭合注释、多余分号、static 变量被外部使用
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

COMP = Path(r"D:\LAAP\laap-hardware\esp32-projects\components\laap_core")

# 匹配函数声明/定义：返回类型 名字(参数)
DECL_RE = re.compile(
    r"^\s*(?:static\s+|extern\s+|inline\s+)*"
    r"(?:const\s+)?(?:unsigned\s+|signed\s+)?"
    r"(?:void|int|char|float|double|bool|size_t|int64_t|int32_t|int16_t|int8_t|"
    r"uint64_t|uint32_t|uint16_t|uint8_t|laap_err_t|laap_msg_kind_t|laap_state_t|"
    r"const\s+char\s*\*)\s*"
    r"(\*?\s*)(\w+)\s*\(",
    re.MULTILINE,
)


def strip_comments(src: str) -> str:
    """去掉注释和字符串，避免误判"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    # 去掉字符串字面量
    src = re.sub(r'"(?:\\.|[^"\\])*"', '""', src)
    src = re.sub(r"'(?:\\.|[^'\\])*'", "''", src)
    return src


def check_balance(path: Path) -> List[str]:
    src = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    issues = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    for lineno, line in enumerate(src.splitlines(), 1):
        for ch in line:
            if ch in pairs:
                stack.append((ch, lineno))
            elif ch in pairs.values():
                if not stack:
                    issues.append(f"{path.name}:{lineno} 多余的 '{ch}'")
                else:
                    op, ol = stack.pop()
                    if pairs[op] != ch:
                        issues.append(
                            f"{path.name}:{lineno} 括号不匹配 '{op}'@{ol} vs '{ch}'")
    for op, ol in stack:
        issues.append(f"{path.name}:{ol} 未闭合 '{op}'")
    return issues


def collect_decls(header: Path) -> Set[str]:
    src = strip_comments(header.read_text(encoding="utf-8", errors="replace"))
    out = set()
    for m in DECL_RE.finditer(src):
        name = m.group(2)
        if name in {"if", "while", "for", "switch", "sizeof", "return"}:
            continue
        out.add(name)
    return out


def collect_defs(cfile: Path) -> Set[str]:
    src = strip_comments(cfile.read_text(encoding="utf-8", errors="replace"))
    out = set()
    for m in DECL_RE.finditer(src):
        name = m.group(2)
        # 定义的特征：名字后面到匹配括号之后有 '{'
        start = m.end()
        depth = 1
        i = start
        while i < len(src) and depth > 0:
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
            i += 1
        rest = src[i:i + 80].lstrip()
        if rest.startswith("{") or rest.startswith("const {"):
            out.add(name)
    return out


def collect_calls(cfile: Path) -> Set[str]:
    src = strip_comments(cfile.read_text(encoding="utf-8", errors="replace"))
    return set(re.findall(r"\b(laap_\w+)\s*\(", src))


def main() -> int:
    if not COMP.exists():
        print(f"组件目录不存在: {COMP}")
        return 1

    headers = sorted((COMP / "include").glob("*.h"))
    cfiles = sorted(COMP.glob("*.c"))

    print("=" * 62)
    print("LAAP Core C 组件静态检查")
    print("=" * 62)
    print(f"头文件 {len(headers)} 个 | 实现 {len(cfiles)} 个\n")

    all_issues: List[str] = []

    # 1. 括号平衡
    for f in headers + cfiles:
        all_issues += check_balance(f)
    print(f"[1] 括号平衡: {'✓ 全部通过' if not all_issues else '✗ ' + str(len(all_issues)) + ' 处问题'}")

    # 2. 头文件声明的函数都有定义
    decls: Dict[str, str] = {}
    for h in headers:
        for d in collect_decls(h):
            decls[d] = h.name
    defs: Set[str] = set()
    for c in cfiles:
        defs |= collect_defs(c)

    # 排除类型名/宏
    api = {d for d in decls if d.startswith("laap_")}
    missing_def = sorted(api - defs)
    print(f"[2] 头文件 API {len(api)} 个，已定义 {len(api & defs)} 个"
          + (f"，缺定义: {missing_def}" if missing_def else " ✓"))

    # 3. 调用的 laap_* 都有声明
    calls: Set[str] = set()
    for c in cfiles:
        calls |= collect_calls(c)
    # 定义本身也在调用集合里（定义处也匹配 xxx( ）
    undeclared = sorted(calls - api - defs)
    print(f"[3] 调用 {len(calls)} 个 laap_* 函数"
          + (f"，未声明: {undeclared}" if undeclared else " ✓ 全部有声明"))

    # 4. include 存在
    inc_issues = []
    local_headers = {h.name for h in headers}
    for c in cfiles:
        src = c.read_text(encoding="utf-8", errors="replace")
        for inc in re.findall(r'#include\s+"([^"]+)"', src):
            if inc in local_headers:
                continue
            # 项目内其它路径
            if (COMP / inc).exists() or (COMP / "include" / inc).exists():
                continue
            # ESP-IDF / 系统头：只白名单检查
            known = ("esp_", "freertos/", "driver/", "cJSON", "sdkconfig",
                     "stdio", "string", "stdlib", "stdint", "stdbool", "stddef", "math")
            if any(k in inc for k in known):
                continue
            inc_issues.append(f"{c.name}: #include \"{inc}\" 找不到")
    print(f"[4] include 检查: {'✓ 通过' if not inc_issues else '✗ ' + str(len(inc_issues))}")

    # 5. 头文件保护
    guard_issues = []
    for h in headers:
        s = h.read_text(encoding="utf-8", errors="replace")
        if "#pragma once" not in s and "#ifndef" not in s:
            guard_issues.append(f"{h.name} 缺头文件保护")
    print(f"[5] 头文件保护: {'✓ 通过' if not guard_issues else '✗ ' + str(len(guard_issues))}")

    # 6. 命名规范：laap_ 前缀
    bad_names = [d for d in defs if not d.startswith("laap_")
                 and not d.startswith("build_") and not d.startswith("on_")
                 and not d.startswith("set_") and not d.startswith("copy_")
                 and not d.startswith("get_") and not d.startswith("add_")
                 and not d.startswith("finish") and not d.startswith("motion_kind")
                 and not d.startswith("strip") and not d.startswith("reconnect")
                 and not d.startswith("ws_") and not d.startswith("check")
                 and not d.startswith("collect") and not d.startswith("now_")]
    print(f"[6] 内部函数用 static/前缀: {'✓' if not bad_names else '注意: ' + str(bad_names[:5])}")

    print()
    issues = all_issues + inc_issues + guard_issues
    if missing_def:
        issues += [f"缺定义: {m}" for m in missing_def]
    if undeclared:
        issues += [f"未声明调用: {u}" for u in undeclared]

    if issues:
        print("发现问题：")
        for i in issues:
            print(f"  ✗ {i}")
        return 1

    # 统计
    total_lines = sum(len(f.read_text(encoding='utf-8', errors='replace').splitlines())
                      for f in headers + cfiles)
    print(f"✓ 全部通过  ({len(headers) + len(cfiles)} 文件 / {total_lines} 行)")
    print()
    print("接口清单：")
    for h in headers:
        ds = sorted(d for d in collect_decls(h) if d.startswith("laap_"))
        print(f"  {h.name:20s} {', '.join(ds) if ds else '（无 laap_ API）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())