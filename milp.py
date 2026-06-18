"""
milp.py

An exact mixed-integer linear programming formulation of the same berth
scheduling problem the greedy heuristic solves -- solved with PuLP (CBC
solver under the hood).

Honest naming note: this is a MILP, not a pure LP. A genuinely linear
program can't express "vessel A's slot on this berth must not overlap
vessel B's slot" -- that disjunction (A before B, OR B before A) requires
binary decision variables. Calling it "the LP" colloquially, as port
scheduling literature often does, is a simplification I'm reproducing in
plain conversation but not in the code or in this docstring.

Formulation (disjunctive / big-M style):

Decision variables:
  x[v, b]      in {0, 1}   -- 1 if vessel v is assigned to berth b
  s[v]         >= 0         -- start time of vessel v
  y[v, w]      in {0, 1}   -- 1 if v precedes w on whatever berth they share
  T[v]         >= 0         -- tardiness of vessel v

Constraints:
  sum_b x[v, b] == 1                          for every vessel v
                                               (each vessel gets exactly one berth)

  s[v] >= arrival[v]                          (can't start before arrival)

  For every pair (v, w) assigned to the SAME berth, exactly one of:
      s[w] >= s[v] + duration[v]   (v finishes before w starts), or
      s[v] >= s[w] + duration[w]   (w finishes before v starts)
  enforced via: s[w] >= s[v] + duration[v] - M*(1 - y[v,w]) - M*(2 - x[v,b] - x[w,b])
  and the symmetric constraint, summed over a shared-berth indicator.

  T[v] >= s[v] + duration[v] - due[v]
  T[v] >= 0

Objective:
  minimize sum_v weight[v] * T[v]

This is a textbook NP-hard scheduling formulation. For larger instances
(dozens of vessels, many berths) solve time grows quickly because of the
combinatorial pairwise-ordering variables -- this is exactly the trade-off
the README discusses: the heuristic is fast and "good enough" at scale,
the MILP is exact but only practical for instances this size.
"""

from __future__ import annotations

import time as _time

import pulp

from instance import Instance
from greedy import Assignment, Schedule


def milp_schedule(instance: Instance, time_limit_seconds: int = 30) -> tuple[Schedule, dict]:
    vessels = instance.vessels
    n = len(vessels)
    berths = range(instance.n_berths)

    # Big-M: must be larger than any plausible start-time gap. Using the
    # latest possible finish time across all vessels is a safe, simple bound.
    M = max(v.arrival + v.duration for v in vessels) + max(v.duration for v in vessels) + 1

    prob = pulp.LpProblem("berth_scheduling", pulp.LpMinimize)

    x = {
        (v.id, b): pulp.LpVariable(f"x_{v.id}_{b}", cat="Binary")
        for v in vessels for b in berths
    }
    s = {v.id: pulp.LpVariable(f"s_{v.id}", lowBound=v.arrival) for v in vessels}
    T = {v.id: pulp.LpVariable(f"T_{v.id}", lowBound=0) for v in vessels}

    # Ordering variable for every unordered pair of distinct vessels
    pairs = [(v1.id, v2.id) for i, v1 in enumerate(vessels) for v2 in vessels[i + 1:]]
    y = {(i, j): pulp.LpVariable(f"y_{i}_{j}", cat="Binary") for (i, j) in pairs}

    # Each vessel assigned to exactly one berth
    for v in vessels:
        prob += pulp.lpSum(x[v.id, b] for b in berths) == 1

    # Tardiness definition
    by_id = {v.id: v for v in vessels}
    for v in vessels:
        prob += T[v.id] >= s[v.id] + v.duration - v.due

    # Pairwise non-overlap, but only enforced when both vessels share a berth.
    # "Same berth" indicator: sum_b x[i,b]*x[j,b] == 1 if same berth -- but
    # that's quadratic, so instead we enforce ordering using a per-berth
    # same-berth proxy: z[i,j,b] = x[i,b] AND x[j,b], linearized below.
    z = {}
    for (i, j) in pairs:
        for b in berths:
            zv = pulp.LpVariable(f"z_{i}_{j}_{b}", cat="Binary")
            z[(i, j, b)] = zv
            # standard AND-linearization: z <= x_i, z <= x_j, z >= x_i + x_j - 1
            prob += zv <= x[i, b]
            prob += zv <= x[j, b]
            prob += zv >= x[i, b] + x[j, b] - 1

    for (i, j) in pairs:
        same_berth = pulp.lpSum(z[(i, j, b)] for b in berths)
        di = by_id[i].duration
        dj = by_id[j].duration

        # If same_berth == 1: exactly one ordering must hold.
        # y[i,j] == 1 means i goes before j.
        prob += s[j] >= s[i] + di - M * (1 - y[(i, j)]) - M * (1 - same_berth)
        prob += s[i] >= s[j] + dj - M * y[(i, j)] - M * (1 - same_berth)

    prob += pulp.lpSum(by_id[v_id].weight * T[v_id] for v_id in by_id)

    start_time = _time.perf_counter()
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_seconds)
    status = prob.solve(solver)
    solve_time = _time.perf_counter() - start_time

    # Known PuLP/CBC quirk: when CBC hits the time limit it can still report
    # pulp.LpStatus[status] == "Optimal" even though it only returned the
    # best incumbent found, not a certified optimum. Don't trust the label
    # blindly -- if we used essentially the whole time budget, treat the
    # result as "best found, not certified optimal" rather than "Optimal".
    hit_time_limit = solve_time >= time_limit_seconds * 0.98
    reported_status = pulp.LpStatus[status]
    if hit_time_limit and reported_status == "Optimal":
        reported_status = "Stopped at time limit (best incumbent, not certified optimal)"

    assignments: list[Assignment] = []
    for v in vessels:
        berth_assigned = next(b for b in berths if pulp.value(x[v.id, b]) > 0.5)
        start = pulp.value(s[v.id])
        finish = start + v.duration
        tardiness = max(0.0, finish - v.due)
        assignments.append(
            Assignment(
                vessel_id=v.id,
                berth=berth_assigned,
                start=round(start, 2),
                finish=round(finish, 2),
                tardiness=round(tardiness, 2),
                weighted_tardiness=round(tardiness * v.weight, 2),
            )
        )

    assignments.sort(key=lambda a: a.vessel_id)
    total = sum(a.weighted_tardiness for a in assignments)

    schedule = Schedule(assignments=assignments, total_weighted_tardiness=total, method="milp")

    meta = {
        "status": reported_status,
        "solve_time_seconds": round(solve_time, 3),
        "n_binary_vars": len(x) + len(y) + len(z),
    }

    return schedule, meta
