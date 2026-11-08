# F1 Manager 2024 AI Strategy System — Technical Research Report

## 1. Feasibility Conclusion: Fully Supported

F1 Manager 2024 stores race and game management state in **SQLite databases** embedded within `.sav` files (over **316 tables**), supplemented by in-process telemetry via Unreal Engine 5.1 reflection. This dual-source architecture allows comprehensive extraction of real-time telemetry and management state.

---

## 2. Core Architecture & Telemetry Sources

### 2.1 Live In-Race Telemetry (UE4SS Reflection Hook)
During active 3D racing, high-frequency sector and lap time records are maintained in transient engine memory (`FCarData`) to prevent disk I/O stutter. 
- **Telemetry stream**: 250ms refresh cycle.
- **Data extracted**: Sector times (S1, S2, S3), sector state (Purple, Green, Yellow), running lap time, last lap, best lap, tyre temperatures, surface wear, ERS battery level, and car-ahead interval delta.

### 2.2 Career & HQ Save State (.sav SQLite Container)
When outside 3D racing (Team HQ, manufacturing, driver contracts, R&D):
- `.sav` files comprise a GVAS UE5 header followed by zlib-compressed SQLite database structures.
- Unpacked using pure Python (`core/savefile_codec.py`) to query static references, car development parts, and track baseline metrics.

---

## 3. Database Schema Overview (Key Tables)

### 🏎️ Race Simulation Tables
| Table | Description | Key Attributes |
|:------|:------------|:---------------|
| `Save_RaceSimCars` | Live car states | Fuel, RacePosition, TotalRaceTime, DRSState, SafetyCarState |
| `Save_RaceSimCars_Parts` | Tyres & wear | 4 individual tyre temps/wear states, wing/sidepod/floor damage levels |
| `Save_RaceSimCars_Strategy` | Strategy execution | TyreWearStrategy, ErsStrategy, OvertakeStrategy, DefenceStrategy |
| `Save_RaceSimCars_PitStop` | Pit stop history | PitStopState, phase durations, compound fitted, pit error probability |
| `Save_RaceSimCars_Misc` | ERS & warmup | ErsBatteryCharge, ErsDeployAmount, TyreWarmupProgress |
| `Save_RaceSimCars_Overtake` | Overtake simulation | OvertakeActive, SuccessRoll, DefenderCar, DefenceType |

### 🌦️ Weather & Track State
| Table | Description | Key Attributes |
|:------|:------------|:---------------|
| `Save_WeatherHistory` | Weather history | Rain, WaterOnTrack, AmbientTemp, TrackTemp, WeatherState |
| `Races_Tracks` | Track references | Laps, TrackLength, SafetyCarChance, PitLaneTimeLoss |

---

## 4. AI Strategy Decision Engine Capabilities

1. **Tyre Degradation Modeling**:
   - Compound degradation curves across Soft, Medium, Hard, Inter, and Wet compounds.
   - Cliff threshold prediction and optimal stint length determination.
2. **Dynamic Pit Window Optimizer**:
   - Compares compound lap-delta trade-offs against track pit lane loss.
   - Evaluates undercut and overcut tactical opportunities against competitor cars.
3. **Safety Car & VSC Exploitation**:
   - Evaluates pit delta time reduction during SC/VSC to identify free pit stop windows.
4. **Weather Crossover Transitions**:
   - Real-time alerts when track dampness passes crossover thresholds between slicks and wet-weather compounds.
