"""
race_intel.py — Competitor intelligence for F1 Manager 2024.

Tracks all 20 cars and provides strategic insights:
- Who is on what strategy
- Undercut/overcut threats
- Who is vulnerable to overtaking
- Championship implications
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.models import CarRaceState, RaceSnapshot, Track, DriverData


@dataclass
class CompetitorIntel:
    """Intelligence about a specific competitor."""
    car_index: int
    position: int
    driver_name: str
    team_id: int
    gap_to_my_car_ms: int
    
    # Strategy analysis
    pit_stops_done: int
    likely_strategy: str          # "1-stop" / "2-stop" / "3-stop" / "unknown"
    estimated_next_pit_lap: int   # 0 if unknown
    
    # Threat assessment
    tyre_condition: float         # 0.0-1.0
    is_threat: bool               # can they challenge us?
    is_vulnerable: bool           # can we overtake them?
    threat_level: str             # "HIGH" / "MEDIUM" / "LOW" / "NONE"
    
    # Notes
    notes: list[str]


@dataclass
class RaceIntelReport:
    """Full intelligence report for the race."""
    my_position: int
    my_gap_to_leader_ms: int
    gap_to_car_ahead_ms: int
    gap_to_car_behind_ms: int
    
    # Key competitors
    immediate_threats: list[CompetitorIntel]  # cars within 5s
    pit_window_intel: list[CompetitorIntel]   # cars likely pitting soon
    vulnerable_cars: list[CompetitorIntel]    # cars we can overtake
    
    # Strategy opportunities
    undercut_opportunities: list[str]
    overcut_opportunities: list[str]
    
    # Championship context
    championship_rivals: list[str]
    
    summary: str


class RaceIntel:
    """
    Analyzes competitor strategies and identifies opportunities.
    """
    
    def __init__(self, drivers: Optional[list[DriverData]] = None):
        self._drivers = {d.staff_id: d for d in (drivers or [])}
    
    def analyze(self, snapshot: RaceSnapshot, my_team_id: int,
                track: Track) -> RaceIntelReport:
        """
        Generate a full intelligence report.
        """
        my_cars = snapshot.get_my_cars(my_team_id)
        if not my_cars:
            return self._empty_report()
        
        # Use the higher-placed car as reference
        my_car = min(my_cars, key=lambda c: c.race_position)
        
        # Analyze all competitors
        competitors = []
        for car in snapshot.cars:
            if car.team_id == my_team_id:
                continue
            intel = self._analyze_competitor(car, my_car, snapshot, track)
            competitors.append(intel)
        
        # Categorize
        immediate_threats = [c for c in competitors if abs(c.gap_to_my_car_ms) < 5000]
        pit_window = [c for c in competitors if c.estimated_next_pit_lap > 0 
                     and c.estimated_next_pit_lap <= snapshot.current_lap + 5]
        vulnerable = [c for c in competitors if c.is_vulnerable]
        
        # Undercut/overcut analysis
        undercut_ops = self._find_undercut_opportunities(my_car, competitors, track)
        overcut_ops = self._find_overcut_opportunities(my_car, competitors, track, snapshot.current_lap)
        
        # Gaps
        ahead = [c for c in snapshot.cars if c.race_position == my_car.race_position - 1]
        behind = [c for c in snapshot.cars if c.race_position == my_car.race_position + 1]
        
        gap_ahead = int((my_car.total_race_time - ahead[0].total_race_time) * 1000) if ahead else 0
        gap_behind = int((behind[0].total_race_time - my_car.total_race_time) * 1000) if behind else 0
        
        # Summary
        summary = self._generate_summary(my_car, competitors, immediate_threats, 
                                         vulnerable, undercut_ops)
        
        return RaceIntelReport(
            my_position=my_car.race_position,
            my_gap_to_leader_ms=int(my_car.total_race_time * 1000),
            gap_to_car_ahead_ms=gap_ahead,
            gap_to_car_behind_ms=gap_behind,
            immediate_threats=immediate_threats,
            pit_window_intel=pit_window,
            vulnerable_cars=vulnerable,
            undercut_opportunities=undercut_ops,
            overcut_opportunities=overcut_ops,
            championship_rivals=[],
            summary=summary,
        )
    
    def _analyze_competitor(self, car: CarRaceState, my_car: CarRaceState,
                            snapshot: RaceSnapshot, track: Track) -> CompetitorIntel:
        """Analyze a single competitor."""
        driver = self._drivers.get(car.driver_id)
        driver_name = f"Car#{car.car_index}"
        if driver:
            driver_name = f"{driver.first_name} {driver.last_name}".strip() or driver.abbreviation
        
        gap_ms = int((car.total_race_time - my_car.total_race_time) * 1000)
        
        # Estimate strategy
        likely_strategy = self._estimate_strategy(car, snapshot, track)
        
        # Threat assessment
        tyre_cond = car.avg_tyre_condition
        is_threat = (gap_ms > -3000 and gap_ms < 10000 and 
                    (tyre_cond > my_car.avg_tyre_condition + 0.1 or car.has_damage))
        is_vulnerable = (gap_ms > 0 and gap_ms < 5000 and 
                        (tyre_cond < my_car.avg_tyre_condition - 0.15 or car.has_damage))
        
        if is_threat and gap_ms < 2000:
            threat_level = "HIGH"
        elif is_threat:
            threat_level = "MEDIUM"
        elif is_vulnerable:
            threat_level = "LOW"
        else:
            threat_level = "NONE"
        
        notes = []
        if car.has_damage:
            notes.append(f"Damage: severity {car.damage_severity}/18")
        if car.pit_stops_had > my_car.pit_stops_had:
            notes.append(f"Has done {car.pit_stops_had} stops (you: {my_car.pit_stops_had})")
        
        return CompetitorIntel(
            car_index=car.car_index,
            position=car.race_position,
            driver_name=driver_name,
            team_id=car.team_id,
            gap_to_my_car_ms=gap_ms,
            pit_stops_done=car.pit_stops_had,
            likely_strategy=likely_strategy,
            estimated_next_pit_lap=self._estimate_next_pit(car, snapshot, track),
            tyre_condition=tyre_cond,
            is_threat=is_threat,
            is_vulnerable=is_vulnerable,
            threat_level=threat_level,
            notes=notes,
        )
    
    def _estimate_strategy(self, car: CarRaceState, snapshot: RaceSnapshot,
                           track: Track) -> str:
        """Estimate a car's strategy from their pit stop pattern."""
        stops = car.pit_stops_had
        progress = snapshot.current_lap / max(1, track.laps)
        
        if stops == 0:
            if progress > 0.6:
                return "1-stop (late)"
            return "1-stop"
        elif stops == 1:
            if progress < 0.5:
                return "2-stop"
            return "1-stop (done)"
        elif stops == 2:
            return "2-stop (done)"
        else:
            return f"{stops}-stop"
    
    def _estimate_next_pit(self, car: CarRaceState, snapshot: RaceSnapshot,
                           track: Track) -> int:
        """Estimate when a competitor will pit next."""
        if car.avg_tyre_condition < 0.35:
            return snapshot.current_lap + 2  # very soon
        elif car.avg_tyre_condition < 0.50:
            return snapshot.current_lap + 5
        elif car.avg_tyre_condition < 0.65:
            return snapshot.current_lap + 10
        return 0  # unknown
    
    def _find_undercut_opportunities(self, my_car: CarRaceState,
                                     competitors: list[CompetitorIntel],
                                     track: Track) -> list[str]:
        """Find cars we can undercut."""
        ops = []
        for c in competitors:
            if (0 < c.gap_to_my_car_ms < 5000 and 
                c.tyre_condition > my_car.avg_tyre_condition + 0.1):
                ops.append(
                    f"P{c.position} {c.driver_name}: gap {c.gap_to_my_car_ms/1000:.1f}s, "
                    f"their tyres better ({c.tyre_condition:.0%} vs {my_car.avg_tyre_condition:.0%})"
                )
        return ops
    
    def _find_overcut_opportunities(self, my_car: CarRaceState,
                                     competitors: list[CompetitorIntel],
                                     track: Track,
                                     current_lap: int = 0) -> list[str]:
        """Find cars we can overcut (stay out longer)."""
        ops = []
        for c in competitors:
            if (c.estimated_next_pit_lap > 0 and 
                c.estimated_next_pit_lap <= current_lap + 3 and
                c.gap_to_my_car_ms > -3000):
                ops.append(
                    f"P{c.position} {c.driver_name}: pitting ~lap {c.estimated_next_pit_lap}, "
                    f"stay out to overcut"
                )
        return ops
    
    def _generate_summary(self, my_car: CarRaceState,
                          competitors: list[CompetitorIntel],
                          threats: list[CompetitorIntel],
                          vulnerable: list[CompetitorIntel],
                          undercut_ops: list[str]) -> str:
        """Generate a human-readable summary."""
        parts = [f"P{my_car.race_position} | Tyres: {my_car.avg_tyre_condition:.0%}"]
        
        if threats:
            names = ", ".join(t.driver_name for t in threats[:3])
            parts.append(f"⚠️ Threats: {names}")
        
        if vulnerable:
            names = ", ".join(v.driver_name for v in vulnerable[:3])
            parts.append(f"🎯 Targets: {names}")
        
        if undercut_ops:
            parts.append(f"⚡ {len(undercut_ops)} undercut opportunity(ies)")
        
        return " | ".join(parts)
    
    def _empty_report(self) -> RaceIntelReport:
        return RaceIntelReport(
            my_position=0, my_gap_to_leader_ms=0,
            gap_to_car_ahead_ms=0, gap_to_car_behind_ms=0,
            immediate_threats=[], pit_window_intel=[], vulnerable_cars=[],
            undercut_opportunities=[], overcut_opportunities=[],
            championship_rivals=[], summary="No data",
        )
