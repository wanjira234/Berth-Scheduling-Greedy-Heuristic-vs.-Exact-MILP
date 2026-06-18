# Berth Scheduling: Greedy Heuristic vs. Exact MILP

A small port-scheduling problem solved two ways — a cheap heuristic and an
exact mixed-integer linear program — with the actual trade-off between them
measured rather than assumed. Built as a fast, scoped companion to a larger
PPO/GAE-based port-scheduling project elsewhere in my portfolio: that
project handles sequential, uncertain scheduling decisions with
reinforcement learning; this one is the static, fully-known version of the
problem, which is exactly what makes it solvable exactly.

## The problem

A set of vessels arrive at a port at known times. Each vessel needs an
uninterrupted block of time at one of several berths to be serviced. A berth
can only serve one vessel at a time. Vessels also have a due date and a
tardiness penalty weight (think: contract penalties or cargo value), so
being late is allowed but costs something, and some lateness costs more
than others. The goal: assign every vessel to a berth and a start time that
minimizes total weighted tardiness across the whole instance.

This is a version of the berth allocation problem, a well-studied scheduling
problem in maritime operations research, and it's closely related to
classic parallel-machine scheduling with release dates and due dates — a
problem that's NP-hard in general, which is precisely why comparing a fast
heuristic against an exact solver is an interesting exercise and not a
foregone conclusion.

## The two methods

**Greedy heuristic** (`src/greedy.py`): process vessels in arrival order;
for each one, assign it to whichever berth becomes free soonest. No
lookahead, no backtracking. Runs in well under a millisecond regardless of
instance size.

**Exact MILP** (`src/milp.py`): a disjunctive mixed-integer formulation
solved with PuLP (CBC solver). Binary variables decide which berth each
vessel uses and, for every pair of vessels sharing a berth, which one goes
first; continuous variables track start times and tardiness. This finds the
true optimum — when it has enough time to certify one.

A naming note that matters: the second method is a MILP, not a pure linear
program. A genuinely linear program can't express "vessel A's slot must not
overlap vessel B's slot" — that either/or requires binary variables. Port
scheduling discussions often say "the LP" loosely; the code and docstrings
here are precise about it being a MILP, because the distinction is the
reason this problem needs integer variables at all.

## What the comparison actually shows

Run on a small instance (8 vessels, 2 berths) where the solver can certify
optimality within seconds:

```
Method   Total weighted tardiness   Solve time   Status
Greedy   24.34                      0.03 ms      —
MILP     15.17                      0.58 s       Optimal

MILP improves on greedy by 9.17 (37.7%) in weighted tardiness.
```

Run on a larger, more congested instance (12 vessels, 3 berths) with a
20-second solver time limit:

```
Method   Total weighted tardiness   Solve time   Status
Greedy   5.07                       0.07 ms      —
MILP     5.07                       20.32 s      Stopped at time limit
                                                  (best incumbent, not
                                                  certified optimal)
```

These two runs tell the actual story. On the small instance, exact solving
finds a meaningfully better schedule than the heuristic, and does it fast
enough to be free. On the larger instance, the MILP's combinatorial
structure — a binary ordering variable for every pair of vessels that might
share a berth — grows fast enough that it can't even match the heuristic's
result inside the time budget, let alone certify an improvement. That
crossover, not a single "MILP always wins" headline number, is the actual
finding: a heuristic's value is highest exactly where exact methods start
to struggle.

## A bug worth documenting, not hiding

While building the seed-sweep used to write this README, one instance
(`--vessels 8 --berths 2 --seed 2`) produced a result where the CLI reported
"MILP hit its time limit" even though the solver's actual status was
`Optimal`. The cause: the MILP code rounds each vessel's tardiness to 2
decimal places before summing, while the greedy code doesn't round at all,
so the two totals can differ by a few thousandths even when the underlying
schedules are equally good. The original comparison logic used a `1e-6`
tolerance — far tighter than that rounding gap — and, worse, inferred "the
solver must have hit its time limit" from the numbers alone instead of
checking the solver's actual reported status.

The fix widens the tolerance to absorb the rounding gap and, more
importantly, bases the message on the real solver status rather than a
guess derived from a noisy number. A regression test
(`test_milp_rounding_does_not_create_false_tardiness_gap`) locks this case
in so it can't silently regress. This is left in the README rather than
quietly fixed and forgotten because it's a more honest demonstration of the
actual engineering process than a changelog that only shows clean code.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Default: 10 vessels, 2 berths, loose due dates
python src/cli.py

# Specify instance size and a fixed seed for reproducibility
python src/cli.py --vessels 12 --berths 3 --seed 7

# Tight due dates -- makes berth congestion actually bite
python src/cli.py --vessels 12 --berths 3 --seed 7 --tight

# Give the MILP solver more time on a harder instance
python src/cli.py --vessels 20 --berths 4 --tight --time-limit 60

# Summary table only, skip the full per-vessel schedules
python src/cli.py --vessels 12 --berths 3 --tight --quiet
```

## Running the tests

```bash
python -m pytest tests/ -v
# or, without pytest:
python tests/test_scheduling.py
```

Six tests cover: reproducibility of generated instances, feasibility of
both schedules (no overlaps, no vessel starts before it arrives, every
vessel scheduled exactly once), the core correctness invariant that a
certified-optimal MILP solution can never be worse than the heuristic, a
sanity check that "tight" instances actually produce tardiness, and the
rounding-tolerance regression above.

## Project structure

```
berth-scheduling/
├── src/
│   ├── instance.py    # synthetic problem instance generator
│   ├── greedy.py       # list-scheduling heuristic
│   ├── milp.py          # exact MILP formulation (PuLP / CBC)
│   └── cli.py             # comparison CLI
├── tests/
│   └── test_scheduling.py
├── requirements.txt
└── README.md
```

## Possible extensions

- Sweep instance size systematically and plot the heuristic's optimality
  gap as a function of vessel count and berth congestion, rather than
  reporting individual seeds by hand.
- Add a second heuristic (e.g. earliest-due-date-first) to compare more
  than one cheap method against the exact baseline.
- Warm-start the MILP from the greedy solution to see whether it reaches a
  better incumbent faster on larger instances.
