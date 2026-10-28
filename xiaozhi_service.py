"""
xiaozhi_service.py — LAAP 小智统一服务常驻包装

作用：让 47 工具的服务在开机后自动起来、断线自动重连、崩溃自动拉起。
没有这层，重启一次就得手动敲命令，等于没接入。

用法：
    python xiaozhi_service.py install      # 注册开机自启（计划任务）
    python xiaozhi_service.py uninstall    # 移除自启
    python xiaozhi_service.py start        # 立即启动
    python xiaozhi_service.py stop         # 停止
    python xiaozhi_service.py status       # 查看状态
    python xiaozhi_service.py run          # 前台运行（调试用）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNIFIED = HERE / "xiaozhi_unified_server.py"
DATA_DIR = Path.home() / ".laap" / "xiaozhi-service"
STATE = DATA_DIR / "state.json"
LOG = DATA_DIR / "service.log"
PIDFILE = DATA_DIR / "service.pid"
TASK_NAME = "LAAP-Xiaozhi-Service"

DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_cfg() -> dict:
    cfg = DATA_DIR / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cfg(cfg: dict) -> None:
    (DATA_DIR / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def python_exe() -> str:
    return sys.executable or "python"


def is_running() -> bool:
    if not PIDFILE.exists():
        return False
    try:
        pid = int(PIDFILE.read_text().strip())
    except Exception:
        return False
    if sys.platform == "win32":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                           capture_output=True, text=True)
        return str(pid) in r.stdout
    return Path(f"/proc/{pid}").exists()


def start(cfg: dict | None = None) -> int:
    cfg = cfg or load_cfg()
    token = cfg.get("token", "").strip()
    if not token:
        print("✗ 缺少 token。先配置：")
        print(f"    python {Path(__file__).name} config --token <wss url 或裸 JWT>")
        return 1
    if is_running():
        print("已在运行")
        return 0

    node_id = cfg.get("node_id", "xiaozhi-unified")
    cmd = [python_exe(), str(UNIFIED), "--token", token, "--node-id", node_id]
    logf = open(LOG, "a", encoding="utf-8")
    logf.write(f"\n==== 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
    logf.flush()

    kwargs = dict(stdout=logf, stderr=subprocess.STDOUT,
                  cwd=str(HERE), stdin=subprocess.DEVNULL)
    if sys.platform == "win32":
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    p = subprocess.Popen(cmd, **kwargs)
    PIDFILE.write_text(str(p.pid), encoding="utf-8")
    print(f"已启动 pid={p.pid}  日志: {LOG}")
    return 0


def stop() -> int:
    if not PIDFILE.exists():
        print("未在运行")
        return 0
    try:
        pid = int(PIDFILE.read_text().strip())
    except Exception:
        PIDFILE.unlink(missing_ok=True)
        return 0
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    PIDFILE.unlink(missing_ok=True)
    print(f"已停止 pid={pid}")
    return 0


def status() -> int:
    cfg = load_cfg()
    run = is_running()
    print("=" * 56)
    print("LAAP 小智统一服务")
    print("=" * 56)
    print(f"  运行中   {'✓' if run else '✗'}")
    print(f"  node_id  {cfg.get('node_id', 'xiaozhi-unified')}")
    tok = cfg.get("token", "")
    if tok:
        # 不打印完整 token
        import base64
        try:
            tail = tok.split("token=")[-1].split(".")[1]
            pad = lambda s: s + "=" * (-len(s) % 4)
            pl = json.loads(base64.urlsafe_b64decode(pad(tail)))
            print(f"  agentId  {pl.get('agentId')}")
            exp = int(pl.get("exp", 0))
            print(f"  过期     {time.strftime('%Y-%m-%d', time.gmtime(exp))}"
                  f"（剩 {(exp - time.time()) / 3600:.0f} 小时）")
        except Exception:
            print("  token    (已配置)")
    else:
        print("  token    未配置")
    print(f"  日志     {LOG}")
    if LOG.exists():
        tail = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-3:]
        for ln in tail:
            print(f"    {ln}")
    return 0 if run else 1


def install() -> int:
    cfg = load_cfg()
    if not cfg.get("token"):
        print("✗ 请先配置 token")
        return 1
    if sys.platform != "win32":
        print("当前仅实现了 Windows；其它平台请用 systemd/launchd。")
        return 1

    cmd = f'"{python_exe()}" "{HERE / "xiaozhi_service.py"}" start'

    # 方案 A：计划任务 ONSTART（需管理员）——真正的开机即起，无需登录。
    # 方案 B：HKCU Run 键（免管理员）——用户登录时启动。
    #
    # 优先 A，被拒绝就退到 B。对这个场景 B 其实更合适：
    # 控制电脑本来就需要用户登录着，没必要为此要管理员权限。
    r = subprocess.run([
        "schtasks", "/Create", "/F",
        "/TN", TASK_NAME,
        "/SC", "ONSTART",
        "/TR", cmd,
        "/RU", os.environ.get("USERNAME", "SYSTEM"),
        "/RL", "HIGHEST",
    ], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"✓ 已注册开机自启（计划任务 {TASK_NAME}，需登录前启动）")
        return 0

    # 退到 HKCU Run 键，不需要管理员
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        ) as k:
            winreg.SetValueEx(k, TASK_NAME, 0, winreg.REG_SZ, cmd)
        print("✓ 已注册登录自启（HKCU Run 键，免管理员）")
        print("  注：用户登录时启动，不是开机即起。")
        print(f"  手动触发: {cmd}")
        return 0
    except Exception as e:
        print(f"✗ 两种自启方式都失败: {e}")
        print(f"  退而求其次：手动启动 → {cmd}")
        return 1


def uninstall() -> int:
    if sys.platform != "win32":
        return 1
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                   capture_output=True)
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        ) as k:
            try:
                winreg.DeleteValue(k, TASK_NAME)
            except FileNotFoundError:
                pass
    except Exception:
        pass
    print(f"✓ 已移除自启: {TASK_NAME}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("config"); c.add_argument("--token"); c.add_argument("--node-id")
    sub.add_parser("start"); sub.add_parser("stop")
    sub.add_parser("status"); sub.add_parser("run")
    sub.add_parser("install"); sub.add_parser("uninstall")
    a = ap.parse_args()

    if a.cmd == "config":
        cfg = load_cfg()
        if a.token:
            t = a.token.strip()
            if not t.startswith(("ws://", "wss://")):
                t = "wss://api.xiaozhi.me/mcp/?token=" + t
            cfg["token"] = t
        if a.node_id:
            cfg["node_id"] = a.node_id
        save_cfg(cfg)
        print("✓ 配置已保存")
        return 0
    if a.cmd == "start":
        return start()
    if a.cmd == "stop":
        return stop()
    if a.cmd in ("status", None):
        return status()
    if a.cmd == "install":
        return install()
    if a.cmd == "uninstall":
        return uninstall()
    if a.cmd == "run":
        cfg = load_cfg()
        os.execv(python_exe(), [python_exe(), str(UNIFIED),
                                "--token", cfg.get("token", ""),
                                "--node-id", cfg.get("node_id", "xiaozhi-unified")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
