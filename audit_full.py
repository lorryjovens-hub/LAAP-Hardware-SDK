"""LAAPer 全面代码审计 — 找出所有 bug 和不一致"""
import ast
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple

BASE = Path(r"D:\LAAP\laap-hardware")


def check_syntax_errors() -> List[str]:
    """语法检查"""
    errors = []
    for py_file in BASE.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except SyntaxError as e:
            errors.append(f"{py_file.name}: line {e.lineno} - {e.msg}")
    return errors


def check_import_errors() -> List[str]:
    """导入检查"""
    errors = []
    test_imports = [
        "laaper.core.frame",
        "laaper.core.brain",
        "laaper.core.channel",
        "laaper.perception.encoder",
        "laaper.perception.fusion",
        "laaper.devices.sensor_unit",
        "laaper.devices.sensors",
        "laaper.devices.digital_life",
        "laaper.discovery.device_finder",
        "laaper.security.certificates",
        "laaper.persistence.store",
        "laaper.network.websocket_transport",
        "laaper.hosts.adapter",
        "laaper.devices.sensory",
    ]

    sys.path.insert(0, str(BASE))

    for module in test_imports:
        try:
            __import__(module)
        except Exception as e:
            errors.append(f"{module}: {e}")
    return errors


def check_common_patterns() -> List[str]:
    """常见 bug 模式检查"""
    issues = []

    for py_file in BASE.rglob("*.py"):
        if "__pycache__" in str(py_file) or py_file.name == "audit_full.py":
            continue

        with open(py_file) as f:
            content = f.read()
            lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # 检查 field(default_factory=time.time()) 应该是 time.time
            if "default_factory=time.time()" in line:
                issues.append(f"{py_file.name}:{i} - field(default_factory=time.time()) 应该去掉括号")

            # 检查类型注解错误
            if "Dict[str, Dict[str, Dict]" in line:
                issues.append(f"{py_file.name}:{i} - 类型注解嵌套过深")

    return issues


def check_type_consistency() -> List[str]:
    """类型一致性检查"""
    issues = []

    for py_file in BASE.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        with open(py_file) as f:
            content = f.read()

        # 检查 SensoryModality 引用一致性
        olfaction_refs = re.findall(r"SensoryModality\.\w+", content)
        for ref in olfaction_refs:
            if "OLFCCTION" in ref or "OLFACTION" in ref:
                if ref != "SensoryModality.OLFCTION":
                    issues.append(f"{py_file.name} - {ref} 应该是 SensoryModality.OLFCTION")

    return issues


def run_audit():
    print("=" * 70)
    print("LAAPer 全面代码审计")
    print("=" * 70)
    print()

    # 1. 语法检查
    print("[1] 语法检查")
    syntax_errors = check_syntax_errors()
    if syntax_errors:
        for e in syntax_errors:
            print(f"  [ERROR] {e}")
    else:
        print("  [OK] 所有文件语法正确")
    print()

    # 2. 导入检查
    print("[2] 模块导入检查")
    import_errors = check_import_errors()
    if import_errors:
        for e in import_errors:
            print(f"  [ERROR] {e}")
    else:
        print("  [OK] 所有模块导入正常")
    print()

    # 3. 常见 bug 模式
    print("[3] 常见 bug 模式检查")
    patterns = check_common_patterns()
    if patterns:
        for p in patterns:
            print(f"  [WARN] {p}")
    else:
        print("  [OK] 未发现常见 bug 模式")
    print()

    # 4. 类型一致性
    print("[4] 类型一致性检查")
    type_issues = check_type_consistency()
    if type_issues:
        for t in type_issues:
            print(f"  [WARN] {t}")
    else:
        print("  [OK] 类型引用一致")
    print()

    # 5. 文件统计
    print("[5] 文件统计")
    py_files = list(BASE.rglob("*.py"))
    total_lines = 0
    for f in py_files:
        if "__pycache__" not in str(f):
            with open(f) as fp:
                total_lines += len(fp.readlines())

    print(f"  Python 文件: {len(py_files)}")
    print(f"  总行数: {total_lines}")
    print()

    print("=" * 70)
    print("审计完成")
    print("=" * 70)


if __name__ == "__main__":
    run_audit()