# ok-kes 软件需求文档 (SRD)

## 1. 项目概述

ok-kes 是一个基于 ok-py 框架的《卡厄思梦境》游戏自动化辅助工具。通过 OCR 识别游戏画面并模拟点击/按键操作，实现游戏内各项功能的自动化。

### 1.1 项目定位
- 目标用户：卡厄思梦境玩家
- 运行环境：Windows 11，Python 3.12，miniconda3/oknikke 环境
- 框架依赖：ok-script（基于 PySide6 的 GUI 自动化框架）

### 1.2 技术栈

| 组件 | 技术选型 |
|------|---------|
| GUI 框架 | ok-script (PySide6 + qfluentwidgets) |
| OCR | onnxocr-ppocrv5 |
| 繁简转换 | OpenCC |
| 图像处理 | OpenCV + OpenVINO |
| 云端存储 | Supabase (PostgreSQL + REST API) |
| 版本控制 | Git + GitHub |

---

## 2. 功能模块

### 2.1 自动卡厄思模式 (ChaosMode)

**文件**: `ok_tasks/ChaosMode.py`, `ok_tasks/utils_chaos.py`

#### 2.1.1 功能概述
自动运行游戏内卡厄思模式副本，处理战斗、路线选择、卡牌操作等完整流程。

#### 2.1.2 核心逻辑
每秒触发一次 `run()` 方法：
1. OCR 识别当前画面文本，繁体转简体
2. 依次尝试约 50 个页面处理函数（`PAGE_HANDLERS` 列表）
3. 命中某一页面则执行对应操作并结束本轮循环

#### 2.1.3 页面处理函数类型

| 类别 | 函数示例 | 功能 |
|------|----------|------|
| 通用操作 | `handle_confirm`, `handle_next_step` | 确认、下一步等通用按钮点击 |
| 战斗相关 | `handle_battle_auto_check` | 检测自动战斗开关，检查手牌数 |
| 路线选择 | `handle_route_selection` | 按优先级识别节点类型并选择路线 |
| 卡牌操作 | `handle_select_card`, `handle_remove`, `handle_flash` | 移除/闪光/复制卡牌 |
| 商店 | `handle_shop` | 德朗商店购买卡牌 |
| 休息 | `handle_rest` | 免费休息恢复 |
| 事件 | `handle_event_task` | 事件任务选择 |
| 面具 | `handle_mask_card`, `handle_chaos_mask_engraving` | 面具卡牌选择与刻印 |
| 精神/治疗 | `handle_mental_breakdown`, `handle_trauma_center` | 精神崩溃治疗 |
| 探险结算 | `handle_expedition_result` | 记录胜负，更新胜率统计 |
| 奖励 | `handle_chaos_reward_claim`, `handle_chaos_reward_settlement` | 领取奖励 |

#### 2.1.4 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| 任务优先级 | 列表 | ["复制","信用点增加","移除"] | 事件任务选择优先级 |
| 拉黑任务 | 列表 | ["咒术卡牌","压力"] | 事件任务过滤，描述包含关键词则不选 |
| 闪光优先级 | JSON | {"剑雨":["生成2张极光剑"]} | 卡牌闪光效果优先级 |
| 移除卡牌列表 | 列表 | ["剑幕","剑光",...] | 移除操作的目标卡牌 |
| 闪光卡牌列表 | 列表 | ["展开极光","剑雨",...] | 闪光操作的目标卡牌 |
| 复制卡牌列表 | 列表 | ["展开极光","剑雨",...] | 复制操作的目标卡牌 |
| 路线优先级 | 列表 | ["休息","事件","小怪","boss"] | 路线节点选择顺序 |
| 优先使用金币治疗 | 布尔 | True | 创伤中心治疗方式 |
| 治疗崩溃 | 布尔 | True | 精神崩溃时去创伤中心 |
| 优先移除基础牌 | 布尔 | True | 移除时优先选基础牌 |
| 进入商店 | 布尔 | False | 路线中是否进商店 |
| 保留存档 | 布尔 | False | 是否保留存储数据 |
| 领取奖励(只使用验证卡) | 布尔 | False | 奖励领取策略 |
| 指定面具卡牌 | 字符串 | "丢弃最多2张卡牌" | 优先选择的面具效果 |
| 面具卡牌刻印 | 字符串 | "自身攻击卡牌伤害总量提升30%" | 优先选的刻印效果 |
| 只打第一层 | 布尔 | False | 通过一次最终boss后退出的图层 |

---

### 2.2 自动出击模式 (SortieMode)

**文件**: `ok_tasks/SortieMode.py`, `ok_tasks/utils_sortie.py`

