"""
streamlit_app.py

Streamlit UI for the berth-scheduling comparison. Wraps the exact same
greedy_schedule() and milp_schedule() used by the CLI and the original
stdlib web server, so the numbers match the rest of the project.

Run locally:
    streamlit run streamlit_app.py

Deploy: push this repo to GitHub, go to share.streamlit.io, pick the repo,
set the main file to streamlit_app.py — requirements.txt in the repo root
tells Streamlit Cloud what to install (pulp, rich, streamlit, plotly).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).parent
SRC = HERE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from instance import generate_instance  # noqa: E402
from greedy import greedy_schedule  # noqa: E402
from milp import milp_schedule  # noqa: E402


VESSELS_RANGE = (2, 24)
BERTHS_RANGE = (1, 8)
TIME_LIMIT_RANGE = (1, 60)

ONTIME_COLOR = "#2ea089"
LATE_COLOR = "#e0653a"
GREEDY_COLOR = "#1361a0"
MILP_COLOR = "#17a2b8"

PRESETS = [
    {
        "label": "MILP wins (9×2, tight)",
        "vessels": 9, "berths": 2, "seed": 3, "tight": True, "time_limit": 10,
    },
    {
        "label": "Uncongested (8×2, loose)",
        "vessels": 8, "berths": 2, "seed": 7, "tight": False, "time_limit": 10,
    },
    {
        "label": "Crossover (12×3, tight)",
        "vessels": 12, "berths": 3, "seed": 7, "tight": True, "time_limit": 15,
    },
]


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _verdict(greedy_total: float, milp_total: float, milp_status: str) -> dict:
    tolerance = 0.01
    gap = greedy_total - milp_total
    if gap > tolerance:
        pct = (gap / greedy_total * 100) if greedy_total > 0 else 0.0
        return {
            "kind": "improve",
            "gap": round(gap, 2),
            "pct": round(pct, 1),
            "message": f"MILP improves on greedy by {gap:.2f} ({pct:.1f}%) in weighted tardiness.",
        }
    if gap < -tolerance:
        if milp_status == "Optimal":
            return {
                "kind": "worse_optimal",
                "gap": round(gap, 2),
                "message": "MILP result is worse than greedy despite a certified-optimal status — this would indicate a formulation bug, not expected behavior.",
            }
        return {
            "kind": "worse_timelimit",
            "gap": round(gap, 2),
            "message": f"MILP result is worse than greedy — solver status was '{milp_status}', meaning it did not certify an optimum within the time limit. This is expected at larger instance sizes: it's the actual point of the comparison.",
        }
    note = "" if milp_status == "Optimal" else f" (solver status: {milp_status})"
    return {
        "kind": "tie",
        "gap": round(gap, 2),
        "message": f"Greedy already matched the MILP result on this instance{note}.",
    }


def solve(vessels: int, berths: int, seed: int, tight: bool, time_limit: int):
    vessels = _clamp(vessels, *VESSELS_RANGE)
    berths = _clamp(berths, *BERTHS_RANGE)
    time_limit = _clamp(time_limit, *TIME_LIMIT_RANGE)

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
            "vessels": vessels, "berths": berths, "seed": seed,
            "tight": tight, "time_limit": time_limit,
        },
        "instance": [
            {
                "id": v.id, "arrival": v.arrival, "duration": v.duration,
                "due": v.due, "weight": v.weight,
            }
            for v in sorted(instance.vessels, key=lambda v: v.id)
        ],
        "greedy": {
            "assignments": [
                {
                    "vessel_id": a.vessel_id, "berth": a.berth,
                    "start": a.start, "finish": a.finish,
                    "tardiness": a.tardiness, "weighted_tardiness": a.weighted_tardiness,
                }
                for a in g.assignments
            ],
            "total_weighted_tardiness": g.total_weighted_tardiness,
            "total_tardiness": g.total_tardiness(),
            "makespan": g.makespan(),
            "solve_ms": round(greedy_ms, 3),
        },
        "milp": {
            "assignments": [
                {
                    "vessel_id": a.vessel_id, "berth": a.berth,
                    "start": a.start, "finish": a.finish,
                    "tardiness": a.tardiness, "weighted_tardiness": a.weighted_tardiness,
                }
                for a in m.assignments
            ],
            "total_weighted_tardiness": m.total_weighted_tardiness,
            "total_tardiness": m.total_tardiness(),
            "makespan": m.makespan(),
            "solve_seconds": meta["solve_time_seconds"],
            "status": meta["status"],
            "n_binary_vars": meta["n_binary_vars"],
        },
        "verdict": _verdict(
            g.total_weighted_tardiness, m.total_weighted_tardiness, meta["status"]
        ),
    }


def apply_preset(key: int):
    p = PRESETS[key]
    st.session_state.vessels = p["vessels"]
    st.session_state.berths = p["berths"]
    st.session_state.seed = p["seed"]
    st.session_state.tight = p["tight"]
    st.session_state.time_limit = p["time_limit"]


def render_verdict(v: dict):
    kind = v["kind"]
    if kind == "improve":
        st.success(v["message"], icon="🏆")
    elif kind == "tie":
        st.info(v["message"], icon="🤝")
    elif kind == "worse_timelimit":
        st.warning(v["message"], icon="⏳")
    elif kind == "worse_optimal":
        st.error(v["message"], icon="🐛")
    else:
        st.write(v["message"])


def render_metrics(greedy: dict, milp: dict):
    g_wins = greedy["total_weighted_tardiness"] < milp["total_weighted_tardiness"] - 0.01
    m_wins = milp["total_weighted_tardiness"] < greedy["total_weighted_tardiness"] - 0.01

    def card(name, total, winner, rows, accent):
        header = f"### {name}"
        if winner:
            header += " &nbsp; 🥇 Best"
        with st.container(border=True):
            st.markdown(
                f"<div style='border-left: 4px solid {accent}; padding-left: 12px;'>"
                f"{header}</div>",
                unsafe_allow_html=True,
            )
            st.metric(
                "Total weighted tardiness",
                f"{total:.2f}",
            )
            for label, value in rows:
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;"
                    f"padding:4px 0;border-top:1px dashed #e5e7eb;"
                    f"font-size:14px;'>"
                    f"<span style='color:#6b7280;'>{label}</span>"
                    f"<span style='font-family:monospace;font-weight:600;'>{value}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    col_g, col_m = st.columns(2)
    with col_g:
        card(
            "Greedy",
            greedy["total_weighted_tardiness"],
            g_wins,
            [
                ("Solve time", f"{greedy['solve_ms']:.3f} ms"),
                ("Total tardiness", f"{greedy['total_tardiness']:.2f}"),
                ("Makespan", f"{greedy['makespan']:.2f}"),
                ("Method", "List scheduling"),
            ],
            GREEDY_COLOR,
        )
    with col_m:
        card(
            "MILP",
            milp["total_weighted_tardiness"],
            m_wins,
            [
                ("Solve time", f"{milp['solve_seconds']:.2f} s"),
                ("Status", milp["status"]),
                ("Binary vars", f"{milp['n_binary_vars']:,}"),
                ("Makespan", f"{milp['makespan']:.2f}"),
            ],
            MILP_COLOR,
        )


def render_gantt(title: str, tag: str, assignments: list[dict], n_berths: int,
                 max_time: float, inst_map: dict):
    st.markdown(f"**{title}** <span style='color:#6b7280;font-family:monospace;font-size:13px;'>"
                f"· total weighted tardiness {tag:.2f}</span>",
                unsafe_allow_html=True)

    fig = go.Figure()

    for b in range(n_berths):
        for a in assignments:
            if a["berth"] != b:
                continue
            v = inst_map.get(a["vessel_id"], {})
            is_late = a["tardiness"] > 0
            color = LATE_COLOR if is_late else ONTIME_COLOR
            tip = (
                f"<b>Vessel V{a['vessel_id']}</b><br>"
                f"Berth {b}<br>"
                f"Start: {a['start']:.2f} → Finish: {a['finish']:.2f}<br>"
                f"Due: {v.get('due', '?'):.2f} · Weight: {v.get('weight', '?'):.2f}<br>"
                f"Tardiness: {a['tardiness']:.2f} "
                f"(weighted {a['weighted_tardiness']:.2f})"
            )
            fig.add_trace(go.Bar(
                y=[f"Berth {b}"],
                x=[a["finish"] - a["start"]],
                base=[a["start"]],
                orientation="h",
                marker=dict(color=color, line=dict(width=1, color="white")),
                name=f"V{a['vessel_id']}",
                text=f"V{a['vessel_id']}",
                textposition="inside",
                insidetextanchor="middle",
                hovertemplate=tip + "<extra></extra>",
                showlegend=False,
                width=0.7,
            ))

    fig.update_layout(
        height=140 + n_berths * 48,
        margin=dict(l=60, r=20, t=10, b=40),
        plot_bgcolor="#f7f9fb",
        paper_bgcolor="white",
        xaxis=dict(
            title="Time (arbitrary units)",
            gridcolor="#e5e7eb",
            range=[0, max_time],
            showgrid=True,
        ),
        yaxis=dict(
            categoryorder="array",
            categoryarray=[f"Berth {b}" for b in range(n_berths - 1, -1, -1)],
        ),
        barmode="overlay",
        bargap=0.05,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_instance(instance: list[dict]):
    rows = [
        {
            "Vessel": f"V{v['id']}",
            "Arrival": round(v["arrival"], 1),
            "Duration": round(v["duration"], 1),
            "Due": round(v["due"], 1),
            "Weight": round(v["weight"], 2),
        }
        for v in instance
    ]
    st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
    )


def main():
    st.set_page_config(
        page_title="Berth Scheduling — Greedy vs. Exact MILP",
        page_icon="⚓",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        .block-container { padding-top: 2rem; padding-bottom: 4rem; }
        section[data-testid="stSidebar"] > div { padding-top: 2rem; }
        .preset-row { display:flex; gap:8px; flex-wrap:wrap; margin: 6px 0 16px 0; }
        .preset-btn {
            border: 1px solid #dde5ec; background: #fff; color: #1361a0;
            border-radius: 999px; padding: 6px 14px; font-size: 13px;
            font-weight: 600; cursor: pointer; transition: all .15s;
        }
        .preset-btn:hover { border-color: #1361a0; background: #f3f8fc; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        "<div style='background: linear-gradient(135deg, #0d4a7c, #1361a0);"
        "color: white; padding: 26px 28px; border-radius: 14px; margin-bottom: 24px;'>"
        "<h1 style='margin:0 0 6px 0; font-size:24px; letter-spacing:-.2px;'>"
        "Berth Scheduling — Greedy Heuristic vs. Exact MILP</h1>"
        "<p style='margin:0; color:#cfe1f0; font-size:15px; max-width:820px;'>"
        "Vessels arrive at a port and must be assigned to berths. A cheap greedy "
        "rule and an exact mixed-integer program each build a schedule; the goal "
        "is to minimize total weighted tardiness. Watch where the exact solver "
        "wins — and where it can't keep up.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Instance")
        st.number_input("Vessels", min_value=VESSELS_RANGE[0], max_value=VESSELS_RANGE[1],
                        value=9, key="vessels")
        st.number_input("Berths", min_value=BERTHS_RANGE[0], max_value=BERTHS_RANGE[1],
                        value=2, key="berths")
        st.number_input("Seed", value=3, step=1, key="seed")
        st.number_input("MILP time limit (s)", min_value=TIME_LIMIT_RANGE[0],
                        max_value=TIME_LIMIT_RANGE[1], value=10, key="time_limit")
        st.checkbox("Tight due dates (congestion bites)", value=True, key="tight")

        st.markdown("<div style='height:2px; background:#e5e7eb; margin:20px 0;'></div>",
                    unsafe_allow_html=True)
        st.subheader("Try a preset")
        for i, p in enumerate(PRESETS):
            if st.button(p["label"], key=f"preset_{i}", use_container_width=True):
                apply_preset(i)
                st.rerun()

    st.subheader("Run comparison")
    run = st.button("▶ Run comparison", type="primary", use_container_width=False)

    if run:
        with st.spinner(
            f"Solving… the MILP can take up to {st.session_state.time_limit}s to certify."
        ):
            data = solve(
                vessels=int(st.session_state.vessels),
                berths=int(st.session_state.berths),
                seed=int(st.session_state.seed),
                tight=bool(st.session_state.tight),
                time_limit=int(st.session_state.time_limit),
            )
        st.session_state.last_result = data

    if "last_result" not in st.session_state:
        st.info("Configure the instance on the left and click **▶ Run comparison** to see results.")
        st.stop()

    data = st.session_state.last_result
    g = data["greedy"]
    m = data["milp"]
    params = data["params"]
    instance = data["instance"]
    inst_map = {v["id"]: v for v in instance}

    all_finish = [a["finish"] for a in g["assignments"]] + [a["finish"] for a in m["assignments"]]
    all_due = [v["due"] for v in instance]

    def nice_ceil(x):
        def nice_step(raw):
            import math
            pow10 = 10 ** math.floor(math.log10(max(raw, 1)))
            n = raw / pow10
            base = 1 if n <= 1 else 2 if n <= 2 else 5 if n <= 5 else 10
            return base * pow10
        step = nice_step(x / 5)
        return ((int(x) + int(step) - 1) // int(step)) * step if step > 0 else x

    max_time = nice_ceil(max(1, *all_finish, *all_due))

    st.markdown("---")
    st.subheader("Result")
    render_verdict(data["verdict"])

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    render_metrics(g, m)

    st.markdown("---")
    st.subheader("Schedules")
    st.caption(
        f'<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
        f'background:{ONTIME_COLOR};vertical-align:-2px;margin-right:6px;"></span>'
        f'On time &nbsp;&nbsp;'
        f'<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
        f'background:{LATE_COLOR};vertical-align:-2px;margin-right:6px;"></span>'
        f'Tardy (finished after due date) &nbsp;&nbsp;·&nbsp;&nbsp; Hover a bar for details',
        unsafe_allow_html=True,
    )
    col_g, col_m = st.columns(2)
    with col_g:
        render_gantt("Greedy", g["total_weighted_tardiness"],
                     g["assignments"], params["berths"], max_time, inst_map)
    with col_m:
        render_gantt("MILP", m["total_weighted_tardiness"],
                     m["assignments"], params["berths"], max_time, inst_map)

    st.caption("Horizontal axis: time (arbitrary units). Rows are berths.")

    st.markdown("---")
    with st.expander("Problem instance (per-vessel arrival, duration, due, weight)"):
        render_instance(instance)

    st.markdown("---")
    st.caption(
        "Numbers come from the project's real code — `greedy.py` and the CBC-solved "
        "`milp.py` — wrapped by this Streamlit UI. The UI adds no scheduling logic of its own."
    )


if __name__ == "__main__":
    main()
