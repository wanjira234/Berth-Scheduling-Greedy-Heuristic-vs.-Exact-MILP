"""
cli.py

Compare the greedy heuristic against the MILP formulation on a synthetic
berth-scheduling instance.

Usage:
    python src/cli.py
    python src/cli.py --vessels 12 --berths 3 --seed 7
    python src/cli.py --vessels 20 --berths 4 --tight --time-limit 30
"""

from __future__ import annotations

import argparse
import time

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from instance import generate_instance
from greedy import greedy_schedule
from milp import milp_schedule

console = Console()


def render_schedule(schedule, title: str) -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Vessel")
    table.add_column("Berth")
    table.add_column("Start")
    table.add_column("Finish")
    table.add_column("Tardiness")
    for a in schedule.assignments:
        style = "red" if a.tardiness > 0 else "green"
        table.add_row(
            str(a.vessel_id), str(a.berth),
            f"{a.start:.1f}", f"{a.finish:.1f}",
            f"[{style}]{a.tardiness:.1f}[/{style}]",
        )
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare greedy heuristic vs MILP for berth scheduling.")
    parser.add_argument("--vessels", type=int, default=10)
    parser.add_argument("--berths", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--tight", action="store_true", help="Use tight due-date slack (0-4 units) to make congestion bite")
    parser.add_argument("--time-limit", type=int, default=20, help="MILP solver time limit in seconds")
    parser.add_argument("--quiet", action="store_true", help="Only print the summary, not full schedules")
    args = parser.parse_args()

    slack = (0.0, 4.0) if args.tight else (5.0, 20.0)
    instance = generate_instance(
        n_vessels=args.vessels, n_berths=args.berths, seed=args.seed, due_slack_range=slack
    )

    console.print(Panel(
        f"[bold]Berth scheduling comparison[/bold]\n"
        f"{args.vessels} vessels · {args.berths} berths · seed {args.seed} · "
        f"{'tight' if args.tight else 'loose'} due dates",
        border_style="blue",
    ))

    t0 = time.perf_counter()
    g = greedy_schedule(instance)
    g_time = time.perf_counter() - t0

    m, meta = milp_schedule(instance, time_limit_seconds=args.time_limit)

    if not args.quiet:
        console.print(render_schedule(g, "Greedy schedule"))
        console.print(render_schedule(m, "MILP schedule"))

    summary = Table(title="Summary")
    summary.add_column("Method")
    summary.add_column("Total weighted tardiness")
    summary.add_column("Solve time")
    summary.add_column("Status")
    summary.add_row("Greedy", f"{g.total_weighted_tardiness:.2f}", f"{g_time*1000:.2f} ms", "—")
    summary.add_row("MILP", f"{m.total_weighted_tardiness:.2f}", f"{meta['solve_time_seconds']:.2f} s", meta["status"])
    console.print(summary)

    # Use a tolerance wide enough to absorb the rounding MILP applies to each
    # assignment's tardiness (round to 2 dp) before summing, since that can
    # accumulate to a few hundredths even when both schedules are equally
    # good. More importantly: don't infer "hit the time limit" from the
    # numbers alone -- ask the solver's actual reported status, since a
    # small numeric gap can appear even when the solve was certified optimal.
    tolerance = 0.01
    gap = g.total_weighted_tardiness - m.total_weighted_tardiness

    if gap > tolerance:
        pct = (gap / g.total_weighted_tardiness * 100) if g.total_weighted_tardiness > 0 else 0
        console.print(f"\n[green]MILP improves on greedy by {gap:.2f} ({pct:.1f}%) in weighted tardiness.[/green]")
    elif gap < -tolerance:
        if meta["status"] == "Optimal":
            console.print(
                "\n[red]MILP result is worse than greedy despite a certified-optimal status -- "
                "this would indicate a formulation bug, not expected behavior.[/red]"
            )
        else:
            console.print(
                f"\n[yellow]MILP result is worse than greedy -- solver status was '{meta['status']}', "
                "meaning it did not certify an optimum within the time limit. This is expected at "
                "larger instance sizes: it's the actual point of the comparison.[/yellow]"
            )
    else:
        note = "" if meta["status"] == "Optimal" else f" (solver status: {meta['status']})"
        console.print(f"\n[dim]Greedy already matched the MILP result on this instance{note}.[/dim]")


if __name__ == "__main__":
    main()
