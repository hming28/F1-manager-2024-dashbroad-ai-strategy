# 🏎️ F1 Manager 2024 — AI Strategy Engine & Live Timing

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-32%20passed-brightgreen.svg)](tests/)

Real-time AI strategy assistant and broadcast-grade **Live Timing Tower** for **F1 Manager 2024**.
Monitors in-race 3D telemetry via UE4SS (250ms refresh rate) with official sector color highlights (purple/green/yellow), lap-by-lap history, tyre degradation modeling, and pit stop optimization. Seamlessly falls back to `.sav` SQLite monitoring when managing contracts, R&D, and facilities in the team HQ.

---

## 🌟 Key Features

- **⚡ Real-Time Live Timing (UE4SS Reflection)**:
  - 500ms millisecond-level telemetry from `FCarData` for all 20 cars (balanced performance & responsiveness).
  - S1, S2, S3 sector timing with F1 broadcast color coding (🟣 **Purple**: Session Best, 🟢 **Green**: Personal Best, 🟡 **Yellow**: Completed).
  - Running lap times, gap to leader, interval to car ahead, and tyre life percentages.
  - 100% thread-safe in Unreal Engine 5.1; handles 16x simulation speed without dropping laps or freezing game threads.
- **🌱 Low-Spec & Eco Modes**:
  - `--eco` flag for 1 FPS minimal CPU usage on older or entry-level systems.
  - Cooldown-protected global object traversal avoiding micro-stutters during race loading.
  - Automatic `UE4SS-settings.ini` tuning in `install_mod.py` to disable background consoles and debug logging.
- **🔄 Dual-Mode Auto Detection**:
  - Automatically streams Live Timing during active 3D sessions (Practice, Qualifying, Race).
  - Automatically falls back to `.sav` SQLite parsing when navigating team HQ menus.
- **🧠 AI Strategy & Telemetry Engine**:
  - **Tyre degradation model**: Predicts cliff points and optimal stint lengths per compound.
  - **Pit stop optimizer**: Dynamic evaluation of 1-stop vs 2-stop, undercut threats, and overcut opportunities.
  - **Safety Car / VSC response**: Instant calculation of delta times for free pit stop opportunities.
  - **Weather radar & rain transitions**: Track wetness tracking and compound crossover alerts.
  - **Competitor intelligence**: Tracks pit windows and pace deltas for all 19 opponents.
- **🖥️ Broadcast-Grade Terminal Dashboard (Rich UI)**:
  - Adaptive 120-column full-width Timing Tower.
  - Dedicated cards for [My Team Status], [Strategy Recommendations], [Weather], and [Race Intel].
  - Graceful `⏸️ LIVE (PAUSED)` state persistence when pausing the game.

---

## 🚀 Quick Start & Installation

Choose the installation option that best fits your workflow:

### Option A: Full AI Strategy Assistant & Live Timing (Recommended)
*For players who want the full broadcast-grade terminal timing tower and real-time AI pit/tyre strategy recommendations.*

#### 1. Clone the repository & install dependencies
```bash
git clone https://github.com/hming28/F1-manager-2024-dashbroad-ai-strategy.git
cd F1-manager-2024-dashbroad-ai-strategy

pip install -r requirements.txt
```

#### 2. Deploy the game mod (One-Click Installer)
```bash
python install_mod.py
```
> 💡 Automatically detects your **Epic Games Store**, **Steam**, or **Xbox Game Pass** game directory and deploys `LiveTimingMod` into `ue4ss/Mods/`. If UE4SS is not yet installed, the installer provides the exact setup guide.

#### 3. Launch game & start strategy assistant
- Open **F1 Manager 2024** and start any session (Practice, Qualifying, or Race).
- In your terminal, run:
  ```bash
  # Auto-detect and monitor all 20 cars
  python main.py

  # Or highlight your specific team (e.g. 1=Ferrari, 2=McLaren, 3=RedBull, 10=AstonMartin)
  python main.py --team 1
  ```

---

### Option B: Standalone Game Mod Only (No Python Required)
*For players who only want the game mod to export live telemetry without setting up Python.*