#### 2.2.1 功能概述
自动运行游戏内出击模式副本，包括手牌识别与出牌、主战员选择等。

#### 2.2.2 核心逻辑
与 ChaosMode 相同，使用 `PAGE_HANDLERS` 列表驱动页面处理。

#### 2.2.3 特色功能

**手牌识别与出牌** (`handle_battle_page`):
- OCR 识别手牌区域卡牌名
- 按键识别（卡牌上的数字键位）
- 出牌卡手检测（连续 3 轮同一张牌未出掉则兜底出牌）
- EP 能量检测（满能量时释放 Ego 技能）
- 帧卡住检测与恢复

**主战员选择** (`handle_member_selection`, `handle_battle_member_config`):
- 按优先级选择主战员
- 支持拉黑列表（跳过指定角色）
- 刷新候选槽位
- 出战主战员选择（战斗前配置）

**卡牌操作**:
- `handle_battle_hand_select`: 战斗中手牌选择
- `handle_get_card`: 获得卡牌页面按优先级选择
- `handle_draw_card_event`: 抽牌事件选择
- `handle_discard_hand_card`: 丢弃手牌
- `handle_curiosity_activate`: 尼娅的好奇心卡牌选择
- `handle_extra_card_use`: 额外使用卡牌

**其他**:
- `handle_boss_selection`: 随机选择首领
- `handle_rest_sortie`: 休息区闪光/休息选择
- `handle_sortie_reward_settlement`: 奖励结算
- `handle_rational_supply`, `handle_ether_supply`: 资源补充

#### 2.2.4 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| 路线优先级 | 列表 | ["休息","事件","小怪","boss"] | 节点选择顺序 |
| 主战员优先级 | 列表 | ["米卡","尼娅",...] | 会合主战员选择 |
| 出战主战员优先级 | 列表 | ["海德玛丽","九",...] | 战斗前主战员配置 |
| 获得卡牌优先级 | 列表 | ["展开极光","剑雨",...] | 获得卡牌时的选择 |
| 出牌优先级 | 列表 | ["剑雨","水之源",...] | 战斗中出牌顺序 |
| 丢弃卡牌优先级 | 列表 | ["展开极光",...] | 丢弃操作的目标 |
| 任务优先级 | 列表 | ["选取随机3条命运",...] | 事件任务选择 |
| 拉黑任务 | 列表 | ["咒术卡牌","压力"] | 事件任务过滤 |
| 拉黑主战员 | 列表 | ["黛安娜","阿黛尔海特"] | 跳过的角色 |
| 移除/复制/闪光卡牌列表 | 列表 | ... | 各类卡牌操作的目标 |
| 跳过非优先级卡牌 | 布尔 | True | 获得卡牌时跳过非优先级 |
| 优先移除基础牌 | 布尔 | True | 移除时优先基础牌 |
| 领取奖励 | 布尔 | False | 奖励领取开关 |
| 进入商店 | 布尔 | False | 路线中进商店 |
| 只打第一层 | 布尔 | True | 通过最终boss后退出 |
| 生命值大于多少优先闪光 | 字符串 | "60" | HP 百分比阈值 |

---

### 2.3 配置同步与热门配置

**文件**: `ok_tasks/config_sync.py`, `ok_tasks/config_io.py`

#### 2.3.1 上传机制
- **触发方式**: 模式运行时每 300 秒（5 分钟）自动检查上传
- **最低场数**: 2 场（`MIN_ROUNDS = 2`，可配置）
- **上传内容**: 配置 base64 + 胜率 + 版本号 + 游戏语言 + 匿名用户 hash
- **不上传**: 个人身份信息、游戏账号、截图、IP 地址

#### 2.3.2 匿名用户标识
`_get_user_hash()`: 组合 MAC 地址 + 主机名 + 用户名，取 SHA256 前 16 位。

#### 2.3.3 云端存储 (Supabase)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT | 自增主键 |
| mode | TEXT | "chaos" 或 "sortie" |
| config_b64 | TEXT | 配置的 base64 编码 |
| config_ver | TEXT | 版本号 |
| game_lang | TEXT | 游戏语言 |
| win_rate | REAL | 胜率 (0.0~1.0) |
| total_rounds | INTEGER | 总战斗场数 |
| user_hash | TEXT | 匿名用户标识 |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |

**唯一约束**: `(user_hash, mode, config_b64)` — 同一用户同一配置只保留一条记录

#### 2.3.4 热门配置展示
- 排序方式：按平均胜率降序 / 按使用人数降序
- 展示上限：20 条
- 展示信息：排名、胜率、使用人数、游戏语言、版本

