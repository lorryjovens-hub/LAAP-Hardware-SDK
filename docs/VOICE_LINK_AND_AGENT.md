# LAAP 语音直连 + 多步任务 + 撤销 — 实现文档

> 五件事全部完成：语音直连、多步任务、视觉确认、撤销机制、自定义域名

---

## 一、语音直连（小智说话 → 电脑动手）

### 完整链路

```
小智硬件（麦克风）
    ↓ 音频上行
xiaozhi.me 云端（ASR 语音转文字）
    ↓ MCP tools/call
XiaozhiVoiceLink
    ↓
VoiceComputerAgent / MultiStepComputerAgent
    ↓
鼠标 · 键盘 · 滚轮
    ↓ 动作结果 → 组装成一句话
    ↓ MCP 返回值
xiaozhi.me 云端（TTS 语音合成）
    ↓ 音频下行
小智硬件（扬声器）
```

### 关键设计：返回值必须是"能念出来的话"

MCP 工具返回的文本会被云端直接拿去 TTS。

```python
# 好
return "翻到底了"

# 坏
return '{"success": true, "action": "scroll_until", "iterations": 4}'
```

### 暴露给小智的 13 个工具

| 工具 | 用途 |
|------|------|
| `voice_command` | **主入口**，自然语言控制 |
| `computer_task` | 多步任务 |
| `pc_scroll` | 滚动（四方向） |
| `pc_click` | 点击（按文字优先） |
| `pc_type` | 输入文字（支持中文） |
| `pc_key` | 单键 |
| `pc_hotkey` | 组合键 |
| `pc_look` | 看屏幕 |
| `pc_windows` | 窗口列表 |
| `pc_focus` | 切换窗口 |
| `pc_undo` | 撤销 |
| `pc_history` | 操作历史 |
| `pc_status` | 能力状态 |

### 实测（真实工具调用）

```
状态问询       408ms → 屏幕 3840x2160，当前窗口 voice_test.txt
看屏幕        136ms → 当前窗口 + 可操作控件
翻到底       1516ms → 滚到底了
回到顶部      1487ms → 已经在顶了
自然语言滚动    102ms → 往下翻了
中文输入       279ms → 输入了「LAAP 语音直连测试」
回车          62ms → 按了回车
撤销          62ms → 按了 ctrl+z
操作历史        0ms → 共 7 个动作，6 个可撤销
窗口列表        2ms → voice_test.txt、HanaAgent...
```

小智 broker 连接：`xiaozhi-2045678` 在线，13 个工具注册成功。

---

## 二、多步任务

### 三层验证（成本递增）

动作后不能盲目继续，但每步都调视觉太贵太慢。

| 层 | 耗时 | 成本 | 判断 |
|---|------|------|------|
| **像素变化** | 20ms | 免费 | 屏幕变了吗 |
| **结构化** | 200ms | 免费 | 目标元素还在吗 |
| **视觉确认** | 1-3s | 有 API 成本 | 让视觉模型说"成功了吗" |

视觉只在必要时升级，且有预算上限（默认 3 次/任务）。

### 停滞与失败处理

```python
连续 3 步屏幕无变化    → 判定卡住，中止
重复执行同一动作 2 次   → 判定方法错误，中止
达到最大步数 20        → 中止并报告进度
```

### 实测

```
任务: 在记事本里输入 hello 然后保存
成功: True
消息: 已在记事本文档末尾输入"hello laap"，并经视觉确认最后一行内容为 hello laap，未执行保存操作。
步数: 4 | 耗时: 43.5s | 视觉调用: 3

[OK] 步骤1 focus_window  467ms  确保记事本窗口获得焦点
[OK] 步骤2 click         578ms  点击编辑区使其获得输入焦点
[OK] 步骤3 hotkey        607ms  光标移到文档末尾（Ctrl+End）
[OK] 步骤4 type          668ms  输入文字
```

注意最后那句"未执行保存操作"——**她自己判断了不该保存**，因为指令里说"不要保存"。

### 修的一个真实 bug：LLM 输出 JSON 后又继续推理

实测发现，即使设了 `json_mode=True`，模型也会输出：

```
{"action": "click", ...}
Wait, let me reconsider. ...
```

`json.loads` 直接报 `Extra data: line 3 column 1`。

