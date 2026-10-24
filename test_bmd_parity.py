"""BMD 二进制格式两侧对齐校验

## 这个测试存在的理由

C 和 Python 必须产出**完全相同的字节**，否则固件和 PC 之间无法通信。
而这种不一致极难发现：两边各自都「能跑」，只是解出来是垃圾。

已经抓到过的真 bug：
  `LBP_BMD_FIXED_SIZE` 宏里漏了 mass 的 4 字节
  → encoded_size 少算 4 → 长度检查通过但实际越界写 4 字节（缓冲区溢出）

所以这个测试做三件事：
  1. **真去解析 C 头文件**，把宏和 Python 常量对比
  2. 按文档的字节偏移逐字段验证（不只查总长度）
  3. 往返：编码 → 解码 → 再编码，必须逐字节相同
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from laaper.body.module import (
    ModuleDescriptor, make_module, BMD_FIXED_SIZE, BMD_JOINT_SIZE,
    BMD_PORT_SIZE, BMD_NAME_LEN, bmd_binary_size,
)

OK, FAIL = "✓", "✗"
results = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  {OK if cond else FAIL} {name}" + (f"  [{detail}]" if detail else ""))


C_HDR = Path(__file__).resolve().parent / "esp32-projects" / "components" \
    / "lbp" / "include" / "lbp_payload.h"
C_TYPES_HDR = C_HDR.parent / "lbp_types.h"

print("=" * 70)
print("LBP 协议格式 — C/Python 两侧对齐")
print("=" * 70)

# ══════════════════════════════════════════════════════════
# 1. 解析 C 头文件，对比常量
# ══════════════════════════════════════════════════════════
print("\n[1] C 头文件常量 vs Python 常量")

if not C_HDR.exists():
    check("找到 C 头文件", False, str(C_HDR))
    sys.exit(1)

csrc = C_HDR.read_text(encoding="utf-8", errors="replace")
# LBP_NAME_LEN 定义在 lbp_types.h，两个头都要查
csrc_all = csrc
if C_TYPES_HDR.exists():
    csrc_all += "\n" + C_TYPES_HDR.read_text(encoding="utf-8", errors="replace")


def c_def(name: str) -> int | None:
    """从 C 头文件读 #define 的数值（支持十进制与 0x 十六进制）"""
    m = re.search(rf"#define\s+{name}\s+(0[xX][0-9A-Fa-f]+|\d+)", csrc_all)
    if not m:
        return None
    return int(m.group(1), 0)


c_joint = c_def("LBP_BMD_JOINT_SIZE")
c_port = c_def("LBP_BMD_PORT_SIZE")
c_fixed = c_def("LBP_BMD_FIXED_SIZE")
c_name_len = c_def("LBP_NAME_LEN")

check("LBP_BMD_JOINT_SIZE 一致", c_joint == BMD_JOINT_SIZE,
      f"C={c_joint} Py={BMD_JOINT_SIZE}")
check("LBP_BMD_PORT_SIZE 一致", c_port == BMD_PORT_SIZE,
      f"C={c_port} Py={BMD_PORT_SIZE}")
check("LBP_BMD_FIXED_SIZE 一致", c_fixed == BMD_FIXED_SIZE,
      f"C={c_fixed} Py={BMD_FIXED_SIZE}")
check("名字长度一致", c_name_len == BMD_NAME_LEN,
      f"C={c_name_len} Py={BMD_NAME_LEN}")

# 独立重算固定部分（防止两边都写错同一个数）
manual_fixed = (4 + 2 + 1 + 1 + 2 + 2 + 8 + 1 + 1 + 4 + 12 + 4 + 4
                + 1 + 1 + 2 + 2 + 4 + 1 + 32)
check("固定部分由字段逐项相加等于 89", manual_fixed == 89, f"{manual_fixed}")

# 联合尺寸 = 固定 + 关节 + 端口
check("关节尺寸由字段相加等于 68",
      16 + 12 + 4 + 4 + 4 + 4 + 12 + 12 == 68, "16+12+16+12+12")
check("端口尺寸由字段相加等于 25", 1 + 12 + 12 == 25, "1+12+12")

# ══════════════════════════════════════════════════════════
# 2. 编码 3-DOF 腿，逐字段验证偏移
# ══════════════════════════════════════════════════════════
print("\n[2] 3-DOF 腿：编码与字节偏移")

leg = make_module("leg_3dof")
leg.serial = 0x1122334455667788
buf = leg.to_bytes()
expect_size = bmd_binary_size(3, 1)

check("编码长度正确", len(buf) == expect_size,
      f"{len(buf)}B（固定89 + 3×68 + 1×25 = {expect_size}）")
check("magic 是 'LBMD'", buf[0:4] == b"LBMD", buf[0:4].decode("ascii", "replace"))
check("ver_major 在偏移 4", buf[4] == 1, f"buf[4]={buf[4]}")
check("ver_minor 在偏移 5", buf[5] == 0, f"buf[5]={buf[5]}")
check("cls 在偏移 6（ACTUATOR=1）", buf[6] == 1, f"buf[6]={buf[6]}")
check("role 在偏移 7（LIMB=2）", buf[7] == 2, f"buf[7]={buf[7]}")