#### 2.3.5 配置导入导出
- `_export_config_to_text()`: 导出为 base64 编码
- `_import_config_from_text()`: 从 base64 导入（合并到当前配置）
- 按钮功能：所有配置操作在 UI 的 config 按钮中完成

---

### 2.4 通用功能

#### 2.4.1 多语言支持
- 使用 OpenCC（繁转简）统一 OCR 文本处理
- i18n 通过 `.po` / `.mo` 文件实现 UI 翻译
- 全局配置「游戏语言」支持：简体中文、繁体中文、日文、英文

#### 2.4.2 卡牌识别增强（剑雨合并）
在 `select_card` 中，如果 OCR 将"剑雨"识别为分离的"剑"和"雨"两个单字框，自动合并为一个 `Box(name="剑雨")`，删除旧的单字框，使后续匹配能正确识别。

#### 2.4.3 帧卡住检测
`is_frame_stuck()`: 基于像素变化检测画面是否卡住（连续 30 秒变化比例 < 0.5%），用于战斗恢复和日志输出。

---

## 3. 架构设计

### 3.1 整体架构

```
main.py (入口)
  └── ok.OK(config) ──→ GUI 启动
        ├── ChaosMode (TriggerTask)
        │     └── run() → 遍历 utils_chaos.PAGE_HANDLERS
        ├── SortieMode (TriggerTask)
        │     └── run() → 遍历 utils_sortie.PAGE_HANDLERS
        └── 全局配置 (Settings)
              ├── 游戏语言
              └── 配置上传开关
```

### 3.2 任务调度
- 继承 `ok.TriggerTask`，每秒触发一次 `run()`
- 每帧 OCR → 繁转简 → 依次尝试页面处理函数 → 命中即返回
- 帧末尾检查是否需要上传配置

### 3.3 互斥机制
- 开启 ChaosMode 时自动禁用 SortieMode
- 开启 SortieMode 时自动禁用 ChaosMode

### 3.4 数据流

```
用户操作配置 → 保存到 configs/ 目录 JSON 文件
      ↓
每 5 分钟 → 读取配置 → base64 编码 → 上传到 Supabase
      ↓
热门配置按钮 → 从 Supabase 获取 → 聚合计算 → 展示列表 → 用户选择 → 导入配置
```

---

## 4. 配置项总览

### 4.1 全局配置 (src/config.py)

| 配置分类 | 配置项 | 类型 | 默认值 |
|----------|--------|------|--------|
| 游戏语言 | 游戏语言 | 下拉框 | 简体中文 |
| 配置上传 | 是否上传配置 | 开关 | True |

### 4.2 卡厄思模式配置（18 项）

任务优先级、拉黑任务、闪光优先级、移除卡牌列表、闪光卡牌列表、复制卡牌列表、路线优先级、优先使用金币治疗、治疗崩溃、优先移除基础牌、进入商店、保留存档、领取奖励(只使用验证卡)、指定面具卡牌、面具卡牌刻印、只打第一层、导出配置、导入配置、热门配置

### 4.3 出击模式配置（20 项）

路线优先级、主战员优先级、出战主战员优先级、获得卡牌优先级、移除卡牌列表、复制卡牌列表、闪光卡牌列表、领取奖励、出牌优先级、丢弃卡牌优先级、进入商店、卡牌奖励优先级、任务优先级、拉黑任务、拉黑主战员、跳过非优先级卡牌、优先移除基础牌、生命值大于多少优先闪光、只打第一层、导出配置、导入配置、热门配置

---

## 5. 环境要求

### 5.1 运行环境
- 操作系统：Windows 11
- Python：3.12 (miniconda3/oknikke)
- 游戏窗口：16:9 分辨率，最低 1280x720，推荐 1920x1080
- 网络：可选（上传配置及获取热门配置需要）

### 5.2 依赖

```
ok-script>=1.0.163
onnxocr-ppocrv5>=0.0.18
OpenCC>=1.2.0
opencv-python>=4.12.0
openvino>=2026.0.0
requests (用于配置同步)
```

### 5.3 声明的 OCR 库配置

```python
'ocr': {
    'lib': 'onnxocr',
    'auto_simplify': True,
    'params': {
        'use_openvino': True,
    }
}
```

### 5.4 Windows 交互配置

```python
'interaction': ['Pynput', 'PostMessage', 'Genshin', 'PyDirect', 'ForegroundPostMessage']
'capture_method': ['WGC', 'BitBlt_RenderFull', 'BitBlt']
```

---

## 6. 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.3.5 | 2026-07-22 | 新增热门配置同步功能；提高剑雨卡牌识别率；新增拉黑任务功能；代码去重优化 |
| v1.3.4 | - | - |
| ... | - | - |