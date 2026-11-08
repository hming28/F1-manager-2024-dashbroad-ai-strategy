# Memory Address Reverse-Engineering Tutorial — F1 Manager 2024

## 📋 Prerequisites
1. Cheat Engine: https://www.cheatengine.org/
2. pymem: `pip install pymem`
3. F1 Manager 2024 running, inside an active race session

---

## 🎯 Step 1: Finding Lap Count Address

### 1.1 Preparation
```
1. Launch F1 Manager 2024
2. Enter an active race session
3. Advance until around Lap 10
4. Pause the game
```

### 1.2 Search in Cheat Engine
```
1. Open Cheat Engine
2. Click process selector (top-left computer icon)
3. Select "F1Manager24-Win64-Shipping.exe" (or F1Manager24.exe)
4. Enter current lap (e.g. 10) in "Value" box
5. Set "Scan Type" to "Exact Value"
6. Set "Value Type" to "4 Bytes"
7. Click "First Scan"
```

### 1.3 Filter Results
```
1. Return to game, simulate 1 lap (lap becomes 11)
2. Pause the game
3. Return to Cheat Engine
4. Enter 11 in "Value" box
5. Click "Next Scan"
6. Repeat until 1-3 candidate addresses remain
```

### 1.4 Finding Pointer Chains
```
1. Right-click target address
2. Select "Find out what accesses this address"
3. Return to game, simulate 1 lap
4. Cheat Engine displays accessing instructions
5. Double-click instruction, inspect "Pointer" info
6. Note base address and offsets
```

### 1.5 Example Record
```
Base: F1Manager24-Win64-Shipping.exe+0x1A0B2C0
Offsets: [0x20, 0x38, 0x10]
```

---

## 🎯 Step 2: Finding Car Position

### 2.1 Search Position
```
1. Note current race position (e.g. P5 = 5)
2. Search value 5 in Cheat Engine (4 Bytes)
3. Wait for position to change (e.g. P4)
4. Next scan: 4
5. Repeat until isolated
```

### 2.2 Validation
```
1. Freeze the found address
2. Return to game and observe if position indicator freezes
3. If confirmed, unfreeze and document pointer
```

---

## 🎯 Step 3: Finding Tyre Condition

### 3.1 Search Tyre Percentage
```
1. Note tyre condition percentage (e.g. 65%)
2. In Cheat Engine:
   - Scan Type: "Value between..."
   - Min: 0.63
   - Max: 0.67
   - Value Type: Float
3. Click First Scan
4. Wait for tyre wear change (e.g. 63%)
5. Next scan: 0.61 - 0.65
6. Repeat until found
```

### 3.2 Key Notes
```
- Tyre wear is stored as a 4-byte Float, not an integer
- 65% in UI equals 0.65 in memory
- Use decimals rather than percentages during searches
```

---

## 🎯 Step 4: Finding ERS and Fuel

### 4.1 ERS State of Charge
```
1. Note ERS percentage (e.g. 75%)
2. Search 0.73 - 0.77 (Float)
3. Wait for battery deploy / recharge
4. Filter until confirmed
```

### 4.2 Fuel Remaining
```
1. Note remaining fuel load (e.g. 45.2 kg)
2. Search 44.9 - 45.5 (Float)
3. Filter as fuel burns down
```

---

## ⚠️ Frequently Asked Questions

### Q: Why do memory addresses change between launches?
A: This is due to ASLR (Address Space Layout Randomization). Use static module base offsets (`module + offset`) with pointer chains, or use the UE4SS reflection mod approach which dynamically queries memory offsets via Unreal Engine reflection symbols.

### Q: Why prefer UE4SS over manual Cheat Engine offsets?
A: Manual offsets break with every official game update and require maintaining 20 separate pointer chains. UE4SS hooks directly into Unreal Engine's C++ reflection system (`FCarData`), ensuring compatibility across game patches.