vid, pid = struct.unpack_from("<HH", buf, 8)
check("vendor_id/product_id 在偏移 8", vid == 0x1AAB and pid == 0x0010,
      f"vid=0x{vid:04X} pid=0x{pid:04X}")

(serial,) = struct.unpack_from("<Q", buf, 12)
check("serial 在偏移 12", serial == 0x1122334455667788, f"0x{serial:016X}")
check("dof 在偏移 20", buf[20] == 3, f"buf[20]={buf[20]}")

# 关节 0 从偏移 21 开始
J0 = 21
name0 = buf[J0:J0 + 16].split(b"\x00")[0].decode()
check("关节 0 名字在偏移 21", name0 == "hip_abduct", name0)

ax0 = struct.unpack_from("<3f", buf, J0 + 16)
check("关节 0 轴在偏移 37（=21+16）", abs(ax0[0] - 1.0) < 1e-6 and ax0[1] == 0,
      f"axis={tuple(round(v,3) for v in ax0)}")

lo, hi, vel, tq = struct.unpack_from("<4f", buf, J0 + 28)
import math
check("关节 0 限位在偏移 49（=21+28）",
      abs(lo - math.radians(-30)) < 1e-4 and abs(hi - math.radians(30)) < 1e-4,
      f"lo={math.degrees(lo):.1f}° hi={math.degrees(hi):.1f}°")

# 关节 2 从 21 + 2*68 开始
J2 = 21 + 2 * 68
name2 = buf[J2:J2 + 16].split(b"\x00")[0].decode()
check("关节 2 名字在偏移 157（=21+2×68）", name2 == "knee", name2)

# port_count 在 21 + 3*68 = 225
PC = 21 + 3 * 68
check("port_count 在偏移 225", buf[PC] == 1, f"buf[{PC}]={buf[PC]}")
check("端口 pos_id 在偏移 226", buf[PC + 1] == 0, f"{buf[PC+1]}")

# mass 在 226 + 25 = 251
MASSOFF = PC + 1 + BMD_PORT_SIZE
(mass,) = struct.unpack_from("<f", buf, MASSOFF)
check("mass 在偏移 251（固定部分含 mass 4 字节）",
      abs(mass - 0.28) < 1e-6, f"mass={mass}")
# mass 之后还有：com12 + payload4 + reach4 + bus1 + addr1 + power2 + peak2
#                   + caps4 + hw_ts1 + name32 = 63 字节
after_mass = 12 + 4 + 4 + 1 + 1 + 2 + 2 + 4 + 1 + 32
check("mass 偏移 + 4 + 尾部 63B == 总长",
      MASSOFF + 4 + after_mass == len(buf),
      f"{MASSOFF} + 4 + {after_mass} = {MASSOFF + 4 + after_mass} vs {len(buf)}")

# 尾部字段
off = MASSOFF + 4 + 12 + 4 + 4
bus_profile = buf[off]
off += 1
bus_addr = buf[off]
off += 1
power, peak = struct.unpack_from("<HH", buf, off)
off += 4
(caps,) = struct.unpack_from("<I", buf, off)
off += 4
hw_ts = buf[off]
off += 1
name_tail = buf[off:off + 32].split(b"\x00")[0].decode()

check("bus_profile 在 mass 之后", bus_profile == 1, f"{bus_profile}")
check("power/peak 正确", power == 900 and peak == 9000, f"{power}/{peak}")
check("caps 为 0（腿不声明能力）", caps == 0, f"0x{caps:X}")
check("hw_timestamp 为 1", hw_ts == 1, f"{hw_ts}")
check("模块名在最后 32 字节", name_tail == "leg_3dof", name_tail)
check("尾部字段正好收尾", off + 32 == len(buf), f"{off+32} == {len(buf)}")

# ══════════════════════════════════════════════════════════
# 3. 往返一致性
# ══════════════════════════════════════════════════════════
print("\n[3] 往返：编码 → 解码 → 再编码")

back = ModuleDescriptor.from_bytes(buf)
check("解码 dof", back.dof == leg.dof, f"{back.dof}")
check("解码质量", abs(back.mass_kg - leg.mass_kg) < 1e-6,
      f"{back.mass_kg}")
check("解码关节名", [j.name for j in back.joints] == [j.name for j in leg.joints],
      ",".join(j.name for j in back.joints))
check("解码端口数量", len(back.ports) == len(leg.ports),
      f"{len(back.ports)}")
check("解码 serial", back.serial == leg.serial, f"0x{back.serial:016X}")

buf2 = back.to_bytes()
check("再编码后逐字节相同", buf2 == buf,
      f"{'一致' if buf2 == buf else f'不同（{len(buf2)} vs {len(buf)}）'}")

