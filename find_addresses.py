"""
find_addresses.py — Interactive tool to find F1 Manager 2024 memory addresses.

This tool helps you find the memory addresses for race data.
It's like a simplified Cheat Engine in Python.

Usage:
    python find_addresses.py

Steps:
    1. Start F1 Manager 2024 and enter a race
    2. Run this script
    3. Follow the prompts to search for values
    4. When addresses are found, save them to config
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.memory_reader import MemoryReader, AddressScanner, PYMEM_AVAILABLE


def main():
    if not PYMEM_AVAILABLE:
        print("ERROR: pymem not installed")
        print("Install with: pip install pymem")
        return
    
    print("=" * 60)
    print("  F1 Manager 2024 — Memory Address Finder")
    print("=" * 60)
    print()
    
    # Connect to game
    reader = MemoryReader()
    
    print("Connecting to F1Manager24-Win64-Shipping.exe...")
    if not reader.connect():
        print("ERROR: Cannot connect to game")
        print("Make sure the game is running!")
        return
    
    print(f"Connected! Base address: 0x{reader.base_address:X}")
    print()
    
    scanner = AddressScanner(reader)
    
    # ── Find Lap Count ───────────────────────────────────────────────────
    print("-" * 60)
    print("STEP 1: Find LAP COUNT")
    print("-" * 60)
    print()
    print("Instructions:")
    print("1. In the game, note the current lap number")
    print("2. Enter it below")
    print("3. Advance ONE lap in the game")
    print("4. Enter the new lap number")
    print("5. Repeat until only a few addresses remain")
    print()
    
    lap_addresses = []
    
    try:
        while True:
            current_lap = input("Current lap number (or 'done' to finish): ").strip()
            if current_lap.lower() == 'done':
                break
            
            try:
                lap_num = int(current_lap)
            except ValueError:
                print("Please enter a number or 'done'")
                continue
            
            if not lap_addresses:
                print(f"Searching for value {lap_num}...")
                lap_addresses = scanner.search_int(lap_num)
                print(f"Found {len(lap_addresses)} addresses")
            else:
                print(f"Filtering for value {lap_num}...")
                lap_addresses = scanner.filter_int(lap_addresses, lap_num)
                print(f"Remaining: {len(lap_addresses)} addresses")
            
            if len(lap_addresses) == 0:
                print("No addresses found! Try again.")
                break
            elif len(lap_addresses) <= 10:
                print()
                print("Remaining addresses:")
                for addr in lap_addresses:
                    print(f"  0x{addr:X}")
                print()
            
            if len(lap_addresses) == 1:
                print(f"FOUND IT! Lap count address: 0x{lap_addresses[0]:X}")
                break
    
    except KeyboardInterrupt:
        print("\nCancelled")
    
    # ── Find Tyre Condition ──────────────────────────────────────────────
    print()
    print("-" * 60)
    print("STEP 2: Find TYRE CONDITION (your car, front left)")
    print("-" * 60)
    print()
    print("Instructions:")
    print("1. In the game, note your tyre condition percentage")
    print("2. Convert to float (e.g., 65% = 0.65)")
    print("3. Enter it below")
    print("4. Wait for it to change slightly")
    print("5. Enter the new value")
    print()
    
    tyre_addresses = []
    
    try:
        while True:
            current_tyre = input("Tyre condition as decimal (e.g., 0.65, or 'done'): ").strip()
            if current_tyre.lower() == 'done':
                break
            
            try:
                tyre_val = float(current_tyre)
            except ValueError:
                print("Please enter a decimal number or 'done'")
                continue
            
            if not tyre_addresses:
                print(f"Searching for value {tyre_val}...")
                tyre_addresses = scanner.search_float(tyre_val, tolerance=0.02)
                print(f"Found {len(tyre_addresses)} addresses")
            else:
                print(f"Filtering for value {tyre_val}...")
                tyre_addresses = [a for a in tyre_addresses 
                                 if abs(reader.pm.read_float(a) - tyre_val) < 0.02]
                print(f"Remaining: {len(tyre_addresses)} addresses")
            
            if len(tyre_addresses) == 0:
                print("No addresses found! Try again.")
                break
            elif len(tyre_addresses) <= 10:
                print()
                print("Remaining addresses:")
                for addr in tyre_addresses:
                    val = reader.pm.read_float(addr)
                    print(f"  0x{addr:X} = {val}")
                print()
            
            if len(tyre_addresses) == 1:
                print(f"FOUND IT! Tyre condition address: 0x{tyre_addresses[0]:X}")
                break
    
    except KeyboardInterrupt:
        print("\nCancelled")
    
    # ── Summary ──────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print()
    
    if lap_addresses:
        print(f"Lap count: 0x{lap_addresses[0]:X}")
    else:
        print("Lap count: NOT FOUND")
    
    if tyre_addresses:
        print(f"Tyre condition: 0x{tyre_addresses[0]:X}")
    else:
        print("Tyre condition: NOT FOUND")
    
    print()
    print("Next steps:")
    print("1. Record these addresses")
    print("2. We'll calculate the pointer chains")
    print("3. Save to config/memory_offsets.yaml")
    print()


if __name__ == "__main__":
    main()
