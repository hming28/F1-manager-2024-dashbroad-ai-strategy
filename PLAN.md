# F1 Manager 2024 AI Strategy System — Engineering Plan

## Project Objective
Build a real-time AI strategy assistant for F1 Manager 2024 that monitors race data, evaluates tyre degradation, and recommends optimal pit and pace strategies.

---

## Phase 1: Data Pipeline — Foundations
**Goal:** Ingest telemetry and save states from the game.

### Task 1.1: Savefile Unpacker
- Extract and integrate `savefile_codec.py`
- Support `.sav` (GVAS + zlib) -> SQLite conversion
- Validate compatibility across career and race weekend saves

### Task 1.2: File Monitoring System
- Monitor save directory using Python `watchdog`
- Detect save modifications and trigger automated analysis

### Task 1.3: Data Access Layer
- Implement typed SQLite queries for race snapshots
- Query car telemetry, weather conditions, pit history, and standings

---

## Phase 2: Strategy Engine — Core Algorithms
**Goal:** Compute data-driven race strategies.

### Task 2.1: Tyre Degradation Model
- Model tyre degradation curves across Soft, Medium, Hard, Intermediate, and Wet compounds
- Predict remaining tyre life and cliff drop-offs

### Task 2.2: Pit Window Optimizer
- Calculate optimal pit lap considering tyre degradation vs. new compound delta
- Account for track pit lane loss and traffic reintegration

### Task 2.3: Weather & Transition Strategy
- Monitor track dampness and rain intensity
- Alert crossover windows for slick <-> wet tyres

### Task 2.4: Safety Car / VSC Strategy
- Detect SC/VSC deployment
- Compute free pit stop deltas and recommend pit decisions

### Task 2.5: Competitor Modeling
- Track opponent pit windows and pace deltas
- Identify undercut/overcut tactical windows

---

## Phase 3: Telemetry & Live Timing (UE4SS)
**Goal:** Deliver broadcast-grade live timing with zero latency.

### Task 3.1: UE4SS Live Timing Mod
- In-process Unreal Engine 5.1 hook into `FCarData`
- Sector timing (S1, S2, S3) with official color coding (Purple, Green, Yellow)
- Running lap times, gap to leader, and car-ahead interval delta

### Task 3.2: Terminal Dashboard (Rich UI)
- Full-width adaptive Timing Tower
- Simultaneous display of team status, strategy recommendations, weather, and competitor intel

---

## Phase 4: Verification & Packaging
- Automated unit test suite (`pytest`)
- Standalone mod installer (`install_mod.py`) supporting Epic Games Store, Steam, and Xbox Game Pass
- GitHub open-source packaging and automated release bundles
