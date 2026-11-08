"""
monte_carlo.py — Monte Carlo Race Simulator for F1 Manager 2024.

Performs stochastic perturbation simulations (1,000+ iterations) near pit windows:
- Safety Car / VSC sudden deployments and field compression
- Traffic reintegration, dirty air, and DRS train blocking
- Competitor strategy response (undercut reaction, pit duration variance & mistakes)
- Lap time jitter and tyre degradation variances

Calculates win probability, podium probability, and expected championship points.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.models import (
    CarRaceState, RaceSnapshot, Track, TyreCompound, SafetyCarState
)
from strategy.tyre_model import TyreModel

logger = logging.getLogger(__name__)

# Official F1 points scoring system (P1 through P10)
F1_POINTS = {
    1: 25,
    2: 18,
    3: 15,
    4: 12,
    5: 10,
    6: 8,
    7: 6,
    8: 4,
    9: 2,
    10: 1,
}


@dataclass
class MonteCarloResult:
    """Stochastic simulation results for a candidate strategy."""
    strategy_name: str
    pit_lap: int
    compound: TyreCompound
    stint_length: int
    expected_points: float              # Expected F1 points (0.0 to 25.0)
    win_probability: float              # P(P1)
    podium_probability: float           # P(P1-P3)
    points_probability: float           # P(P1-P10)
    median_finish_position: float       # Median finish position
    p10_position: int                   # Pessimistic (10th percentile / lower bound)
    p90_position: int                   # Optimistic (90th percentile / upper bound)
    traffic_risk: float                 # 0.0 - 1.0 (% runs delayed by traffic)
    sc_benefit_frequency: float         # 0.0 - 1.0 (% runs benefiting from SC)
    avg_race_time_sec: float
    description: str = ""


@dataclass
class SimulationReport:
    """Consolidated report across all candidate strategies evaluated."""
    best_result: MonteCarloResult
    all_results: List[MonteCarloResult]
    simulations_run: int
    execution_time_ms: float
    summary_reason: str


class MonteCarloSimulator:
    """
    Monte Carlo Race Simulator evaluating candidate pit strategies under
    stochastic race perturbations.
    """

    def __init__(self, tyre_model: Optional[TyreModel] = None,
                 default_simulations: int = 1000):
        self.tyre_model = tyre_model if tyre_model is not None else TyreModel()
        self.default_simulations = default_simulations

    def simulate(self, snapshot: RaceSnapshot, my_car: CarRaceState, track: Track,
                 candidate_stops: List[Tuple[str, int, TyreCompound]],
                 num_simulations: Optional[int] = None,
                 seed: Optional[int] = None) -> SimulationReport:
        """
        Run Monte Carlo simulations for a list of candidate strategies.

        Args:
            snapshot: Current race snapshot
            my_car: Player's car state
            track: Current track
            candidate_stops: List of (name, pit_lap, target_compound)
            num_simulations: Number of Monte Carlo iterations (default 1000)
            seed: Optional random seed for deterministic testing

        Returns:
            SimulationReport with probability metrics and recommended candidate
        """
        start_time = time.perf_counter()
        n_sims = num_simulations or self.default_simulations
        rng = np.random.default_rng(seed)

        current_lap = snapshot.current_lap
        total_laps = track.laps
        remaining_laps = max(1, total_laps - current_lap)

        if not candidate_stops:
            # Default fallback: stay out or pit on next lap on Medium
            candidate_stops = [
                ("Stay Out", 0, TyreCompound.MEDIUM),
                ("Box Lap +1", current_lap + 1, TyreCompound.MEDIUM),
            ]

        # Extract track attributes
        cal_profile = self.tyre_model.get_calibrated_profile(track) if hasattr(self.tyre_model, "get_calibrated_profile") else None
        if cal_profile:
            sc_chance_per_race = float(cal_profile.get("sc_probability", track.safety_car_chance))
            overtake_diff = float(cal_profile.get("overtaking_difficulty", 0.50))
            pit_loss_base = float(cal_profile.get("pit_lane_loss_sec", track.pit_lane_time_loss))
        else:
            sc_chance_per_race = float(track.safety_car_chance)
            overtake_diff = 0.50
            pit_loss_base = float(track.pit_lane_time_loss)

        sc_loss_base = float(track.safety_car_time_loss if track.safety_car_time_loss > 0 else pit_loss_base * 0.65)
        base_lap_sec = (cal_profile.get("base_lap_time_ms", 90000) / 1000.0) if cal_profile else (track.fastest_lap + 2.5)

        # Build competitor field (top 20 cars)
        competitors = self._extract_competitor_field(snapshot, my_car, base_lap_sec)

        # Pre-generate stochastic environmental factors across all simulations
        # 1. Safety car hazard per lap
        sc_hazard_per_lap = min(0.06, (sc_chance_per_race / max(40, total_laps)) * 1.15)
        # Random matrix shape: (N, remaining_laps)
        sc_matrix = rng.random((n_sims, remaining_laps)) < sc_hazard_per_lap

        # If already under SC, first 2-3 laps remain under SC
        if snapshot.is_safety_car:
            sc_matrix[:, :min(3, remaining_laps)] = True

        # Run rollouts for each candidate strategy
        results: List[MonteCarloResult] = []

        for name, pit_lap, compound in candidate_stops:
            res = self._simulate_candidate(
                candidate_name=name,
                pit_lap=pit_lap,
                target_compound=compound,
                current_lap=current_lap,
                total_laps=total_laps,
                remaining_laps=remaining_laps,
                my_car=my_car,
                competitors=competitors,
                track=track,
                cal_profile=cal_profile,
                pit_loss_base=pit_loss_base,
                sc_loss_base=sc_loss_base,
                base_lap_sec=base_lap_sec,
                overtake_diff=overtake_diff,
                sc_matrix=sc_matrix,
                n_sims=n_sims,
                rng=rng,
            )
            results.append(res)

        # Select the best strategy: highest expected points, tie-breaker = win probability
        best_candidate = max(results, key=lambda r: (r.expected_points, r.win_probability, -r.median_finish_position))

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        summary = (
            f"Recommended: {best_candidate.strategy_name} | "
            f"Exp Pts: {best_candidate.expected_points:.1f} | "
            f"Podium: {best_candidate.podium_probability:.1%} | "
            f"Win: {best_candidate.win_probability:.1%} | "
            f"P10-P90: P{best_candidate.p90_position}-P{best_candidate.p10_position}"
        )

        return SimulationReport(
            best_result=best_candidate,
            all_results=results,
            simulations_run=n_sims,
            execution_time_ms=elapsed_ms,
            summary_reason=summary,
        )

    def _extract_competitor_field(self, snapshot: RaceSnapshot, my_car: CarRaceState,
                                  base_lap_sec: float) -> List[Dict[str, Any]]:
        """Extract baseline status of all competitors on track."""
        cars = snapshot.cars if snapshot.cars else [my_car]
        competitors = []

        for c in cars:
            is_me = (c.car_index == my_car.car_index)
            # Baseline pace offset based on position and rating
            pace_offset = (c.race_position - 1) * 0.12
            total_time = c.total_race_time if c.total_race_time > 0 else (c.race_position * 1.5)
            competitors.append({
                "car_index": c.car_index,
                "is_me": is_me,
                "position": c.race_position,
                "total_time": total_time,
                "tyre_cond": c.avg_tyre_condition if c.avg_tyre_condition > 0 else 0.70,
                "pit_stops": c.pit_stops_had,
                "pace_offset": pace_offset,
            })

        # Ensure we have at least 10 cars in simulation
        if len(competitors) < 10:
            for p in range(len(competitors) + 1, 21):
                competitors.append({
                    "car_index": p + 50,
                    "is_me": False,
                    "position": p,
                    "total_time": my_car.total_race_time + (p - my_car.race_position) * 2.5,
                    "tyre_cond": 0.65,
                    "pit_stops": 0,
                    "pace_offset": p * 0.15,
                })

        return competitors

    def _simulate_candidate(self, candidate_name: str, pit_lap: int,
                            target_compound: TyreCompound, current_lap: int,
                            total_laps: int, remaining_laps: int,
                            my_car: CarRaceState, competitors: List[Dict[str, Any]],
                            track: Track, cal_profile: Optional[Dict[str, Any]],
                            pit_loss_base: float, sc_loss_base: float,
                            base_lap_sec: float, overtake_diff: float,
                            sc_matrix: np.ndarray, n_sims: int,
                            rng: np.random.Generator) -> MonteCarloResult:
        """Simulate n_sims race outcomes for one candidate strategy."""
        is_pitting = (pit_lap > current_lap and pit_lap <= total_laps)

        # Compound pace and degradation
        analysis_new = self.tyre_model.analyze_compound(target_compound, track)
        deg_per_lap_new = analysis_new.degradation_per_lap
        compound_pace_delta_new = analysis_new.pace_delta_vs_medium_ms / 1000.0

        current_compound = target_compound  # approximation
        analysis_cur = self.tyre_model.analyze_compound(current_compound, track)
        deg_per_lap_cur = analysis_cur.degradation_per_lap

        # 1. Simulate My Car Race Time
        # Base driver lap noise: N(0, 0.22)
        my_driver_noise = rng.normal(0.0, 0.22, (n_sims, remaining_laps))

        # Base lap times for my car
        my_lap_times = np.zeros((n_sims, remaining_laps))

        # Pit stop execution times: Base 2.5s with N(0, 0.35s) + 3% pit mistake probability (+2.5s to 5.0s)
        pit_execution = rng.normal(2.5, 0.35, n_sims)
        pit_mistake = (rng.random(n_sims) < 0.035) * rng.uniform(2.5, 5.5, n_sims)
        total_pit_duration = np.maximum(2.0, pit_execution + pit_mistake)

        sc_benefit_flags = np.zeros(n_sims, dtype=bool)
        traffic_delay_sec = np.zeros(n_sims)

        # Compute laps before pit and laps after pit
        laps_to_pit = (pit_lap - current_lap) if is_pitting else remaining_laps

        # Lap-by-lap simulation for my car
        wear = 1.0 - my_car.avg_tyre_condition
        for idx in range(remaining_laps):
            lap_num = current_lap + 1 + idx
            is_sc = sc_matrix[:, idx]

            # Check if this lap is the pit lap
            if is_pitting and lap_num == pit_lap:
                # Car executes pit stop
                effective_pit_loss = np.where(is_sc, sc_loss_base, pit_loss_base)
                my_lap_times[:, idx] += effective_pit_loss + total_pit_duration
                # Mark SC benefit if pitted under SC
                sc_benefit_flags |= is_sc
                # Reset tyre wear for new set
                wear = 0.0
                deg_rate = deg_per_lap_new
                compound_delta = compound_pace_delta_new
            else:
                deg_rate = deg_per_lap_new if (is_pitting and lap_num > pit_lap) else deg_per_lap_cur
                compound_delta = compound_pace_delta_new if (is_pitting and lap_num > pit_lap) else 0.0

            # Tyre wear and degradation penalty
            wear += deg_rate * rng.normal(1.0, 0.08, n_sims)
            wear_penalty = np.where(wear < 0.30, 0.0, np.where(wear < 0.75, (wear - 0.30) * 1.8, 1.0 + (wear - 0.75) * 6.0))

            # Lap pace under green flag or safety car
            green_lap = base_lap_sec + compound_delta + wear_penalty + my_driver_noise[:, idx]
            sc_lap = base_lap_sec * 1.35  # Delta pace under safety car
            my_lap_times[:, idx] += np.where(is_sc, sc_lap, green_lap)

        # 2. Traffic Reintegration Simulation
        if is_pitting:
            # Check traffic risk upon rejoining:
            # Cars within 2.0s ahead with slower pace
            rejoin_lap_idx = min(remaining_laps - 1, laps_to_pit)
            # Traffic probability influenced by overtaking difficulty (e.g. Monaco=0.98 vs Monza=0.35)
            base_traffic_risk = min(0.85, 0.25 + overtake_diff * 0.45)
            caught_in_traffic = (rng.random(n_sims) < base_traffic_risk) & (~sc_benefit_flags)

            # If caught in traffic, delay for 2-5 laps until DRS/tyre delta enables overtake
            traffic_laps = rng.integers(2, 6, size=n_sims)
            loss_per_traffic_lap = rng.uniform(0.7, 1.6, size=n_sims)
            traffic_delay_sec = caught_in_traffic * traffic_laps * loss_per_traffic_lap
            my_lap_times[:, rejoin_lap_idx] += traffic_delay_sec

        my_total_time = np.sum(my_lap_times, axis=1)

        # 3. Competitor Rollout & Finishing Position Computation
        # For each simulation, evaluate finishing positions across all 20 cars
        my_pos_arr = np.zeros(n_sims, dtype=int)

        # Base competitor times
        other_times = []
        for comp in competitors:
            if comp["is_me"]:
                continue
            # Competitor base pace
            comp_pace = base_lap_sec + comp["pace_offset"]
            comp_noise = rng.normal(0.0, 0.24, (n_sims, remaining_laps))

            # Competitor strategy: 65% reaction to our undercut if within 3s
            gap_to_me = abs(comp["position"] - my_car.race_position)
            comp_pits = False
            if is_pitting and gap_to_me <= 2:
                # Reactive pit probability
                reacts = rng.random(n_sims) < 0.65
                comp_pit_lap = np.where(reacts, pit_lap + 1, pit_lap + rng.integers(3, 8, size=n_sims))
                comp_pits = True
            else:
                comp_pit_lap = np.full(n_sims, current_lap + rng.integers(5, 18))

            comp_laps = np.zeros((n_sims, remaining_laps))
            for idx in range(remaining_laps):
                lap_num = current_lap + 1 + idx
                is_sc = sc_matrix[:, idx]
                is_comp_pit = (lap_num == comp_pit_lap)
                comp_pit_loss = np.where(is_sc, sc_loss_base, pit_loss_base) + rng.normal(2.6, 0.4, n_sims)
                lap_add = np.where(is_comp_pit, comp_pit_loss, 0.0)
                comp_lap_time = np.where(is_sc, base_lap_sec * 1.35, comp_pace + comp_noise[:, idx])
                comp_laps[:, idx] = comp_lap_time + lap_add

            c_total = np.sum(comp_laps, axis=1) + (comp["total_time"] - my_car.total_race_time)
            other_times.append(c_total)

        if other_times:
            # other_matrix: shape (len_competitors, n_sims)
            other_matrix = np.array(other_times)
            # Count how many cars are faster than my_car
            cars_ahead = np.sum(other_matrix < my_total_time[np.newaxis, :], axis=0)
            my_positions = 1 + cars_ahead
        else:
            my_positions = np.ones(n_sims, dtype=int)

        # 4. Statistical Aggregation
        p1_wins = np.count_nonzero(my_positions == 1)
        podiums = np.count_nonzero(my_positions <= 3)
        points_finishes = np.count_nonzero(my_positions <= 10)

        # Compute Expected Points: sum(P(Pos == k) * F1_POINTS[k])
        exp_points = 0.0
        for pos, pts in F1_POINTS.items():
            count = np.count_nonzero(my_positions == pos)
            exp_points += (count / n_sims) * pts

        median_pos = float(np.median(my_positions))
        p10 = int(np.percentile(my_positions, 90))  # pessimistic
        p90 = int(np.percentile(my_positions, 10))  # optimistic

        traffic_risk_rate = float(np.mean(traffic_delay_sec > 0.1)) if is_pitting else 0.0
        sc_benefit_rate = float(np.mean(sc_benefit_flags))

        return MonteCarloResult(
            strategy_name=candidate_name,
            pit_lap=pit_lap,
            compound=target_compound,
            stint_length=total_laps - pit_lap if is_pitting else remaining_laps,
            expected_points=round(exp_points, 2),
            win_probability=round(p1_wins / n_sims, 3),
            podium_probability=round(podiums / n_sims, 3),
            points_probability=round(points_finishes / n_sims, 3),
            median_finish_position=round(median_pos, 1),
            p10_position=p10,
            p90_position=p90,
            traffic_risk=round(traffic_risk_rate, 2),
            sc_benefit_frequency=round(sc_benefit_rate, 2),
            avg_race_time_sec=float(np.mean(my_total_time)),
            description=f"Exp Pts: {exp_points:.1f} | Pod: {podiums/n_sims:.0%} | Win: {p1_wins/n_sims:.0%}",
        )
