# F1 Manager 2024 AI Strategy System — 深度研究报告

## 一、可行性结论：✅ 完全可行

F1 Manager 2024 的存档系统使用 **SQLite 数据库**（嵌入在 .sav 文件中），包含 **316 个数据表**，涵盖赛车模拟的所有维度。这意味着我们可以通过解析存档文件来获取近乎实时的赛事数据。

---

## 二、核心技术发现

### 2.1 存档文件结构
- 游戏存档 (.sav) = GVAS UE5 头部 + zlib 压缩的 SQLite 数据库
- 解压后得到 `main.db`（主数据库）+ 2个辅助数据库
- 纯 Python 可以解包/重打包（已有开源实现）

### 2.2 关键数据表（316个表中的核心）

#### 🏎️ 实时赛车数据
| 表名 | 描述 | 关键字段 |
|------|------|----------|
| `Save_RaceSimCars` | 赛车实时状态 | Fuel, RacePosition, TotalRaceTime, DRSState, SafetyCar状态 |
| `Save_RaceSimCars_Parts` | 轮胎&损伤 | 4个轮胎温度/状态, 前翼/后翼/侧箱/地板/悬挂损伤等级 |
| `Save_RaceSimCars_Strategy` | 策略执行 | TyreWearStrategy, ErsStrategy, OvertakeStrategy, DefenceStrategy |
| `Save_RaceSimCars_PitStop` | 进站数据 | PitStopState, 各阶段时间, 换胎选择, 失误概率 |
| `Save_RaceSimCars_Misc` | ERS&暖胎 | ErsBatteryCharge, ErsDeployAmount, TyreWarmupProgress |
| `Save_RaceSimCars_Overtake` | 超车模拟 | OvertakeActive, SuccessRoll, DefenderCar, DefenceType |
| `Save_RaceSimCars_Incident` | 事故数据 | IncidentType, ImpactSpeed, RecoveryState |

#### 🌦️ 天气数据
| 表名 | 描述 | 关键字段 |
|------|------|----------|
| `Save_WeatherHistory` | 天气历史 | Rain, WaterOnTrack, AmbientTemp, TrackTemp, WeatherState |

#### ⏱️ 计时数据
| 表名 | 描述 | 关键字段 |
|------|------|----------|
| `Save_TimingManager_Laps` | 圈速记录 | CarIndex, Lap, LapTimeMS, RaceTime |
| `Save_TimingManager_Sectors` | 段速 | 分段计时 |

#### 🛞 轮胎管理
| 表名 | 描述 | 关键字段 |
|------|------|----------|
| `Save_CarTyreAllocation` | 轮胎分配 | 各轮胎磨损(FrontLeft/Right, BackLeft/Right), 预估圈数 |
| `Save_PlayerStrategyStints` | 玩家策略 | TyreType, PitWindowStart/End, OptimalPitLap |

#### 🚨 赛事控制
| 表名 | 描述 | 关键字段 |
|------|------|----------|
| `Save_RaceSimManager` | 比赛管理 | SimTime, SafetyCarState, RaceEventFlags |
| `Save_SafetyCarDeploymentsSummary` | 安全车 | SafetyCarDeployments, VSCDeployments |
| `Save_RaceControl` | 赛事控制 | 旗帜/处罚 |
| `Save_DriverCommands` | 车手指令 | RacePaceStrategy, ERSStrategy, LiftAndCoast |

#### 📊 静态参考数据
| 表名 | 描述 | 关键字段 |
|------|------|----------|
| `Races_Tracks` | 赛道数据 | Laps, TrackLength, SafetyCarChance, PitLaneTimeLoss |
| `Races_Strategies` | AI策略模板 | StartingLap, EndingLap, TyreSet, PitWindowStart/End |
| `Staff_DriverData` | 车手属性 | Aggression, Improvability, Marketability |
| `Parts_Designs` | 零件设计 | 各项性能指标 |
| `Parts_Enum_Stats` | 性能指标 | 16项车辆统计 |

---

## 三、实时数据获取方案

### 方案：存档文件监控 + SQLite 解析

```
[游戏运行] → [.sav 文件写入] → [文件监控] → [解压] → [SQLite 查询] → [AI 分析] → [策略建议]
```

**技术细节：**
1. 游戏在比赛期间会定期写入存档
2. 使用 Python `watchdog` 监控存档目录
3. 使用 `savefile_codec.py` 解压 .sav → SQLite
4. 用 `sqlite3` 查询实时数据
5. AI 引擎分析并生成策略建议

**数据刷新频率：** 约每圈或每次重大事件后更新

### 参考工具
- **IUrreta/DatabaseEditor** (165⭐, 59🍴) — 最成熟的 F1 Manager 存档编辑器
- **scarlet-dynasty-f1m24** — 纯 Python .sav 解包/重打包库 (GPL-3.0)

---

## 四、策略引擎可以分析什么

### 4.1 赛前策略
- 基于赛道数据（圈数、安全车概率、维修区时间损失）计算最优进站窗口
- 基于天气预报选择轮胎策略（1停 vs 2停 vs 3停）
- 基于对手策略预测应对方案

### 4.2 实时策略调整
- **轮胎管理：** 监控4轮温度/磨损，预测最佳换胎时机
- **燃油管理：** 根据剩余燃油和圈数调整引擎模式
- **ERS管理：** 优化能量回收/部署策略
- **超车/防守：** 根据DRS可用性和轮胎差异判断进攻时机
- **安全车策略：** 安车出动时立即计算是否免费进站

### 4.3 对手分析
- 追踪所有车辆的位置变化、进站时间、轮胎选择
- 预测undercut/overcut窗口
- 识别对手弱点（轮胎衰退快、ERS不足）

---

## 五、外部参考数据源（增强策略准确度）

| 数据源 | 用途 |
|--------|------|
| **FastF1** (Python库, 5.2⭐) | 真实F1遥测数据，用于校准游戏模型 |
| **OpenF1 API** | 实时F1 API数据 |
| **Ergast API** | 历史F1比赛结果 |

---

## 六、技术栈

- **Python 3.10+** — 核心语言
- **watchdog** — 文件系统监控
- **sqlite3** — 数据库查询（内置）
- **savefile_codec.py** — .sav 解包（从 scarlet-dynasty-f1m24 提取）
- **FastF1** — 真实F1数据参考
- **scikit-learn / numpy** — 策略优化计算
- **Rich / Textual** — 终端UI展示策略建议

---

## 七、风险与限制

| 风险 | 严重度 | 缓解方案 |
|------|--------|----------|
| 游戏更新改变数据库结构 | 中 | 版本检测 + schema 自动发现 |
| 存档写入时机不确定 | 低 | 文件监控 + 轮询备份 |
| Save_* 表仅在比赛期间有数据 | 低 | 这正是我们需要的 — 比赛期间读取 |
| 无法直接注入策略到游戏 | 高 | 只能提供建议，玩家手动操作 |
| 反作弊检测 | 低 | 单机游戏，无反作弊 |

---

## 八、结论

**这是一个非常可行的项目。** F1 Manager 2024 的 SQLite 存档系统为我们提供了前所未有的数据访问能力。结合 AI 策略引擎，我们可以构建一个实时策略助手，在比赛期间为玩家提供数据驱动的策略建议。

**关键优势：**
- 不需要内存注入或 hack — 纯文件读取
- 数据极其丰富（316个表，覆盖所有维度）
- 纯 Python 实现，无需 C++ 或逆向工程
- 已有成熟的开源工具作为基础
