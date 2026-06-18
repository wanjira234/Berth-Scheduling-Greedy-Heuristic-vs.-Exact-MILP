"""
test_scheduling.py

Run with:
    python -m pytest tests/ -v
or:
    python tests/test_scheduling.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from instance import generate_instance  # noqa: E402
from greedy import greedy_schedule  # noqa: E402
from milp import milp_schedule  # noqa: E402


def _no_overlaps(schedule) -> bool:
    by_berth = {}
    for a in schedule.assignments:
        by_berth.setdefault(a.berth, []).append(a)
    for items in by_berth.values():
        items = sorted(items, key=lambda a: a.start)
        for i in range(len(items) - 1):
            if items[i].finish > items[i + 1].start + 1e-6:
                return False
    return True


def _respects_arrival(schedule, instance) -> bool:
    arrival_by_id = {v.id: v.arrival for v in instance.vessels}
    return all(a.start >= arrival_by_id[a.vessel_id] - 1e-6 for a in schedule.assignments)


def _every_vessel_scheduled_once(schedule, instance) -> bool:
    scheduled_ids = sorted(a.vessel_id for a in schedule.assignments)
    expected_ids = sorted(v.id for v in instance.vessels)
    return scheduled_ids == expected_ids


def test_generate_instance_is_reproducible():
    a = generate_instance(n_vessels=8, n_berths=2, seed=99)
    b = generate_instance(n_vessels=8, n_berths=2, seed=99)
    assert [v.arrival for v in a.vessels] == [v.arrival for v in b.vessels]
    assert [v.duration for v in a.vessels] == [v.duration for v in b.vessels]


def test_greedy_produces_feasible_schedule():
    instance = generate_instance(n_vessels=12, n_berths=3, seed=5, due_slack_range=(0.0, 4.0))
    schedule = greedy_schedule(instance)
    assert _no_overlaps(schedule)
    assert _respects_arrival(schedule, instance)
    assert _every_vessel_scheduled_once(schedule, instance)


def test_milp_produces_feasible_schedule():
    instance = generate_instance(n_vessels=8, n_berths=2, seed=5, due_slack_range=(0.0, 4.0))
    schedule, meta = milp_schedule(instance, time_limit_seconds=15)
    assert _no_overlaps(schedule)
    assert _respects_arrival(schedule, instance)
    assert _every_vessel_scheduled_once(schedule, instance)


def test_milp_is_never_worse_than_greedy_when_solved_to_optimality():
    """The defining correctness property of this whole project: an exact
    solver that actually reaches a certified optimum can never produce a
    worse objective value than a heuristic on the same problem. If this
    fails, the MILP formulation has a bug -- it is not a matter of
    interpretation."""
    instance = generate_instance(n_vessels=8, n_berths=2, seed=11, due_slack_range=(0.0, 4.0))
    greedy_result = greedy_schedule(instance)
    milp_result, meta = milp_schedule(instance, time_limit_seconds=20)

    if meta["status"] == "Optimal":
        assert milp_result.total_weighted_tardiness <= greedy_result.total_weighted_tardiness + 1e-6, (
            f"MILP claimed optimal ({milp_result.total_weighted_tardiness}) but is worse than "
            f"greedy ({greedy_result.total_weighted_tardiness}) -- formulation bug."
        )
    else:
        # If the solver didn't certify optimality, we can't make this claim --
        # that's expected and handled, not silently ignored.
        print(f"  (skipped strict check: solver status was '{meta['status']}', not certified optimal)")


def test_tight_instance_creates_genuine_tardiness_for_greedy():
    """Sanity check that the 'tight' parameter actually produces a congested,
    non-trivial instance -- otherwise the comparison has nothing to show."""
    instance = generate_instance(n_vessels=10, n_berths=2, seed=7, due_slack_range=(0.0, 4.0))
    schedule = greedy_schedule(instance)
    assert schedule.total_weighted_tardiness > 0, "expected a congested instance to produce some tardiness"


def test_milp_rounding_does_not_create_false_tardiness_gap():
    """Regression test for a real bug found during development: MILP rounds
    each assignment's tardiness to 2 dp before summing, while greedy doesn't
    round at all. On seed=2 this produces a ~0.004 numeric gap between two
    schedules that are actually equally good (MILP status: Optimal). A
    comparison tolerance of 1e-6 was too tight and caused the CLI to
    misreport this as "MILP hit its time limit" when the solver had in fact
    certified optimality. The fix: only call MILP "worse" if the gap exceeds
    a tolerance wide enough to absorb this rounding (0.01), and never infer
    "hit time limit" without checking the actual solver status."""
    instance = generate_instance(n_vessels=8, n_berths=2, seed=2, due_slack_range=(0.0, 4.0))
    greedy_result = greedy_schedule(instance)
    milp_result, meta = milp_schedule(instance, time_limit_seconds=15)

    assert meta["status"] == "Optimal", "this regression case assumes the solver certifies optimality"
    gap = abs(milp_result.total_weighted_tardiness - greedy_result.total_weighted_tardiness)
    assert gap < 0.01, (
        f"expected the known rounding gap (~0.004) to stay under the 0.01 comparison "
        f"tolerance used in cli.py, got {gap}"
    )


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
