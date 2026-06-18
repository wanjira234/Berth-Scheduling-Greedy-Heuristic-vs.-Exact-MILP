"""
instance.py

Generates synthetic port berth-scheduling problem instances.

The problem: N vessels arrive at a port at known times and each needs a
fixed amount of berth time to be serviced. There are B berths (parallel
servers). Each vessel must be assigned to exactly one berth; a berth can
only serve one vessel at a time; a vessel cannot start service before it
arrives. The objective is to minimize total weighted tardiness against each
vessel's due date.

This is the classic unrelated/identical parallel-machine scheduling problem
with release dates and due dates -- NP-hard in general, which is exactly
why comparing a cheap heuristic against an exact (but slower) formulation
is an interesting exercise rather than a trivial one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Vessel:
    id: int
    arrival: float       # earliest time service can start
    duration: float       # how long berthing takes
    due: float            # target completion time
    weight: float          # tardiness penalty weight (e.g. cargo value / contract penalty)


@dataclass
class Instance:
    vessels: list[Vessel]
    n_berths: int
    seed: int

    def __repr__(self) -> str:
        return f"Instance(n_vessels={len(self.vessels)}, n_berths={self.n_berths}, seed={self.seed})"


def generate_instance(
    n_vessels: int = 10,
    n_berths: int = 3,
    seed: int = 42,
    max_arrival: float = 40.0,
    duration_range: tuple[float, float] = (4.0, 12.0),
    due_slack_range: tuple[float, float] = (5.0, 20.0),
    weight_range: tuple[float, float] = (1.0, 5.0),
) -> Instance:
    """Build a random but reproducible berth-scheduling instance.

    Due dates are generated as arrival + duration + some slack, so that due
    dates are achievable in isolation but become tight once berths start
    competing for the same time slots -- this is what makes the scheduling
    decision actually matter.
    """
    rng = random.Random(seed)
    vessels = []
    for i in range(n_vessels):
        arrival = round(rng.uniform(0, max_arrival), 1)
        duration = round(rng.uniform(*duration_range), 1)
        slack = round(rng.uniform(*due_slack_range), 1)
        due = round(arrival + duration + slack, 1)
        weight = round(rng.uniform(*weight_range), 2)
        vessels.append(Vessel(id=i, arrival=arrival, duration=duration, due=due, weight=weight))

    return Instance(vessels=vessels, n_berths=n_berths, seed=seed)
