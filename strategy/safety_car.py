"""
safety_car.py — Safety car strategy for F1 Manager 2024.

Detects safety car deployments and evaluates:
- Free pit stop opportunity
- Position gain/loss from pitting
- Tyre condition vs track position trade-off
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.models import (
    CarRaceState, RaceSnapshot, SafetyCarState, TyreCompound, Track,
)


@dataclass
class SafetyCarDecision:
    """Recommendation for safety car period."""
    should_pit: bool
    reason: str
    position_change: int         # expected position change (+ = gain, - = loss)
    time_saved_ms: int           # time saved by pitting under SC vs normal
    priority: str                # "MUST_DO" / "RECOMMENDED" / "STAY_OUT"


class SafetyCarStrategy:
    """
    Evaluates safety car pit stop opportunities.
    """
    
    def evaluate(self, snapshot: RaceSnapshot, my_car: CarRaceState,
                 track: Track) -> Optional[SafetyCarDecision]:
        """
        Evaluate whether to pit under safety car.
        
        Returns None if no safety car is active.
        """
        if not snapshot.is_safety_car:
            return None
        
        # Calculate time saved by pitting under SC
        normal_pit_loss = track.pit_lane_time_loss * 1000  # ms
        sc_pit_loss = track.safety_car_time_loss * 1000    # ms
        time_saved = normal_pit_loss - sc_pit_loss
        
        # Estimate position change
        position_change = self._estimate_position_change(snapshot, my_car)
        
        # Tyre condition factor
        tyre_condition = my_car.avg_tyre_condition
        tyre_factor = self._tyre_urgency(tyre_condition)
        
        # Make decision
        if tyre_condition < 0.30:
            # Tyres are critical — MUST pit
            return SafetyCarDecision(
                should_pit=True,
                reason=f"🛞 CRITICAL tyres ({tyre_condition:.0%}) + FREE pit under SC!",
                position_change=position_change,
                time_saved_ms=time_saved,
                priority="MUST_DO",
            )
        
        if position_change >= 0:
            # We gain or break even — pit!
            return SafetyCarDecision(
                should_pit=True,
                reason=f"✅ Free pit under SC! Save {time_saved/1000:.1f}s, position {'gain' if position_change > 0 else 'unchanged'}",
                position_change=position_change,
                time_saved_ms=time_saved,
                priority="RECOMMENDED",
            )
        
        if position_change >= -2 and tyre_condition < 0.60:
            # Small position loss but tyres need changing
            return SafetyCarDecision(
                should_pit=True,
                reason=f"⚠️ Pit under SC: lose {abs(position_change)} position(s) but save {time_saved/1000:.1f}s + fresh tyres",
                position_change=position_change,
                time_saved_ms=time_saved,
                priority="RECOMMENDED",
            )
        
        if position_change < -2:
            # Significant position loss — stay out
            return SafetyCarDecision(
                should_pit=False,
                reason=f"❌ Stay out! Would lose {abs(position_change)} positions. Tyres OK at {tyre_condition:.0%}",
                position_change=position_change,
                time_saved_ms=time_saved,
                priority="STAY_OUT",
            )
        
        # Default: stay out if tyres are decent
        return SafetyCarDecision(
            should_pit=False,
            reason=f"Stay out. Tyres at {tyre_condition:.0%}, position loss risk.",
            position_change=position_change,
            time_saved_ms=time_saved,
            priority="STAY_OUT",
        )
    
    def _estimate_position_change(self, snapshot: RaceSnapshot,
                                  my_car: CarRaceState) -> int:
        """
        Estimate position change from pitting under safety car.
        Positive = gain, negative = loss.
        """
        # Count cars that are currently in the pit
        cars_in_pit = sum(1 for c in snapshot.cars if c.is_in_pit)
        
        # Count cars directly behind us that might benefit
        my_pos = my_car.race_position
        
        # Simple heuristic: if cars ahead are pitting, we gain by staying out
        # If cars behind are staying out, we lose by pitting
        gain = 0
        
        for car in snapshot.cars:
            if car.car_index == my_car.car_index:
                continue
            
            if car.is_in_pit:
                # This car is pitting — if they were ahead, we gain
                if car.race_position < my_pos:
                    gain += 1
                # If they were behind, no change
            else:
                # Car staying out — if they were behind us and we pit, they pass
                if car.race_position > my_pos:
                    gain -= 1
        
        return gain
    
    def _tyre_urgency(self, condition: float) -> float:
        """0.0 = no urgency, 1.0 = critical"""
        if condition >= 0.70:
            return 0.0
        elif condition >= 0.40:
            return (0.70 - condition) / 0.30
        else:
            return 1.0
