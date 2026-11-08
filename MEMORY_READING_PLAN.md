# 内存读取方案 — 实时获取 F1 Manager 2024 比赛数据

## 🎯 目标
在比赛进行中，每秒读取游戏内存，获取实时数据（位置、轮胎、ERS、燃油等）。

## 📋 总体方案

```
F1 Manager 2024 进程 (F1Manager24.exe)
    ↓
游戏内存 (UE5 对象)
    ↓
pymem 读取 → Python 程序 → 策略分析 → 终端显示
```

---

## Phase 1: 环境准备 (你需要做的)

### 1.1 安装工具
- **Cheat Engine** — 用来找内存地址
  - 下载: https://www.cheatengine.org/
  - 安装后以管理员运行

### 1.2 安装 Python 依赖
```powershell
pip install pymem
```

---

## Phase 2: 找内存地址 (最关键)

### 2.1 为什么需要这一步
- 游戏每次启动，数据在内存中的位置会变 (ASLR)
- 但数据结构的"偏移量"是固定的
- 我们需要找到"指针链" (pointer chain) — 从固定基址到数据的路径

### 2.2 需要找到的数据
| 数据 | 搜索类型 | 搜索值 |
|------|----------|--------|
| 当前圈数 | 4字节整数 | 当前圈数 (如 32) |
| 车辆位置 | 4字节整数 | 你的位置 (如 5) |
| 轮胎状态 | 浮点数 | 0.0-1.0 (如 0.65) |
| ERS 电量 | 浮点数 | 0.0-1.0 (如 0.75) |
| 燃油 | 浮点数 | 剩余 kg (如 45.5) |
| 天气 | 4字节整数 | 0=晴, 1=阴, 2=小雨, 3=大雨 |

### 2.3 Cheat Engine 搜索步骤

```
1. 启动 F1 Manager 2024，进入一场比赛
2. 暂停比赛，记下当前数据（如：P5, 圈 32, 轮胎 65%）
3. 打开 Cheat Engine
4. 选择进程: F1Manager24.exe
5. 搜索: Value=32, Type=4 Bytes
6. 回到游戏，跑一圈，变成 33
7. 在 Cheat Engine 搜索: Value=33
8. 重复直到只剩 1-3 个地址
9. 右键 → "Find out what accesses this address"
10. 记录指针链 (pointer chain)
```

### 2.4 需要找到的地址
- 圈数指针链
- 车辆位置指针链 (每辆车)
- 轮胎状态指针链
- ERS 电量指针链
- 燃油指针链
- 天气状态指针链

---

## Phase 3: 代码实现

### 3.1 内存读取器 (core/memory_reader.py)

```python
"""
memory_reader.py — 读取 F1 Manager 2024 游戏内存

使用 pymem 库直接读取游戏进程内存。
"""
import pymem
import pymem.process
import struct

class MemoryReader:
    def __init__(self):
        self.pm = None
        self.base_address = 0
        
    def connect(self):
        """连接到游戏进程"""
        self.pm = pymem.Pymem("F1Manager24.exe")
        self.base_address = self.pm.base_address
        
    def read_int(self, address: int) -> int:
        """读取 4 字节整数"""
        return self.pm.read_int(address)
    
    def read_float(self, address: int) -> float:
        """读取浮点数"""
        return self.pm.read_float(address)
    
    def read_pointer_chain(self, base: int, offsets: list[int]) -> int:
        """读取指针链"""
        addr = base
        for offset in offsets:
            addr = self.pm.read_longlong(addr) + offset
        return addr
    
    def get_lap_count(self) -> int:
        """获取当前圈数"""
        # 需要用 Cheat Engine 找到真实地址
        # 示例: base + 0x1A0 + 0x20 + 0x38
        return self.read_int(self.lap_count_address)
    
    def get_car_position(self, car_index: int) -> int:
        """获取车辆位置"""
        # 需要用 Cheat Engine 找到真实地址
        return self.read_int(self.car_positions_address + car_index * 0x10)
    
    def get_tyre_condition(self, car_index: int) -> float:
        """获取轮胎状态 (0.0-1.0)"""
        return self.read_float(self.tyre_condition_address + car_index * 0x10)
```

### 3.2 配置文件 (config/memory_offsets.yaml)

```yaml
# 内存偏移量配置
# 这些值需要用 Cheat Engine 找到

# 基址指针
base_pointer: "F1Manager24.exe+0x1A0B2C0"

# 圈数
lap_count_offsets: [0x20, 0x38, 0x10]

# 车辆数据基址
car_data_base_offsets: [0x20, 0x38, 0x100]

# 每辆车的数据偏移
car_data_stride: 0x10  # 每辆车之间的内存间隔

# 各数据项的偏移
position_offset: 0x00
tyre_condition_offset: 0x10
ers_charge_offset: 0x20
fuel_offset: 0x30
```

---

## Phase 4: 集成到主系统

### 4.1 修改 main.py
```python
# 新增内存读取模式
if args.mode == "memory":
    reader = MemoryReader()
    reader.connect()
    
    while True:
        snapshot = reader.build_snapshot()
        state = engine.update(snapshot)
        display.render(snapshot, state)
        time.sleep(1)  # 每秒读取一次
```

### 4.2 命令行参数
```powershell
# 内存读取模式
python main.py --mode memory --team 4

# 存档文件模式 (现有)
python main.py --mode save --team 4
```

---

## ⚠️ 重要说明

### 需要你手动完成的部分
1. **安装 Cheat Engine**
2. **搜索内存地址** — 这是最耗时的步骤
3. **记录指针链** — 可能需要 2-4 小时

### 风险
- 游戏更新可能改变内存偏移
- 需要重新找地址
- 反作弊检测 (单机游戏通常没有)

### 预期效果
```
L32/57 │ P5 │ Tyres 🟡62% │ ERS ⚡85% │ Fuel 45.2kg
L33/57 │ P4 (+1) │ Tyres 🟡58% │ ERS ⚡72% │ Fuel 43.8kg
⚠️ L33 轮胎中度磨损 (58%) → 开始考虑进站窗口
```

每秒更新，完全实时！

---

## 📅 实施计划

| 阶段 | 任务 | 时间 | 谁做 |
|------|------|------|------|
| 1 | 安装 Cheat Engine | 10 分钟 | 你 |
| 2 | 搜索圈数地址 | 30 分钟 | 你 |
| 3 | 搜索车辆位置地址 | 1 小时 | 你 |
| 4 | 搜索轮胎/ERS/燃油地址 | 1 小时 | 你 |
| 5 | 写内存读取代码 | 2 小时 | 我 |
| 6 | 集成测试 | 30 分钟 | 一起 |

**总计: 约 5 小时**

---

## 🤔 下一步

你想现在开始吗？

1. 先安装 Cheat Engine
2. 启动游戏，进入一场比赛
3. 我教你一步步找地址

或者你想我先把代码框架写好，等你找到地址后再集成？