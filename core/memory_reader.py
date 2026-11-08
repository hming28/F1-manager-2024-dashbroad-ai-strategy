"""
memory_reader.py — Real-time memory reader for F1 Manager 2024.

Reads game memory directly using pymem for true real-time data.
Requires Cheat Engine to find memory addresses first.

Usage:
    reader = MemoryReader()
    reader.connect()
    reader.load_offsets("config/memory_offsets.yaml")
    
    while True:
        lap = reader.get_lap_count()
        pos = reader.get_car_position(0)
        tyre = reader.get_tyre_condition(0)
        print(f"L{lap} P{pos} Tyres {tyre:.0%}")
        time.sleep(1)
"""
from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Try to import pymem (Windows only) ──────────────────────────────────────

try:
    import pymem
    import pymem.process
    PYMEM_AVAILABLE = True
except ImportError:
    PYMEM_AVAILABLE = False
    logger.warning("pymem not installed. Memory reading disabled. Install with: pip install pymem")


# ── Memory Offsets ───────────────────────────────────────────────────────────

@dataclass
class MemoryOffsets:
    """
    Memory offsets for F1 Manager 2024.
    These need to be found using Cheat Engine.
    
    All offsets are relative to the base pointer.
    """
    # Process name
    process_name: str = "F1Manager24-Win64-Shipping.exe"
    
    # Base pointer (module + offset)
    # Example: "F1Manager24.exe+0x1A0B2C0"
    base_module: str = "F1Manager24-Win64-Shipping.exe"
    base_offset: int = 0x0
    
    # Pointer chain to race data
    # List of offsets to follow from base pointer
    race_data_offsets: list[int] = field(default_factory=lambda: [0x0])
    
    # Car data structure
    car_data_base_offset: int = 0x0      # Offset to car data array
    car_data_stride: int = 0x100         # Bytes between each car's data
    
    # Individual field offsets (relative to each car's data)
    position_offset: int = 0x00
    lap_count_offset: int = 0x00
    fuel_offset: int = 0x00
    ers_charge_offset: int = 0x00
    
    # Tyre data (4 tyres, each with condition)
    tyre_condition_offset: int = 0x00
    tyre_stride: int = 0x04              # Between each tyre
    
    # Weather
    weather_offset: int = 0x00
    
    # Safety car
    safety_car_offset: int = 0x00
    
    # Total laps
    total_laps_offset: int = 0x00


# ── Car Race Data ────────────────────────────────────────────────────────────

@dataclass
class MemoryCarData:
    """Data read from memory for a single car."""
    car_index: int
    position: int = 0
    lap_count: int = 0
    fuel: float = 0.0
    ers_charge: float = 0.0
    tyre_conditions: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    
    @property
    def avg_tyre_condition(self) -> float:
        if not self.tyre_conditions:
            return 0.0
        return sum(self.tyre_conditions) / len(self.tyre_conditions)


@dataclass
class MemoryRaceState:
    """Complete race state read from memory."""
    current_lap: int = 0
    total_laps: int = 0
    weather_state: int = 0
    safety_car_state: int = 0
    cars: list[MemoryCarData] = field(default_factory=list)
    timestamp: float = 0.0


# ── Memory Reader ────────────────────────────────────────────────────────────