1. **Download the pre-packaged Mod**:
   - Go to [v1.0.0 Release](https://github.com/hming28/F1-manager-2024-dashbroad-ai-strategy/releases/tag/v1.0.0).
   - Under **Assets**, download `F1Manager24-LiveTimingMod-v1.0.0.zip`.

2. **Install UE4SS Framework (Prerequisite)**:
   - Download the UE4SS release from [RE-UE4SS Releases](https://github.com/UE4SS-RE/RE-UE4SS/releases) (e.g. `UE4SS_v3.0.1.zip`).
   - Extract the files into your game's binaries directory:
     `<Game_Directory>\F1Manager24\Binaries\Win64\`

3. **Install the Mod**:
   - Extract `F1Manager24-LiveTimingMod-v1.0.0.zip` directly into the same directory:
     `<Game_Directory>\F1Manager24\Binaries\Win64\`
   - Done! During any race, the mod will automatically generate live telemetry at `ue4ss\Mods\LiveTimingMod\live_timing.json`.

---

#### Team ID Reference
| ID | Team | ID | Team |
|:--:|:-----|:--:|:-----|
| `1` | Scuderia Ferrari | `6` | Williams Racing |
| `2` | McLaren | `7` | Haas F1 Team |
| `3` | Red Bull Racing | `8` | Racing Bulls (VCARB) |
| `4` | Mercedes-AMG | `9` | Stake F1 Team Kick Sauber |
| `5` | Alpine F1 Team | `10` | Aston Martin Aramco |
| `32` | Create a Team (Custom) | `0` | All Teams (Default) |

---

## ⚡ Performance & Low-Spec Optimization Guide

If you experience in-game micro-stutters or frame drops while running the strategy engine, follow these quick optimization steps:

### 1. Launch with `--eco` Mode
Run the Python assistant with the `--eco` flag:
```bash
python main.py --eco
```
> **What it does**: Drops terminal dashboard re-rendering to 1 FPS and expands internal loop sleep to 1.0s, reducing Python CPU & GPU utilization by over 70% on quad-core or entry-level processors.

### 2. Add Windows Defender / Antivirus Exclusion (Prevents I/O Spikes)
Real-time antivirus scanning (`MsMpEng.exe`) monitors file writes. Because `live_timing.json` updates continuously during races, antivirus software can lock the file and cause stuttering.
- Open **Windows Security** → **Virus & threat protection settings** → **Exclusions** → **Add an exclusion**.
- Add both your **F1 Manager 2024 game folder** and the **`f1-manager-2024-strategy-ai`** directory.

### 3. Disable UE4SS GUI Overlay Console & Debug Logging
Our `install_mod.py` automatically configures this, but you can also verify manually in `<GameDir>/F1Manager24/Binaries/Win64/ue4ss/UE4SS-settings.ini`:
```ini
[Debug]
ConsoleEnabled = 0
GuiConsoleEnabled = 0
LogLevel = 0
```

### 4. Game Simulation Speed & Graphics
- **Simulation Speed**: During intense battles or on lower-spec CPUs, prefer **2x or 4x** over **16x**. (At 16x speed, Unreal Engine calculates 16 times as many physics and AI ticks per real second).
- **In-Game Settings**: Lower **Shadow Quality**, **Post Processing**, and enable **FSR 2 / DLSS (Balanced or Performance)**.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ F1 Manager 2024 Game Process (Unreal Engine 5.1)                       │
│                                                                        │
│   [URaceSimManager:OnRaceSimEventReceived] ──► Event checkpoints       │
│   [BP_BaseCar2022_Actor_C:ReceiveTick]     ──► 500ms Telemetry Stream  │
│                                                                        │
│   └──► UE4SS Mod: ue4ss/Mods/LiveTimingMod/Scripts/main.lua            │
│             │                                                          │
└─────────────┼──────────────────────────────────────────────────────────┘
              │ (Zero-dependency string.format atomic write)
              ▼
   live_timing.json  ◄──── (or .sav SQLite fallback in HQ mode)
              │
┌─────────────┼──────────────────────────────────────────────────────────┐
│ Python Strategy Assistant (f1-manager-2024-strategy-ai)                │
│                                                                        │
│   [core/live_timing_reader.py]                                         │
│   ├── LiveTimingReader: Non-blocking shared file reader + pause badge  │
│   └── LapHistoryAccumulator: Lap-by-lap history, S1/S2/S3 color states │
│                                                                        │
│   [strategy/engine.py]                                                 │
│   ├── Tyre Model: Compound degradation & crossover predictions        │
│   ├── Pit Optimizer: Undercut/overcut & Safety Car free-stop logic     │
│   └── Race Intel: Competitor strategy tracking                         │
│                                                                        │
│   [display/dashboard.py]                                              │
│   └── Full-width Rich Timing Tower + Strategy & Weather Cards          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure

```
f1-manager-2024-strategy-ai/
├── install_mod.py             # One-click game mod installer for users
├── package_release.py         # Automated release packager for GitHub Releases
├── main.py                    # Main application entry point
├── config.yaml                # Strategy & model configuration
├── requirements.txt           # Python dependencies
├── pyproject.toml             # Modern Python project configuration
├── LICENSE                    # MIT License
├── mods/                      # UE4SS game mod source files
│   └── LiveTimingMod/
│       ├── enabled.txt
│       └── Scripts/
│           └── main.lua       # Thread-safe Unreal Engine Lua hook
├── core/                      # Data pipeline & telemetry
│   ├── live_timing_reader.py  # Live timing reader & lap history accumulator
│   ├── save_reader.py         # .sav file unpacker (GVAS + zlib -> SQLite)
│   ├── db_accessor.py         # Database query & typed models
│   ├── file_watcher.py        # Save directory monitoring
│   ├── models.py              # Data structures & enums
│   └── savefile_codec.py      # Binary save file decoder
├── strategy/                  # Strategy decision engine
│   ├── engine.py              # Main strategy coordinator
│   ├── tyre_model.py          # Compound degradation curves
│   ├── pit_optimizer.py       # Pit window optimizer
│   ├── safety_car.py          # Safety car / VSC response
│   ├── weather_strategy.py    # Rain & track crossover analyzer
│   └── race_intel.py          # Competitor threat tracker
├── display/                   # Terminal user interface
│   └── dashboard.py           # Rich F1 TV-style Timing Tower
└── tests/                     # Test suite (32 unit tests)
    ├── test_live_timing.py    # Live telemetry & edge case tests
    └── test_strategy.py       # Strategy engine & tyre model tests
```

---

## 🧪 Testing

Run all automated unit tests:
```bash
pytest tests/ -v
```
All 32 test cases cover multi-car telemetry, pause retention, purple sector preservation, high-speed lap jumps, and terminal layout safety.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request or open an Issue for bug reports or feature requests.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 Credits & License

- Distributed under the **MIT License**. See `LICENSE` for more information.
- Save file codec derived from [IUrreta/DatabaseEditor](https://github.com/IUrreta/DatabaseEditor) (GPL-3.0 compatible attribution).
- Database schema references from [guest329/scarlet-dynasty-f1m24](https://github.com/guest329/scarlet-dynasty-f1m24).
