# F1 Manager 2024 AI Strategy System — 实施计划

## 项目目标
构建一个实时 AI 策略助手，在 F1 Manager 2024 比赛期间监控存档数据，分析赛事状态，并提供最优策略建议。

---

## Phase 1: 数据管道 (Data Pipeline) — 基础设施
**目标：** 能够从游戏中提取实时数据

### Task 1.1: 存档文件解包器
- 从 scarlet-dynasty-f1m24 提取 `savefile_codec.py`
- 实现 .sav → SQLite 解包功能
- 测试不同存档的兼容性

### Task 1.2: 文件监控系统
- 使用 Python `watchdog` 监控存档目录
- 检测 .sav 文件变化（创建/修改）
- 自动触发解包和数据库读取

### Task 1.3: 数据访问层
- 封装 SQLite 查询为 Python API
- 实现所有核心表的查询函数：
  - `get_race_positions()` — 实时排名
  - `get_tyre_status(car_id)` — 轮胎状态
  - `get_weather()` — 天气数据
  - `get_lap_times(car_id)` — 圈速历史
  - `get_pit_stops(car_id)` — 进站记录
  - `get_safety_car_status()` — 安全车状态
  - `get_fuel_level(car_id)` — 燃油水平
  - `get_ers_status(car_id)` — ERS 状态
  - `get_damage(car_id)` — 损伤状态

---

## Phase 2: 策略引擎 (Strategy Engine) — 核心算法
**目标：** 基于数据计算最优策略

### Task 2.1: 轮胎衰退模型
- 基于轮胎温度、圈数、赛道特性建模
- 预测轮胎剩余寿命（圈数）
- 计算不同化合物的性能曲线

### Task 2.2: 进站窗口优化器
- 输入：总圈数、当前圈、轮胎状态、维修区时间损失
- 输出：最优进站圈数、推荐轮胎选择
- 考虑因素：
  - 轮胎衰退 vs 新胎优势
  - 出站后的位置变化（traffic）
  - 安全车概率加权

### Task 2.3: 天气响应策略
- 监控天气变化（雨量、赛道湿度）
- 预测天气趋势
- 干胎 ↔ 雨胎切换时机

### Task 2.4: 安全车策略
- 检测安全车/VSC出动
- 计算免费进站窗口
- 评估进站 vs 留在赛道的收益

### Task 2.5: ERS 优化
- 根据赛道特性优化能量回收/部署
- 超车时的 ERS boost 策略
- 防守时的 ERS 管理

### Task 2.6: 对手建模
- 追踪对手进站模式
- 预测 undercut/overcut 窗口
- 识别策略性超车机会

---

## Phase 3: 展示层 (Presentation) — 用户界面
**目标：** 清晰展示策略建议

### Task 3.1: 实时仪表盘 (终端 UI)
- 使用 Rich/Textual 构建终端界面
- 显示：
  - 🏁 实时排名（位置变化用箭头表示）
  - 🛞 轮胎状态（颜色编码：绿/黄/红）
  - 🌦️ 天气信息
  - ⏱️ 圈速对比
  - 📊 策略建议（高亮显示）

### Task 3.2: 策略通知系统
- 关键时刻弹出建议：
  - "⚠️ 轮胎寿命剩余 5 圈，建议第 32 圈进站"
  - "🌧️ 预计 3 圈后下雨，考虑提前换雨胎"
  - "🚨 安全车出动！免费进站窗口！"
  - "💡 对手 Hamilton 刚进站，undercut 窗口打开"

### Task 3.3: 赛后分析报告
- 比赛结束后生成分析报告
- 策略执行效果评估
- 改进建议

---

## Phase 4: 增强功能 — 高级特性
**目标：** 提升策略准确度和用户体验

### Task 4.1: 历史数据学习
- 保存每场比赛的数据
- 学习不同赛道的最优策略模式
- 建立策略知识库

### Task 4.2: FastF1 真实数据校准
- 使用真实 F1 数据校准游戏模型
- 对比游戏 vs 现实的轮胎衰退曲线
- 提升预测准确度

### Task 4.3: 蒙特卡洛模拟
- 对多种策略进行模拟
- 考虑随机因素（安全车、天气变化、事故）
- 输出概率化的策略建议

---

## 文件结构

```
f1-manager-2024-strategy-ai/
├── RESEARCH_REPORT.md          # 研究报告
├── PLAN.md                     # 本文件
├── README.md                   # 项目说明
├── requirements.txt            # 依赖
├── config.yaml                 # 配置（存档路径等）
│
├── core/                       # 核心模块
│   ├── __init__.py
│   ├── save_reader.py          # .sav 解包器
│   ├── file_watcher.py         # 文件监控
│   ├── db_accessor.py          # 数据库访问层
│   └── models.py               # 数据模型
│
├── strategy/                   # 策略引擎
│   ├── __init__.py
│   ├── tyre_model.py           # 轮胎衰退模型
│   ├── pit_optimizer.py        # 进站窗口优化
│   ├── weather_strategy.py     # 天气策略
│   ├── safety_car.py           # 安全车策略
│   ├── ers_optimizer.py        # ERS 优化
│   └── opponent_tracker.py     # 对手追踪
│
├── display/                    # 展示层
│   ├── __init__.py
│   ├── dashboard.py            # 实时仪表盘
│   ├── notifications.py        # 通知系统
│   └── report.py               # 赛后报告
│
├── data/                       # 数据文件
│   ├── tracks.json             # 赛道参考数据
│   ├── tyre_compounds.json     # 轮胎化合物数据
│   └── history/                # 历史比赛数据
│
└── tests/                      # 测试
    ├── test_save_reader.py
    ├── test_strategy.py
    └── test_integration.py
```

---

## 实施顺序

```
Phase 1 (Week 1-2): 数据管道
  → 先能读数据
  → 里程碑：能看到实时比赛数据

Phase 2 (Week 3-4): 策略引擎
  → 核心算法
  → 里程碑：能输出基本策略建议

Phase 3 (Week 5): 展示层
  → 用户界面
  → 里程碑：可用的策略助手

Phase 4 (Week 6+): 增强功能
  → 持续改进
  → 里程碑：高级策略分析
```

---

## 关键技术参考

| 工具 | 链接 | 用途 |
|------|------|------|
| savefile_codec.py | github.com/guest329/scarlet-dynasty-f1m24 | .sav 解包/重打包 |
| DatabaseEditor | github.com/IUrreta/DatabaseEditor | 存档编辑参考 |
| FastF1 | github.com/theOehrly/Fast-F1 | 真实 F1 数据 |
| schema_dump.txt | 同 scarlet-dynasty-f1m24 | 完整数据库结构 |

---

## 开始下一步？

准备好就开始 Phase 1！
