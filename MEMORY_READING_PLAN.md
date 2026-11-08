# Memory Reading Architecture & Feasibility — F1 Manager 2024

## 🎯 Goal
Extract real-time telemetry (race position, tyres, fuel, ERS, sector times) while the 3D race session is ongoing.

## 📋 High-Level Approaches

### Approach A: Direct Process Memory Hooking (Pymem / External)
```
F1Manager24.exe (Process Memory)
       ↓
Dynamic Pointer Chains (ASLR / Offsets)
       ↓
Pymem External Reader → Strategy Engine → Dashboard UI
```
- **Limitation**: Breakages after official game patches due to recompiled struct offsets; manual pointer scan required per update.

### Approach B: UE4SS Unreal Engine C++ Reflection (Adopted Solution)
```
F1Manager24.exe (Unreal Engine 5.1 Runtime)
       ↓
UE4SS In-Process Reflection (FCarData, URaceSimManager)
       ↓
Thread-Safe Lua Hook (LiveTimingMod)
       ↓
Local IPC (live_timing.json) → Python Strategy Engine → Rich Timing Tower
```
- **Advantages**:
  - Automatically queries official Unreal Engine C++ reflection symbols (`FCarData`).
  - Survives patch updates without needing address recalculations.
  - Non-invasive, zero modification to executable binaries or game assets.

---

## Technical Specifications: Telemetry Data Model

| Metric | Type | Source / Offset | Description |
|:-------|:-----|:----------------|:------------|
| Current Lap | int32 | `CarData.LapCount` | Completed laps + 1 |
| Position | int32 | `CarData.RacePos` | Current position P1 - P20 |
| S1 Time | float | `CarData.Sector1Time` | Sector 1 elapsed seconds |
| S1 State | enum | `CarData.Sector1State` | Color status (Yellow, Purple, Green) |
| S2 Time | float | `CarData.Sector2Time` | Sector 2 elapsed seconds |
| S2 State | enum | `CarData.Sector2State` | Color status (Yellow, Purple, Green) |
| S3 Time | float | `CarData.Sector3Time` | Sector 3 elapsed seconds |
| S3 State | enum | `CarData.Sector3State` | Color status (Yellow, Purple, Green) |
| Running Lap Time | float | `CarData.CurrentLapTime` | Live timer in current lap |
| Last Lap Time | float | `CarData.LastLapTime` | Previous completed lap time |
| Best Lap Time | float | `CarData.BestLap` | Driver/Session fastest lap |
| Tyre Wear | uint8 | `CarData.TyreWearPercentage` | 0-100% wear |
| Tyre Temperature | uint8 | `CarData.TyreTemperature` | Surface temperature (°C) |
| Fuel Remaining | float | `CarData.Fuel` | Fuel load (kg) |
| ERS Charge | int32 | `CarData.ERSBatteryChargePercentage`| Battery capacity (0-100%) |
| DRS State | enum | `CarData.DRSState` | Active / Inactive |