class MemoryReader:
    """
    Reads F1 Manager 2024 game memory in real-time.
    
    Usage:
        reader = MemoryReader()
        reader.connect()
        reader.load_offsets("memory_offsets.yaml")
        
        state = reader.read_race_state()
        print(f"Lap {state.current_lap}, {len(state.cars)} cars")
    """
    
    def __init__(self):
        self.pm = None
        self.base_address = 0
        self.offsets = MemoryOffsets()
        self.connected = False
        self._race_data_ptr = 0
    
    def connect(self, process_name: Optional[str] = None) -> bool:
        """
        Connect to the game process.
        
        Returns True if successful.
        """
        if not PYMEM_AVAILABLE:
            logger.error("pymem not installed")
            return False
        
        name = process_name or self.offsets.process_name
        
        try:
            self.pm = pymem.Pymem(name)
            self.base_address = self.pm.base_address
            self.connected = True
            logger.info(f"Connected to {name}, base: 0x{self.base_address:X}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.connected = False
            return False
    
    def load_offsets(self, path: str):
        """Load memory offsets from YAML file."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        
        # Update offsets from file
        for key, value in data.items():
            if hasattr(self.offsets, key):
                setattr(self.offsets, key, value)
        
        logger.info(f"Loaded offsets from {path}")
    
    def save_offsets(self, path: str):
        """Save current offsets to YAML file."""
        import yaml
        data = {
            'process_name': self.offsets.process_name,
            'base_module': self.offsets.base_module,
            'base_offset': self.offsets.base_offset,
            'race_data_offsets': self.offsets.race_data_offsets,
            'car_data_base_offset': self.offsets.car_data_base_offset,
            'car_data_stride': self.offsets.car_data_stride,
            'position_offset': self.offsets.position_offset,
            'lap_count_offset': self.offsets.lap_count_offset,
            'fuel_offset': self.offsets.fuel_offset,
            'ers_charge_offset': self.offsets.ers_charge_offset,
            'tyre_condition_offset': self.offsets.tyre_condition_offset,
            'tyre_stride': self.offsets.tyre_stride,
            'weather_offset': self.offsets.weather_offset,
            'safety_car_offset': self.offsets.safety_car_offset,
            'total_laps_offset': self.offsets.total_laps_offset,
        }
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
        
        logger.info(f"Saved offsets to {path}")
    
    # ── Low-level memory operations ──────────────────────────────────────
    
    def read_int(self, address: int) -> int:
        """Read a 4-byte integer."""
        try:
            return self.pm.read_int(address)
        except Exception:
            return 0
    
    def read_float(self, address: int) -> float:
        """Read a 4-byte float."""
        try:
            return self.pm.read_float(address)
        except Exception:
            return 0.0
    
    def read_longlong(self, address: int) -> int:
        """Read an 8-byte pointer."""
        try:
            return self.pm.read_longlong(address)
        except Exception:
            return 0
    
    def read_pointer_chain(self, base: int, offsets: list[int]) -> int:
        """
        Follow a pointer chain.
        
        base → read ptr → +offset1 → read ptr → +offset2 → ... → final address
        """
        addr = base
        for i, offset in enumerate(offsets):
            try:
                if i < len(offsets) - 1:
                    addr = self.pm.read_longlong(addr) + offset
                else:
                    addr = addr + offset
            except Exception:
                return 0
        return addr
    
    # ── High-level data reading ──────────────────────────────────────────
    
    def get_race_data_base(self) -> int:
        """Get the base address of race data."""
        if self._race_data_ptr:
            return self._race_data_ptr
        
        # Follow pointer chain from base
        base = self.base_address + self.offsets.base_offset
        self._race_data_ptr = self.read_pointer_chain(
            base, self.offsets.race_data_offsets
        )
        return self._race_data_ptr
    
    def get_lap_count(self) -> int:
        """Get current lap count."""
        base = self.get_race_data_base()
        if not base:
            return 0
        return self.read_int(base + self.offsets.lap_count_offset)
    
    def get_total_laps(self) -> int:
        """Get total race laps."""
        base = self.get_race_data_base()
        if not base:
            return 0
        return self.read_int(base + self.offsets.total_laps_offset)
    
    def get_car_position(self, car_index: int) -> int:
        """Get a car's position."""
        base = self.get_race_data_base()
        if not base:
            return 0
        car_addr = base + self.offsets.car_data_base_offset + \
                   car_index * self.offsets.car_data_stride
        return self.read_int(car_addr + self.offsets.position_offset)
    
    def get_tyre_condition(self, car_index: int, tyre: int = 0) -> float:
        """
        Get tyre condition for a car.
        tyre: 0=FL, 1=FR, 2=BL, 3=BR
        Returns: 0.0 (destroyed) to 1.0 (new)
        """
        base = self.get_race_data_base()
        if not base:
            return 0.0
        car_addr = base + self.offsets.car_data_base_offset + \
                   car_index * self.offsets.car_data_stride
        tyre_addr = car_addr + self.offsets.tyre_condition_offset + \
                    tyre * self.offsets.tyre_stride
        return self.read_float(tyre_addr)
    
    def get_fuel(self, car_index: int) -> float:
        """Get fuel level for a car."""
        base = self.get_race_data_base()
        if not base:
            return 0.0
        car_addr = base + self.offsets.car_data_base_offset + \
                   car_index * self.offsets.car_data_stride
        return self.read_float(car_addr + self.offsets.fuel_offset)
    
    def get_ers_charge(self, car_index: int) -> float:
        """Get ERS charge for a car (0.0-1.0)."""
        base = self.get_race_data_base()
        if not base:
            return 0.0
        car_addr = base + self.offsets.car_data_base_offset + \
                   car_index * self.offsets.car_data_stride
        return self.read_float(car_addr + self.offsets.ers_charge_offset)
    
    def get_weather_state(self) -> int:
        """Get weather state (0=clear, 1=overcast, 2=light rain, 3=heavy rain)."""
        base = self.get_race_data_base()
        if not base:
            return 0
        return self.read_int(base + self.offsets.weather_offset)
    
    def get_safety_car_state(self) -> int:
        """Get safety car state (0=none, 1=SC, 2=VSC)."""
        base = self.get_race_data_base()
        if not base:
            return 0
        return self.read_int(base + self.offsets.safety_car_offset)
    
    # ── Snapshot builder ─────────────────────────────────────────────────
    
    def read_race_state(self, num_cars: int = 20) -> MemoryRaceState:
        """
        Read complete race state from memory.
        
        Returns a MemoryRaceState with all data.
        """
        state = MemoryRaceState(
            current_lap=self.get_lap_count(),
            total_laps=self.get_total_laps(),
            weather_state=self.get_weather_state(),
            safety_car_state=self.get_safety_car_state(),
            timestamp=time.time(),
        )
        
        for i in range(num_cars):
            car = MemoryCarData(
                car_index=i,
                position=self.get_car_position(i),
                fuel=self.get_fuel(i),
                ers_charge=self.get_ers_charge(i),
                tyre_conditions=[
                    self.get_tyre_condition(i, 0),  # FL
                    self.get_tyre_condition(i, 1),  # FR
                    self.get_tyre_condition(i, 2),  # BL
                    self.get_tyre_condition(i, 3),  # BR
                ],
            )
            state.cars.append(car)
        
        return state
    
    def is_connected(self) -> bool:
        """Check if connected to game process."""
        if not self.connected or not self.pm:
            return False
        try:
            # Try to read a small amount of memory
            self.pm.read_int(self.base_address)
            return True
        except Exception:
            self.connected = False
            return False
    
    def reconnect(self) -> bool:
        """Try to reconnect to game."""
        self._race_data_ptr = 0
        return self.connect()


# ── Address Scanner (helper for finding addresses) ──────────────────────────

class AddressScanner:
    """
    Helper class for finding memory addresses using Cheat Engine-like scanning.
    
    Usage:
        scanner = AddressScanner(reader)
        
        # Search for a known value
        addresses = scanner.search_int(32)  # searching for lap count = 32
        
        # Filter after value changes
        addresses = scanner.filter_int(addresses, 33)  # now lap = 33
        
        # Print remaining addresses
        for addr in addresses:
            print(f"0x{addr:X}")
    """
    
    def __init__(self, reader: MemoryReader):
        self.reader = reader
        self.pm = reader.pm
    
    def search_int(self, value: int, 
                   start: int = 0x0, end: int = 0x7FFFFFFFFFFF,
                   step: int = 4) -> list[int]:
        """Search for all addresses containing an integer value."""
        results = []
        try:
            addr = start
            while addr < end:
                try:
                    read_val = self.pm.read_int(addr)
                    if read_val == value:
                        results.append(addr)
                except Exception:
                    pass
                addr += step
                
                # Progress indicator
                if addr % (1024 * 1024 * 100) == 0:
                    logger.debug(f"Scanned up to 0x{addr:X}, found {len(results)} matches")
                    
        except KeyboardInterrupt:
            logger.info("Scan interrupted")
        
        return results
    
    def filter_int(self, addresses: list[int], value: int) -> list[int]:
        """Filter addresses to only those containing the given value."""
        results = []
        for addr in addresses:
            try:
                if self.pm.read_int(addr) == value:
                    results.append(addr)
            except Exception:
                pass
        return results
    
    def search_float(self, value: float, tolerance: float = 0.01,
                     start: int = 0x0, end: int = 0x7FFFFFFFFFFF) -> list[int]:
        """Search for all addresses containing a float value."""
        results = []
        try:
            addr = start
            while addr < end:
                try:
                    read_val = self.pm.read_float(addr)
                    if abs(read_val - value) < tolerance:
                        results.append(addr)
                except Exception:
                    pass
                addr += 4
        except KeyboardInterrupt:
            pass
        return results


# ── Convenience ──────────────────────────────────────────────────────────────

def quick_connect() -> Optional[MemoryReader]:
    """Quick connect to game and return reader, or None if failed."""
    reader = MemoryReader()
    if reader.connect():
        return reader
    return None