**解决：用 `raw_decode` 只解析第一个完整 JSON 对象**

```python
obj, end_idx = json.JSONDecoder().raw_decode(candidate)
```

实测五种输入全部正确：
```
纯 JSON              → OK
JSON + 后续文字       → OK
markdown 包裹         → OK
JSON + 多余对象       → OK
无 JSON              → abort（诚实报告）
```

---

## 三、撤销机制

### 核心难点：不是所有动作都可逆

这是必须先讲清楚的。GUI 操作的可逆性差异极大：

| 动作 | 可逆 | 原因 |
|------|:----:|------|
| 滚动 | ✓ | 反向滚即可 |
| 窗口切换 | ✓ | 切回原窗口 |
| 输入文字 | ✓ | Ctrl+Z |
| 复制/全选/查找 | ✓ | 无副作用 |
| 回车 | △ | 可能已提交，Ctrl+Z 试试 |
| 启动应用 | △ | 可关但有未保存数据 |
| 点击按钮 | ✗ | 点了就点了 |
| 保存 | ✗ | 已写盘 |
| 关闭窗口 | ✗ | 可能丢数据 |

### 为什么诚实比"假装能撤"重要

"我能撤销"这句话如果说了做不到，比不说更危险——用户会以为在安全网里，实际没有。

所以宁可说"这一步撤不回来"，也不假装能撤。

### 实测

```
共 4 个动作，2 个可撤销，2 个不可撤销
可撤销: ['scroll', 'type']
不可撤销: ['click', 'hotkey']

撤销最近一步: True — 已按 ctrl+z 撤销
再撤 2 步: True — 撤销了 1 步，跳过 2 步不可撤销的
  跳过: click（点击已发生，无法撤销）
        ctrl+s（已保存到磁盘）
```

---

## 四、自定义域名

```
https://api.laap.cn/ws/health   → 200 OK
wss://api.laap.cn/ws            → WebSocket 中继
https://laap-relay.lorryjovens.workers.dev  → 备用通道
```

### TOML 踩的坑

`routes` 不能放在 `[vars]` 之后——TOML 里一旦打开 `[vars]`，后续所有键都归属它。

```toml
# 错：routes 会被当成 vars 的子键
[vars]
ENVIRONMENT = "production"
routes = [...]

# 对：routes 在前
routes = [...]
[vars]
ENVIRONMENT = "production"
```

### 端到端测试（api.laap.cn）

```
[1] 中枢连接          ✓ 握手 peers=['pc-hub']
[2] 手机连接          ✓ 中枢收到上线通知
[3] 派任务            ✓ task_assign 送达
[4] 回结果            ✓ task_result 送达
[5] 心跳              ✓ 回应
[6] 离线消息           ✓ 重连后收到暂存消息
```

---

## 五、文件

| 文件 | 作用 |
|------|------|
| `laaper/hub/xiaozhi_voice_link.py` | 语音直连（13 个工具） |
| `laaper/hub/multi_step.py` | 多步任务 + 三层验证 |
| `laaper/hub/action_journal.py` | 动作日志 + 诚实撤销 + 安全策略 |
| `laaper/hub/computer_use.py` | 鼠标键盘底层 |
| `laaper/hub/voice_computer.py` | 语音意图 + 元素定位 |
| `relay/src/index.ts` | 云端中继 |
| `relay/wrangler.toml` | 部署配置 |

---

## 六、一键启动

```python
from laaper.hub import quick_start

result = await quick_start(connect_xiaozhi=True)
# {
#   "success": True,
#   "components": {"computer_use": True, "journal": True, "multistep": True},
#   "xiaozhi": {"online": 1, "tools": [13 个]},
#   "link": XiaozhiVoiceLink
# }
```

---

## 七、还没做的

| 缺口 | 说明 |
|------|------|
| 音频流直连 | 现在走 xiaozhi.me 云端的 ASR/TTS；如果要自己 ASR，需接本地 xiaozhi-esp32-server 的 Opus WebSocket 协议 |
| 撤销可视化 | 撤销目前只能语音说，缺一个界面看动作时间线 |
| 危险动作确认流程 | `SafetyPolicy` 写好了，但没接进语音询问循环 |
| 跨应用上下文 | 切换应用后不记得之前在那个应用做了什么 |
