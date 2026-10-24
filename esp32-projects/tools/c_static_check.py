"""C 代码静态检查器 — 没有 gcc 时能做的验证

支持检查多个组件：
    python tools/c_static_check.py              # 全部组件
    python tools/c_static_check.py laap_core    # 指定组件

检查项：
  1. 括号/花括号平衡
  2. 头文件声明的函数是否都有定义
  3. .c 里调用的函数是否在某个头文件里声明过
  4. include 的头文件是否都存在
  5. 头文件保护
  6. 弱符号默认实现覆盖（BSP 特有：每个弱接口都有对应强实现或确实不需要）

## 弱符号检查（BSP 关键）

bsp_base.c 给每个板级接口一个弱默认实现，board.c 用强符号覆盖。
如果 board.c 声明了某项能力（BSP_CAP_X）但没覆盖对应函数，
真机上就会走到"不支持"分支。这个检查抓这类问题。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "components"

DECL_RE = re.compile(
    r"^\s*"
    r"(?:(?:__attribute__\s*\(\([^)]*\)\)|static|extern|inline)\s*)*"
    r"(?:const\s+)?(?:unsigned\s+|signed\s+)?"
    r"(?:void|int|char|float|double|bool|size_t|int64_t|int32_t|int16_t|int8_t|"
    r"uint64_t|uint32_t|uint16_t|uint8_t|esp_err_t|laap_err_t|laap_msg_kind_t|"
    r"laap_state_t|const\s+\w+\s*\*|\w+_t)\s*"
    r"(\*?\s*)(\w+)\s*\(",
    re.MULTILINE,
)

# 系统/IDF 头文件白名单（只检查项目内 include）
KNOWN_INC = ("esp_", "freertos/", "driver/", "cJSON", "sdkconfig", "soc/",
             "hal/", "stdio", "string", "stdlib", "stdint", "stdbool",
             "stddef", "math", "stdlib")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
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


def collect_defs(cfile: Path, include_weak: bool = True) -> Dict[str, bool]:
    """返回 {函数名: 是否弱符号}"""
    raw = cfile.read_text(encoding="utf-8", errors="replace")
    src = strip_comments(raw)

    # 记录每个函数前面最近的 weak 标记
    out: Dict[str, bool] = {}
    for m in DECL_RE.finditer(src):
        name = m.group(2)
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
        if not (rest.startswith("{") or rest.startswith("const {")):
            continue

        # 往前找 300 字符 + 本次匹配内是否有 weak 标记
        marker = src[max(0, m.start() - 300):m.end()]
        is_weak = "__attribute__" in marker and "weak" in marker
        out[name] = is_weak
    return out


def check_component(name: str, comp: Path) -> tuple:
    headers = sorted((comp / "include").glob("*.h"))
    cfiles = sorted(comp.glob("*.c"))

    issues: List[str] = []
    warns: List[str] = []

    # 1. 括号
    for f in headers + cfiles:
        issues += [f"[{name}] {i}" for i in check_balance(f)]

    # 2. 头文件 API 都有定义
    decls: Dict[str, str] = {}
    for h in headers:
        for d in collect_decls(h):
            decls[d] = h.name

    defs: Dict[str, bool] = {}
    for c in cfiles:
        defs.update(collect_defs(c))

    # 板级子目录（BSP 特例）
    boards_dir = comp / "boards"
    board_files = sorted(boards_dir.glob("*/board.c")) if boards_dir.exists() else []

    api = {d for d in decls if d.startswith(("laap_", "bsp_"))}
    # bsp_ 接口允许只有弱默认实现（bsp_base.c 里）
    missing_def = sorted(api - set(defs))
    for m in missing_def:
        issues.append(f"[{name}] 头文件声明了 {m}() 但无定义")

    # 3. 调用的函数都有声明
    calls: Set[str] = set()
    for c in cfiles + board_files:
        src = strip_comments(c.read_text(encoding="utf-8", errors="replace"))
        calls |= set(re.findall(r"\b((?:laap|bsp)_\w+)\s*\(", src))
    undeclared = sorted(calls - api - set(defs))
    for u in undeclared:
        issues.append(f"[{name}] 调用了未声明的 {u}()")

    # 4. include 存在
    local_headers = {h.name for h in headers}
    for c in cfiles + board_files:
        src = c.read_text(encoding="utf-8", errors="replace")
        for inc in re.findall(r'#include\s+"([^"]+)"', src):
            if inc in local_headers: continue
            if (comp / inc).exists() or (comp / "include" / inc).exists(): continue
            if (c.parent / inc).exists(): continue
            if any(k in inc for k in KNOWN_INC): continue
            issues.append(f"[{name}] {c.name}: #include \"{inc}\" 找不到")

    # 5. 头文件保护
    for h in headers:
        s = h.read_text(encoding="utf-8", errors="replace")
        if "#pragma once" not in s and "#ifndef" not in s:
            issues.append(f"[{name}] {h.name} 缺头文件保护")

    # 6. BSP 弱符号覆盖检查
    if board_files:
        weak_funcs = {n for n, w in defs.items() if w}
        for bf in board_files:
            bdefs = collect_defs(bf)
            strong = {n for n, w in bdefs.items() if not w}
            src = bf.read_text(encoding="utf-8", errors="replace")
            caps = set(re.findall(r"BSP_CAP_(\w+)", src))
            # 声明的能力对应函数是否真实现了
            cap_map = {
                "DISPLAY": ["bsp_display_init"],
                "TOUCH": ["bsp_touch_init"],
                "AUDIO_OUT": ["bsp_audio_init"],
                "AUDIO_IN": ["bsp_audio_init"],
                "SERVO": ["bsp_servo_init", "bsp_servo_set_angle"],
                "I2C": ["bsp_i2c_init"],
            }
            for cap, fns in cap_map.items():
                if cap in caps:
                    for fn in fns:
                        if fn not in strong:
                            warns.append(
                                f"[{name}] {bf.parent.name}: 声明 {cap} 但未覆盖 {fn}()")

    return issues, warns, len(headers) + len(cfiles)


def main() -> int:
    print("=" * 68)
    print("LAAP C 组件静态检查")
    print("=" * 68)

    if not COMPONENTS.exists():
        print(f"✗ 找不到 {COMPONENTS}")
        return 1

    targets = []
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        targets = [COMPONENTS / sys.argv[1]]
    else:
        targets = sorted(d for d in COMPONENTS.iterdir() if d.is_dir())

    all_issues: List[str] = []
    all_warns: List[str] = []
    total_files = 0
    total_lines = 0

    for comp in targets:
        if not comp.exists():
            print(f"✗ 组件不存在: {comp.name}")
            return 1

        issues, warns, nfiles = check_component(comp.name, comp)

        files = (sorted((comp / "include").glob("*.h")) +
                 sorted(comp.glob("*.c")) +
                 sorted(comp.glob("boards/*/board.c")) +
                 sorted(comp.glob("boards/*/board_pins.h")))
        lines = sum(len(f.read_text(encoding='utf-8', errors='replace').splitlines())
                    for f in files)
        total_files += len(files)
        total_lines += lines

        status = "✓" if not issues else "✗"
        print(f"\n{status} {comp.name:14s} {len(files)} 文件 / {lines} 行")
        for w in warns:
            print(f"    ⚠ {w}")
            all_warns.append(w)
        for i in issues:
            print(f"    ✗ {i}")
            all_issues.append(i)

    print("\n" + "-" * 68)
    print(f"合计: {total_files} 文件 / {total_lines} 行"
          + (f" / {len(all_warns)} 个提示" if all_warns else ""))

    if all_issues:
        print(f"\n发现 {len(all_issues)} 个问题：")
        for i in all_issues:
            print(f"  ✗ {i}")
        return 1

    print("\n✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())