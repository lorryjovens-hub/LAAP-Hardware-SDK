"""预测编码感知的验收测试

不测「代码跑不跑」，测「它是不是真的像生命一样感知」。

七个判据：
  1. 静止场景 → 稀疏上行（习惯化：不看的东西就不占带宽）
  2. 有人靠近 → 多模态同时惊讶 → 识别为「人」而不是「距离变化」
  3. 被摸 → 亲昵可供性最高优先 + 余韵让后续更敏感
  4. 只有声音 → 定位不明 → 主动提议扫描
  5. 多传感器一致 → 定位明确 → 不需要探索
  6. 低电量 → 同样的物理变化感受更弱（内感受调制）
  7. 持续扰动 → 惊讶度衰减（方差自适应 = 习惯化）
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from laaper.perception.predictive import make_sensor, PredictiveSensor
from laaper.perception.lifelike import (
    PerceptualField, Action, Interoception, ActivePerceiver,
)

OK, FAIL = "✓", "✗"
results = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  {OK if cond else FAIL} {name}" + (f"  [{detail}]" if detail else ""))


print("=" * 68)
print("预测编码感知 — 行为验收")
print("=" * 68)

# ══════════════════════════════════════════════════════════
# 1. 静止场景：稀疏上行
# ══════════════════════════════════════════════════════════
print("\n[1] 静止场景 → 稀疏上行（习惯化）")
field = PerceptualField()
field.step({"temperature": 22.0, "distance": 100.0, "light": 400.0, "audio": 35.0}, 0.1)
for _ in range(200):   # 20 秒静止
    field.step({"temperature": 22.0 + (math.sin(_ * 0.1) * 0.03),
                "distance": 100.0 + (math.sin(_ * 0.3) * 0.4),
                "light": 400.0 + (math.sin(_ * 0.2) * 2.0),
                "audio": 35.0 + (math.sin(_ * 0.5) * 0.5)}, 0.1)
bw = field.bandwidth_report()
check("静止 20 秒上报率极低", bw["saved_ratio"] > 0.85,
      f"省下 {bw['saved_ratio']*100:.1f}% 带宽")
check("人类可读感知为空（没变化就是没感知）",
      len(field.step({"temperature": 22.0, "distance": 100.0,
                      "light": 400.0, "audio": 35.0}, 0.1).percepts) == 0)

# ══════════════════════════════════════════════════════════
# 2. 有人靠近：多模态融合
# ══════════════════════════════════════════════════════════
print("\n[2] 有人走近 → 识别为「人」而不是「距离变化」")
field = PerceptualField()
# 建立静止基线
for _ in range(50):
    field.step({"temperature": 22.0, "distance": 120.0, "light": 400.0,
                "audio": 32.0, "touch": 0.0}, 0.1)
# 人走近：距离降 + 温度升 + 声音升（人体三特征）
state = None
for i in range(30):
    state = field.step({
        "temperature": 22.0 + i * 0.06,     # 热辐射
        "distance": 120.0 - i * 2.5,        # 走近
        "light": 400.0 - i * 1.0,           # 遮挡变暗
        "audio": 32.0 + i * 0.8,            # 脚步声
        "touch": 0.0,
    }, 0.1)

look = [a for a in state.affordances if a.action == Action.LOOK_AT]
check("产生 LOOK_AT 可供性", len(look) > 0,
      str(look[0]) if look else "无")
check("识别为「人」而非物体", look and "人" in look[0].target,
      look[0].target if look else "-")
check("多模态一起支撑（置信度 > 0.8）",
      look and look[0].confidence > 0.8,
      f"conf={look[0].confidence:.2f}" if look else "-")
check("感知描述里出现人/靠近/热", any("靠近" in p or "热" in p for p in state.percepts),
      " / ".join(state.percepts[:3]))

# ══════════════════════════════════════════════════════════
# 3. 被摸：亲昵优先 + 余韵
# ══════════════════════════════════════════════════════════
print("\n[3] 被摸头 → 亲昵可供性最高 + 余韵")
field = PerceptualField()
for _ in range(50):
    field.step({"touch": 0.0, "temperature": 22.0, "audio": 32.0}, 0.1)
state = field.step({"touch": 1.0, "temperature": 22.1, "audio": 33.0}, 0.1)

aff = state.dominated
check("最优先动作是回应亲昵",
      aff is not None and aff.action == Action.RESPOND_AFFECTION,
      str(aff) if aff else "无")
check("亲昵紧迫度最高", aff is not None and aff.urgency >= 0.9,
      f"urg={aff.urgency:.2f}" if aff else "-")
touch_gain_after = field.intero.gain("touch")
check("触摸余韵拉高了敏感度", touch_gain_after > 1.0,
      f"gain={touch_gain_after:.2f}")

# 余韵衰减：2 秒后应回落
for _ in range(20):
    field.step({"touch": 0.0, "temperature": 22.0, "audio": 32.0}, 0.1)
check("余韵会衰减（不会一直亢奋）",
      field.intero.gain("touch") < touch_gain_after,
      f"2s 后 gain={field.intero.gain('touch'):.2f}")

# ══════════════════════════════════════════════════════════
# 4. 只有声音 → 主动探索
# ══════════════════════════════════════════════════════════
print("\n[4] 只听到声音 → 方位不明 → 主动扫描")
field = PerceptualField()
for _ in range(60):
    field.step({"audio": 30.0, "distance": 120.0, "light": 400.0}, 0.1)
# 突然一声响（其他通道不动）
explored = None
for i in range(10):
    st = field.step({"audio": 30.0 + i * 6.0, "distance": 120.0,
                     "light": 400.0}, 0.1)
    if st.explore:
        explored = st.explore
        break
check("单感官惊讶触发主动探索", explored is not None,
      str(explored) if explored else "未触发")
check("探索方式是扫描（声音方位不明）",
      explored is not None and explored.kind == "scan",
      explored.kind if explored else "-")

# ══════════════════════════════════════════════════════════
# 5. 多传感器一致 → 不需要探索
# ══════════════════════════════════════════════════════════
print("\n[5] 多传感器同时指向同一方向 → 已知道在哪，不必找")
field = PerceptualField()
for _ in range(60):
    field.step({"distance": 120.0, "temperature": 22.0, "audio": 30.0}, 0.1)
explored5 = None
for i in range(10):
    st = field.step({"distance": 120.0 - i * 4.0,
                     "temperature": 22.0 + i * 0.15,
                     "audio": 30.0 + i * 5.0}, 0.1)
    if st.explore:
        explored5 = st.explore
        break

from laaper.perception.predictive import Prediction
ap = ActivePerceiver(gain_threshold=0.8)

def P(name, surprise, err=0.0, obs=0.0):
    return Prediction(name, obs, obs, err, surprise, 1.0, obs, 0.0)

single = {"audio": P("audio", 4.0, 12.0, 50.0)}
multi = {
    "audio": P("audio", 4.0, 12.0, 50.0),
    "distance": P("distance", 4.0, -20.0, 60.0),
    "temperature": P("temperature", 3.5, 2.0, 25.0),
}
g_single = ap.propose(single, now_ms=999999)
g_multi = ap.propose(multi, now_ms=1999999)
check("单传感器 → 提议探索（定位弱）", g_single is not None,
      str(g_single) if g_single else "无")
check("三传感器一致 → 不探索（情境已识别）", g_multi is None,
      "已定位为 person_nearby，无需动" if g_multi is None else f"误触发 {g_multi}")

# ══════════════════════════════════════════════════════════
# 6. 内感受调制
# ══════════════════════════════════════════════════════════
print("\n[6] 低电量 → 同样的物理变化感受更弱（内感受调制）")

def surprise_at_energy(energy: float) -> float:
    f = PerceptualField()
    f.set_body_state(energy=energy)
    for _ in range(40):
        f.step({"temperature": 22.0}, 0.1)
    st = f.step({"temperature": 26.0}, 0.1)
    return st.predictions["temperature"].surprise

s_full = surprise_at_energy(1.0)
s_low = surprise_at_energy(0.1)
check("满电比低电对同一变化更敏锐", s_full > s_low,
      f"满电 {s_full:.2f} vs 低电 {s_low:.2f}")

# ══════════════════════════════════════════════════════════
# 7. 习惯化（方差自适应）
# ══════════════════════════════════════════════════════════
print("\n[7] 持续扰动 → 惊讶度衰减（习惯化）")
sensor = make_sensor("light")
for _ in range(30):
    sensor.step(400.0, 0.1)
first = sensor.step(900.0, 0.1).surprise
surprises = [sensor.step(400.0 + (500 if i % 2 == 0 else 0), 0.1).surprise
             for i in range(40)]
last = sum(surprises[-5:]) / 5

check("首次突变惊讶度很高", first > 3.0, f"first={first:.2f}")
check("持续同幅扰动后惊讶度下降（习惯了）", last < first,
      f"first={first:.2f} → last={last:.2f}")
check("但不会归零（敏感度保留）", last > 0.2, f"last={last:.2f}")

# ══════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════
print("\n" + "=" * 68)
passed = sum(1 for _, c, _ in results if c)
total = len(results)
print(f"结果: {passed}/{total} 通过")

if passed < total:
    print("\n未通过项：")
    for name, cond, detail in results:
        if not cond:
            print(f"  {FAIL} {name}  [{detail}]")

print("\n带宽报告（预测编码的实际收益）：")
import random
random.seed(42)
f = PerceptualField()
for i in range(300):
    # 加真实传感器噪声（量化抖动）
    f.step({"temperature": 22.0 + math.sin(i * 0.1) * 0.2 + random.gauss(0, 0.04),
            "distance": 100.0 + math.sin(i * 0.2) * 2.0 + random.gauss(0, 1.0),
            "light": 400.0 + math.sin(i * 0.15) * 8.0 + random.gauss(0, 5.0),
            "audio": 35.0 + math.sin(i * 0.4) * 1.5 + random.gauss(0, 1.5),
            "touch": 0.0 + abs(random.gauss(0, 0.01))}, 0.1)
bw = f.bandwidth_report()
print(f"  采样 {bw['samples']} 次 → 上行 {bw['reports']} 次 "
      f"（省 {bw['saved_ratio']*100:.1f}%）")
for n, r in bw["per_sensor"].items():
    print(f"    {n:12s} 上报率 {r*100:5.1f}%")

sys.exit(0 if passed == total else 1)