#!/usr/bin/env python3
"""Charts for the audit report (optional; requires matplotlib)."""
import argparse
import json
import os
import sys

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib not available; charts skipped")
    sys.exit(0)

COLORS = {"codex": "#10a37f", "opencode": "#e879f9", "omp": "#f59e0b", "zcode": "#3b82f6",
          "claude": "#d97757"}


def color(t):
    return COLORS.get(t, "#64748b")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="agentic-audit")
    args = ap.parse_args()

    data = os.path.join(args.out, "data")
    stats_path = os.path.join(data, "stats.json")
    if not os.path.isfile(stats_path):
        sys.exit("stats.json not found; run compute_stats.py first")
    stats = json.load(open(stats_path, encoding="utf-8"))
    up = json.load(open(os.path.join(data, "user_patterns.json"), encoding="utf-8"))
    plt.rcParams["font.family"] = "DejaVu Sans"
    tools = list(stats["overview"].keys())

    # sessions per day per tool
    tl = stats["timeline"]
    days = sorted(tl)
    fig, ax = plt.subplots(figsize=(11, 4))
    bottom = [0] * len(days)
    for t in tools:
        vals = [tl[d].get(t, 0) for d in days]
        ax.bar(range(len(days)), vals, bottom=bottom, label=t, color=color(t))
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_xticks(range(len(days)))
    ax.set_xticklabels([d[5:] for d in days], rotation=45, fontsize=8)
    ax.set_ylabel("sessions started")
    ax.set_title("AI agent sessions per day")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "chart_sessions_by_day.png"), dpi=130)

    # tool call profiles
    fig, axes = plt.subplots(1, len(tools), figsize=(3.2 * len(tools), 3.6))
    if len(tools) == 1:
        axes = [axes]
    for ax, t in zip(axes, tools):
        items = list(stats["tool_breakdown"].get(t, {}).items())[:6]
        names = [i[0] for i in items][::-1]
        vals = [i[1] for i in items][::-1]
        ax.barh(names, vals, color=color(t))
        ax.set_title(f"{t}: {sum(stats['tool_breakdown'].get(t, {}).values())} calls", fontsize=10)
        ax.tick_params(labelsize=8)
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "chart_tool_calls.png"), dpi=130)

    # user message classification
    cls = up["classification"]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    names = list(cls.keys())[::-1]
    vals = [cls[n] for n in names]
    ax.barh(names, vals, color="#6366f1")
    ax.set_title(f"User messages by class ({up['real_user_msgs_main']} real, main sessions)", fontsize=10)
    ax.tick_params(labelsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "chart_user_msgs.png"), dpi=130)
    print("charts written to", args.out)


if __name__ == "__main__":
    main()
