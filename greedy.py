"""
greedy.py

A list-scheduling heuristic for the berth allocation problem.

Rule: process vessels in order of arrival time (earliest first). For each
vessel, assign it to whichever berth becomes free soonest, but never start
service before the vessel actually arrives. This is the same idea as the
classic "shortest available machine first" rule used in parallel-machine
scheduling -- cheap to compute, no lookahead, and easy to explain.
"""

from __future__ import annotations

from dataclasses import dataclass

from instance import Instance, Vessel


@dataclass
class Assignment:
    vessel_id: int
    berth: int
    start: float
    finish: float
    tardiness: float
    weighted_tardiness: float


@dataclass
class Schedule:
    assignments: list[Assignment]
    total_weighted_tardiness: float
    method: str

    def total_tardiness(self) -> float:
        return sum(a.tardiness for a in self.assignments)

    def makespan(self) -> float:
        return max(a.finish for a in self.assignments) if self.assignments else 0.0


def greedy_schedule(instance: Instance) -> Schedule:
    berth_free_at = [0.0] * instance.n_berths
    assignments: list[Assignment] = []

    # Process in arrival order -- a vessel can't be considered before it shows up.
    ordered = sorted(instance.vessels, key=lambda v: v.arrival)

    for vessel in ordered:
        # Pick the berth that becomes free soonest.
        berth = min(range(instance.n_berths), key=lambda b: berth_free_at[b])
        start = max(vessel.arrival, berth_free_at[berth])
        finish = start + vessel.duration
        tardiness = max(0.0, finish - vessel.due)
        weighted_tardiness = tardiness * vessel.weight

        assignments.append(
            Assignment(
                vessel_id=vessel.id,
                berth=berth,
                start=start,
                finish=finish,
                tardiness=tardiness,
                weighted_tardiness=weighted_tardiness,
            )
        )
        berth_free_at[berth] = finish

    # Restore original vessel ordering in the output for readability
    assignments.sort(key=lambda a: a.vessel_id)
    total = sum(a.weighted_tardiness for a in assignments)

    return Schedule(assignments=assignments, total_weighted_tardiness=total, method="greedy")
