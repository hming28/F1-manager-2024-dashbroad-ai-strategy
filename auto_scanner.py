"""
auto_scanner.py — Automatic memory address finder for F1 Manager 2024.

This tool automates the Cheat Engine process.
You just input the values you see in the game, and it finds the addresses.

Usage:
    python auto_scanner.py

Requirements:
    - F1 Manager 2024 running with a race in progress
    - pymem installed (pip install pymem)
    - Run as Administrator
"""
from __future__ import annotations

import sys
import time
import json
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    import pymem
    import pymem.process
    PYMEM_AVAILABLE = True
except ImportError:
    PYMEM_AVAILABLE = False


class AutoScanner:
    """Automated memory scanner for F1 Manager 2024."""
    
    def __init__(self):
        self.pm = None
        self.base_address = 0
        self.found_addresses = {}
    
    def connect(self) -> bool:
        """Connect to the game process."""
        if not PYMEM_AVAILABLE:
            print("ERROR: pymem not installed")
            print("Install with: pip install pymem")
            return False
        
        print("Connecting to F1 Manager 2024...")
        try:
            # Try common process names
            names = [
                "F1Manager24-Win64-Shipping.exe",
                "F1Manager24.exe",
                "F1 Manager 24",
            ]
            
            for name in names:
                try:
                    self.pm = pymem.Pymem(name)
                    self.base_address = self.pm.base_address
                    print(f"✓ Connected to {name}")
                    print(f"  Base address: 0x{self.base_address:X}")
                    return True
                except Exception:
                    continue
            
            print("ERROR: Cannot find F1 Manager 2024 process")
            print("Make sure the game is running!")
            return False
            
        except Exception as e:
            print(f"ERROR: {e}")
            return False
    
    def scan_int(self, value: int, max_results: int = 1000) -> list[int]:
        """Scan for integer values in memory."""
        print(f"  Scanning for integer value: {value}...")
        results = []
        
        # Scan the main module
        try:
            module = pymem.process.module_from_name(
                self.pm.process_handle, 
                "F1Manager24-Win64-Shipping.exe"
            )
            if module:
                start = module.lpBaseOfDll
                size = module.SizeOfImage
            else:
                start = self.base_address
                size = 0x7FFFFFFF
        except Exception:
            start = self.base_address
            size = 0x7FFFFFFF
        
        # Read memory in chunks
        chunk_size = 4096
        addr = start
        end = start + size
        
        while addr < end and len(results) < max_results:
            try:
                # Read chunk
                data = self.pm.read_bytes(addr, chunk_size)
                
                # Search in chunk
                for i in range(0, len(data) - 3, 4):
                    val = int.from_bytes(data[i:i+4], byteorder='little')
                    if val == value:
                        results.append(addr + i)
                
                addr += chunk_size
                
            except Exception:
                # Skip unreadable memory
                addr += chunk_size
                continue
        
        print(f"  Found {len(results)} addresses")
        return results
    
    def scan_float(self, value: float, tolerance: float = 0.01, 
                   max_results: int = 1000) -> list[int]:
        """Scan for float values in memory."""
        print(f"  Scanning for float value: {value} (±{tolerance})...")
        results = []
        
        try:
            module = pymem.process.module_from_name(
                self.pm.process_handle, 
                "F1Manager24-Win64-Shipping.exe"
            )
            if module:
                start = module.lpBaseOfDll
                size = module.SizeOfImage
            else:
                start = self.base_address
                size = 0x7FFFFFFF
        except Exception:
            start = self.base_address
            size = 0x7FFFFFFF
        
        chunk_size = 4096
        addr = start
        end = start + size
        
        while addr < end and len(results) < max_results:
            try:
                data = self.pm.read_bytes(addr, chunk_size)
                
                for i in range(0, len(data) - 3, 4):
                    val = self.pm.read_float(addr + i)
                    if abs(val - value) < tolerance:
                        results.append(addr + i)
                
                addr += chunk_size
                
            except Exception:
                addr += chunk_size
                continue
        
        print(f"  Found {len(results)} addresses")
        return results
    
    def filter_addresses(self, addresses: list[int], value, 
                         is_float: bool = False, tolerance: float = 0.01) -> list[int]:
        """Filter addresses to only those containing the given value."""
        print(f"  Filtering {len(addresses)} addresses for value: {value}...")
        results = []
        
        for addr in addresses:
            try:
                if is_float:
                    val = self.pm.read_float(addr)
                    if abs(val - value) < tolerance:
                        results.append(addr)
                else:
                    val = self.pm.read_int(addr)
                    if val == value:
                        results.append(addr)
            except Exception:
                continue
        
        print(f"  Remaining: {len(results)} addresses")
        return results
    
    def save_results(self, filename: str = "found_addresses.json"):
        """Save found addresses to file."""
        data = {
            "base_address": self.base_address,
            "addresses": self.found_addresses,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Saved to {filename}")


def find_lap_count(scanner: AutoScanner):
    """Interactive guide to find lap count address."""
    print()
    print("=" * 60)
    print("  FIND: LAP COUNT")
    print("=" * 60)
    print()
    print("In the game, note the current lap number.")
    print("Then advance 1 lap and enter the new number.")
    print("Repeat until only a few addresses remain.")
    print()
    
    addresses = []
    
    while True:
        value = input("Current lap number (or 'done' to finish): ").strip()
        
        if value.lower() == 'done':
            break
        
        try:
            lap_num = int(value)
        except ValueError:
            print("Please enter a number or 'done'")
            continue
        
        if not addresses:
            addresses = scanner.scan_int(lap_num)
        else:
            addresses = scanner.filter_addresses(addresses, lap_num)
        
        if len(addresses) == 0:
            print("No addresses found. Try again.")
            break
        elif len(addresses) <= 5:
            print()
            print("Remaining addresses:")
            for addr in addresses:
                print(f"  0x{addr:X}")
            print()
        
        if len(addresses) == 1:
            print(f"✓ FOUND! Lap count address: 0x{addresses[0]:X}")
            scanner.found_addresses["lap_count"] = addresses[0]
            return addresses[0]
    
    if addresses:
        print(f"Best guess: 0x{addresses[0]:X}")
        scanner.found_addresses["lap_count"] = addresses[0]
        return addresses[0]
    
    return None


def find_position(scanner: AutoScanner):
    """Interactive guide to find position address."""
    print()
    print("=" * 60)
    print("  FIND: YOUR POSITION")
    print("=" * 60)
    print()
    print("In the game, note your position (1-20).")
    print("Then wait for it to change and enter the new position.")
    print()
    
    addresses = []
    
    while True:
        value = input("Current position (or 'done'): ").strip()
        
        if value.lower() == 'done':
            break
        
        try:
            pos = int(value)
        except ValueError:
            print("Please enter a number or 'done'")
            continue
        
        if not addresses:
            addresses = scanner.scan_int(pos)
        else:
            addresses = scanner.filter_addresses(addresses, pos)
        
        if len(addresses) == 0:
            print("No addresses found. Try again.")
            break
        elif len(addresses) <= 5:
            print()
            print("Remaining addresses:")
            for addr in addresses:
                print(f"  0x{addr:X}")
            print()
        
        if len(addresses) == 1:
            print(f"✓ FOUND! Position address: 0x{addresses[0]:X}")
            scanner.found_addresses["position"] = addresses[0]
            return addresses[0]
    
    if addresses:
        print(f"Best guess: 0x{addresses[0]:X}")
        scanner.found_addresses["position"] = addresses[0]
        return addresses[0]
    
    return None


def find_tyre_condition(scanner: AutoScanner):
    """Interactive guide to find tyre condition address."""
    print()
    print("=" * 60)
    print("  FIND: TYRE CONDITION")
    print("=" * 60)
    print()
    print("In the game, note your tyre condition percentage.")
    print("Convert to decimal (e.g., 65% = 0.65)")
    print("Then wait for it to change and enter the new value.")
    print()
    
    addresses = []
    
    while True:
        value = input("Tyre condition as decimal (e.g., 0.65, or 'done'): ").strip()
        
        if value.lower() == 'done':
            break
        
        try:
            tyre_val = float(value)
        except ValueError:
            print("Please enter a decimal number or 'done'")
            continue
        
        if not addresses:
            addresses = scanner.scan_float(tyre_val, tolerance=0.02)
        else:
            addresses = scanner.filter_addresses(addresses, tyre_val, 
                                                 is_float=True, tolerance=0.02)
        
        if len(addresses) == 0:
            print("No addresses found. Try again.")
            break
        elif len(addresses) <= 5:
            print()
            print("Remaining addresses:")
            for addr in addresses:
                try:
                    val = scanner.pm.read_float(addr)
                    print(f"  0x{addr:X} = {val:.4f}")
                except Exception:
                    pass
            print()
        
        if len(addresses) == 1:
            print(f"✓ FOUND! Tyre condition address: 0x{addresses[0]:X}")
            scanner.found_addresses["tyre_condition"] = addresses[0]
            return addresses[0]
    
    if addresses:
        print(f"Best guess: 0x{addresses[0]:X}")
        scanner.found_addresses["tyre_condition"] = addresses[0]
        return addresses[0]
    
    return None


def find_ers_charge(scanner: AutoScanner):
    """Interactive guide to find ERS charge address."""
    print()
    print("=" * 60)
    print("  FIND: ERS CHARGE")
    print("=" * 60)
    print()
    print("In the game, note your ERS charge percentage.")
    print("Convert to decimal (e.g., 75% = 0.75)")
    print()
    
    addresses = []
    
    while True:
        value = input("ERS charge as decimal (e.g., 0.75, or 'done'): ").strip()
        
        if value.lower() == 'done':
            break
        
        try:
            ers_val = float(value)
        except ValueError:
            print("Please enter a decimal number or 'done'")
            continue
        
        if not addresses:
            addresses = scanner.scan_float(ers_val, tolerance=0.02)
        else:
            addresses = scanner.filter_addresses(addresses, ers_val, 
                                                 is_float=True, tolerance=0.02)
        
        if len(addresses) == 0:
            print("No addresses found. Try again.")
            break
        elif len(addresses) <= 5:
            print()
            print("Remaining addresses:")
            for addr in addresses:
                try:
                    val = scanner.pm.read_float(addr)
                    print(f"  0x{addr:X} = {val:.4f}")
                except Exception:
                    pass
            print()
        
        if len(addresses) == 1:
            print(f"✓ FOUND! ERS charge address: 0x{addresses[0]:X}")
            scanner.found_addresses["ers_charge"] = addresses[0]
            return addresses[0]
    
    if addresses:
        print(f"Best guess: 0x{addresses[0]:X}")
        scanner.found_addresses["ers_charge"] = addresses[0]
        return addresses[0]
    
    return None


def find_fuel(scanner: AutoScanner):
    """Interactive guide to find fuel address."""
    print()
    print("=" * 60)
    print("  FIND: FUEL LEVEL")
    print("=" * 60)
    print()
    print("In the game, note your remaining fuel (in kg).")
    print()
    
    addresses = []
    
    while True:
        value = input("Fuel level in kg (e.g., 45.2, or 'done'): ").strip()
        
        if value.lower() == 'done':
            break
        
        try:
            fuel_val = float(value)
        except ValueError:
            print("Please enter a number or 'done'")
            continue
        
        if not addresses:
            addresses = scanner.scan_float(fuel_val, tolerance=0.5)
        else:
            addresses = scanner.filter_addresses(addresses, fuel_val, 
                                                 is_float=True, tolerance=0.5)
        
        if len(addresses) == 0:
            print("No addresses found. Try again.")
            break
        elif len(addresses) <= 5:
            print()
            print("Remaining addresses:")
            for addr in addresses:
                try:
                    val = scanner.pm.read_float(addr)
                    print(f"  0x{addr:X} = {val:.2f}")
                except Exception:
                    pass
            print()
        
        if len(addresses) == 1:
            print(f"✓ FOUND! Fuel address: 0x{addresses[0]:X}")
            scanner.found_addresses["fuel"] = addresses[0]
            return addresses[0]
    
    if addresses:
        print(f"Best guess: 0x{addresses[0]:X}")
        scanner.found_addresses["fuel"] = addresses[0]
        return addresses[0]
    
    return None


def main():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║    🏎️  F1 Manager 2024 — Auto Memory Address Scanner  🏎️     ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("This tool will help you find memory addresses for:")
    print("  • Lap count")
    print("  • Your position")
    print("  • Tyre condition")
    print("  • ERS charge")
    print("  • Fuel level")
    print()
    print("REQUIREMENTS:")
    print("  1. F1 Manager 2024 is running")
    print("  2. You are in a race (not menu)")
    print("  3. Run this script as Administrator")
    print()
    
    input("Press Enter when ready...")
    
    scanner = AutoScanner()
    
    if not scanner.connect():
        print("\nFailed to connect. Make sure the game is running!")
        return
    
    print()
    print("Let's find the addresses one by one.")
    print("For each one, you'll enter the value you see in the game.")
    print("Then advance/change the value and enter it again.")
    print()
    
    # Find each address
    find_lap_count(scanner)
    find_position(scanner)
    find_tyre_condition(scanner)
    find_ers_charge(scanner)
    find_fuel(scanner)
    
    # Save results
    print()
    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print()
    
    for name, addr in scanner.found_addresses.items():
        print(f"  {name:20s}: 0x{addr:X}")
    
    print()
    scanner.save_results()
    
    print()
    print("Next step: Use these addresses in the main program!")
    print("Run: python main.py --mode memory --team 4")


if __name__ == "__main__":
    main()
