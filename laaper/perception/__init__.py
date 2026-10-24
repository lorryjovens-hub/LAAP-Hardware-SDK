"""感知层

两套机制并存：

## 1. 感官编码（encoder + fusion）—— 把物理量变成体验质

    温度 50°C → "滚烫"(valence=-1.0)
    跨模态融合 → "火" → 建议行动

这一套回答的是「这是什么感受」。

## 2. 预测编码（predictive + lifelike）—— 让感知像生命

    predictive: 预测世界，只报告预测失败的部分（惊讶）
    lifelike:   可供性 + 主动探索 + 内感受调制 + 余韵

这一套回答的是「什么变了、我该做什么」。

---

两套是互补的：
  编码层给「质感」（热/烫/刺眼）
  预测层给「动态」（变热了/有人靠近/该看一眼）

用法：

```python
from laaper.perception import PerceptualField

field = PerceptualField()
state = field.step({"temperature": 32.0, "distance": 45.0}, dt=0.1)

if state.dominated:
    await act(state.dominated)       # 可供性：该做什么
if state.explore:
    await look(state.explore.direction)  # 主动感知：该看哪
print(state.percepts)                # 人类可读："变热了" / "有东西靠近"
```
"""
from laaper.perception.encoder import (
    SensoryEncoder,
    SensoryModality,
    QualiaType,
    Qualia,
    NeuralCode,
)
from laaper.perception.fusion import (
    CrossModalFusion,
    FusedPerception,
)

# 预测编码（生命感知）
from laaper.perception.predictive import (
    Prediction,
    PredictiveSensor,
    SensorProfile,
    DEFAULT_PROFILES,
    make_sensor,
)
from laaper.perception.lifelike import (
    PerceptualField,
    FieldState,
    Affordance,
    Action,
    ExploreAction,
    ActivePerceiver,
    Interoception,
)

__all__ = [
    # 感官编码
    "SensoryEncoder",
    "SensoryModality",
    "QualiaType",
    "Qualia",
    "NeuralCode",
    # 跨模态融合
    "CrossModalFusion",
    "FusedPerception",
    # 预测编码
    "Prediction",
    "PredictiveSensor",
    "SensorProfile",
    "DEFAULT_PROFILES",
    "make_sensor",
    # 生命感知场
    "PerceptualField",
    "FieldState",
    "Affordance",
    "Action",
    "ExploreAction",
    "ActivePerceiver",
    "Interoception",
]