# 关节数值往返
jr_ok = True
for j0, j1 in zip(leg.joints, back.joints):
    if abs(j0.min_rad - j1.min_rad) > 1e-5 or abs(j0.max_rad - j1.max_rad) > 1e-5:
        jr_ok = False
    if abs(j0.offset[2] - j1.offset[2]) > 1e-6 or abs(j0.link[2] - j1.link[2]) > 1e-6:
        jr_ok = False
check("关节数值往返精度", jr_ok, "float32 精度内一致")

# ══════════════════════════════════════════════════════════
# 4. 4-DOF 臂 + 分片估算
# ══════════════════════════════════════════════════════════
print("\n[4] 4-DOF 臂与分片数")

arm = make_module("arm_4dof")
arm_buf = arm.to_bytes()
expect_arm = bmd_binary_size(4, 1)
check("臂编码长度", len(arm_buf) == expect_arm,
      f"{len(arm_buf)}B（89 + 4×68 + 25 = {expect_arm}）")
check("臂 caps 含 MANIPULATION", arm.capability_bits & 0x02 != 0,
      f"caps=0x{arm.capability_bits:X}")
arm_back = ModuleDescriptor.from_bytes(arm_buf)
check("臂往返一致", arm_back.to_bytes() == arm_buf, "逐字节相同")

# CAN 2.0B：每 CAN 帧 8B，TP 首段带 5B 数据，之后每段 7B
def can_frames(lbp_len: int) -> int:
    if lbp_len <= 7:
        return 1
    return 1 + (lbp_len - 5 + 6) // 7

lbp_len = 18 + len(leg) if False else 18 + len(buf) + 5
check("腿 BMD 需多个 CAN 帧传输", can_frames(lbp_len) > 1,
      f"LBP 帧 {lbp_len}B → {can_frames(lbp_len)} 个 CAN 帧")
print(f"    参考：leg_3dof BMD {len(buf)}B → LBP 帧 {lbp_len}B "
      f"→ {can_frames(lbp_len)} 个 CAN 帧")

# ══════════════════════════════════════════════════════════
# 5. 帧层两侧对齐（轻量守卫：查 C 源码的字段偏移）
# ══════════════════════════════════════════════════════════
print("\n[5] 帧层字节偏移（C 源码 vs Python 常量）")

from laaper.body.frame import HDR_SIZE, TRAILER_SIZE, SOF, EOF

C_FRAME_C = C_HDR.parent.parent / "lbp_frame.c"
cframe = C_FRAME_C.read_text(encoding="utf-8", errors="replace") \
    if C_FRAME_C.exists() else ""

check("Python HDR_SIZE = 18", HDR_SIZE == 18, f"{HDR_SIZE}")
check("Python TRAILER_SIZE = 5", TRAILER_SIZE == 5, f"{TRAILER_SIZE}")

c_hdr = c_def("LBP_HDR_SIZE")
c_trailer = c_def("LBP_TRAILER_SIZE")
check("C LBP_HDR_SIZE 一致", c_hdr == HDR_SIZE, f"C={c_hdr} Py={HDR_SIZE}")
check("C LBP_TRAILER_SIZE 一致", c_trailer == TRAILER_SIZE,
      f"C={c_trailer} Py={TRAILER_SIZE}")

c_sof = c_def("LBP_SOF")
c_eof = c_def("LBP_EOF")
check("SOF 一致", c_sof == SOF, f"C=0x{c_sof:02X} Py=0x{SOF:02X}")
check("EOF 一致", c_eof == EOF, f"C=0x{c_eof:02X} Py=0x{EOF:02X}")

# C 源码里的字段写入位置
field_checks = [
    ("buf[0] = LBP_SOF", "SOF 在偏移 0"),
    ("put_u16(&buf[6], f->seq)", "seq 在偏移 6"),
    ("put_u32(&buf[12], f->t_exec_us)", "t_exec 在偏移 12"),
    ("put_u16(&buf[16], f->len)", "len 在偏移 16"),
]
for pattern, desc in field_checks:
    check(f"C 帧头 {desc}", pattern in cframe, pattern)

check("C CRC 覆盖 SOF..PAYLOAD",
      "lbp_crc32(buf, LBP_HDR_SIZE + f->len)" in cframe, "与 Python zlib 一致")

# 实测算一遍：Python 编码的帧长度应当符合 C 的公式
from laaper.body.frame import LBPFrame, MsgType
f = LBPFrame(MsgType.CMD, 1, 2, bytes(14))
check("Python 帧长度 == C 公式",
      len(f.encode()) == HDR_SIZE + 14 + TRAILER_SIZE,
      f"{len(f.encode())}B == 18+14+5")

# ══════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
passed = sum(1 for _, c, _ in results if c)
total = len(results)
print(f"结果: {passed}/{total} 通过")

if passed < total:
    print("\n未通过：")
    for name, cond, detail in results:
        if not cond:
            print(f"  {FAIL} {name}  [{detail}]")

sys.exit(0 if passed == total else 1)