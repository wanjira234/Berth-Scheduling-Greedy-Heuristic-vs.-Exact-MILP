"""
app.py

A tiny web UI for the berth-scheduling comparison. It serves index.html and
exposes a single JSON endpoint, POST /solve, that runs the *actual* project
code -- greedy_schedule() and milp_schedule() -- on a generated instance and
returns both schedules plus the same greedy-vs-MILP verdict the CLI prints.

Deliberately built on Python's standard library only (http.server), so it
runs with the exact environment the rest of the repo already needs
(pip install -r requirements.txt) -- no web framework to add.

Usage:
    python app.py                # then open http://localhost:8000
    python app.py --port 5000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The project's modules use flat imports (e.g. `from instance import ...`),
# which assumes src/ is on the path. Honour that instead of rewriting them.
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
sys.path.insert(0, SRC)

from instance import generate_instance  # noqa: E402
from greedy import greedy_schedule  # noqa: E402
from milp import milp_schedule  # noqa: E402

INDEX_HTML = os.path.join(HERE, "index.html")

# Guard rails so a demo click can't launch a huge instance or a five-minute
# solve. The HTML inputs enforce the same bounds; this is the backstop.
VESSELS_RANGE = (2, 24)
BERTHS_RANGE = (1, 8)
TIME_LIMIT_RANGE = (1, 60)


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _assignment_to_dict(a) -> dict:
    return {
        "vessel_id": a.vessel_id,
        "berth": a.berth,
        "start": round(a.start, 2),
        "finish": round(a.finish, 2),
        "tardiness": round(a.tardiness, 2),
        "weighted_tardiness": round(a.weighted_tardiness, 2),
    }


def _verdict(greedy_total: float, milp_total: float, milp_status: str) -> dict:
    """Port of the CLI's comparison logic.

    Uses a tolerance wide enough to absorb the rounding the MILP applies to
    each assignment's tardiness before summing, and bases the "hit the time
    limit" wording on the solver's *reported status*, not on the numbers.
    """
    tolerance = 0.01
    gap = greedy_total - milp_total

    if gap > tolerance:
        pct = (gap / greedy_total * 100) if greedy_total > 0 else 0.0
        return {
            "kind": "improve",
            "gap": round(gap, 2),
            "pct": round(pct, 1),
            "message": f"MILP improves on greedy by {gap:.2f} ({pct:.1f}%) "
                       f"in weighted tardiness.",
        }
    if gap < -tolerance:
        if milp_status == "Optimal":
            return {
                "kind": "worse_optimal",
                "gap": round(gap, 2),
                "message": "MILP result is worse than greedy despite a "
                           "certified-optimal status -- this would indicate a "
                           "formulation bug, not expected behavior.",
            }
        return {
            "kind": "worse_timelimit",
            "gap": round(gap, 2),
            "message": f"MILP result is worse than greedy -- solver status was "
                       f"'{milp_status}', meaning it did not certify an optimum "
                       f"within the time limit. This is expected at larger "
                       f"instance sizes: it's the actual point of the comparison.",
        }
    note = "" if milp_status == "Optimal" else f" (solver status: {milp_status})"
    return {
        "kind": "tie",
        "gap": round(gap, 2),
        "message": f"Greedy already matched the MILP result on this instance{note}.",
    }


def solve(params: dict) -> dict:
    vessels = _clamp(int(params.get("vessels", 8)), *VESSELS_RANGE)
    berths = _clamp(int(params.get("berths", 2)), *BERTHS_RANGE)
    seed = int(params.get("seed", 7))
    tight = bool(params.get("tight", False))
    time_limit = _clamp(int(params.get("time_limit", 10)), *TIME_LIMIT_RANGE)

    slack = (0.0, 4.0) if tight else (5.0, 20.0)
    instance = generate_instance(
        n_vessels=vessels, n_berths=berths, seed=seed, due_slack_range=slack
    )

    t0 = time.perf_counter()
    g = greedy_schedule(instance)
    greedy_ms = (time.perf_counter() - t0) * 1000.0

    m, meta = milp_schedule(instance, time_limit_seconds=time_limit)

    return {
        "params": {
            "vessels": vessels,
            "berths": berths,
            "seed": seed,
            "tight": tight,
            "time_limit": time_limit,
        },
        "instance": [
            {
                "id": v.id,
                "arrival": v.arrival,
                "duration": v.duration,
                "due": v.due,
                "weight": v.weight,
            }
            for v in sorted(instance.vessels, key=lambda v: v.id)
        ],
        "greedy": {
            "assignments": [_assignment_to_dict(a) for a in g.assignments],
            "total_weighted_tardiness": round(g.total_weighted_tardiness, 2),
            "total_tardiness": round(g.total_tardiness(), 2),
            "makespan": round(g.makespan(), 2),
            "solve_ms": round(greedy_ms, 3),
        },
        "milp": {
            "assignments": [_assignment_to_dict(a) for a in m.assignments],
            "total_weighted_tardiness": round(m.total_weighted_tardiness, 2),
            "total_tardiness": round(m.total_tardiness(), 2),
            "makespan": round(m.makespan(), 2),
            "solve_seconds": meta["solve_time_seconds"],
            "status": meta["status"],
            "n_binary_vars": meta["n_binary_vars"],
        },
        "verdict": _verdict(
            g.total_weighted_tardiness, m.total_weighted_tardiness, meta["status"]
        ),
    }


class Handler(BaseHTTPRequestHandler):
    # Quieter, single-line request logging.
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            try:
                with open(INDEX_HTML, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self._send_json(500, {"error": "index.html not found next to app.py"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/solve":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            params = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"bad request body: {exc}"})
            return

        try:
            result = solve(params)
        except Exception as exc:  # noqa: BLE001 -- surface any solver error to the UI
            self._send_json(500, {"error": f"solve failed: {exc}"})
            return

        self._send_json(200, result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Web UI for the berth-scheduling comparison.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Berth-scheduling UI running at {url}")
    print("Open that address in your browser. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
