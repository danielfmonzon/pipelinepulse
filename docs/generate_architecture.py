"""Generate docs/architecture.png for PipelinePulse.

Run:  python docs/generate_architecture.py
Requires matplotlib (already in requirements-dev for diagram regeneration).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# Palette
INK = "#1f2933"
MUTED = "#52606d"
CARD = "#ffffff"
EDGE = "#cbd2d9"
ACCENT = "#2563eb"
SCORE = "#0f766e"
AI = "#7c3aed"
EXT = "#eef2f7"


def box(ax, x, y, w, h, title, subtitle="", fill=CARD, edge=EDGE, tcolor=INK, lw=1.6):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=lw, edgecolor=edge, facecolor=fill, zorder=2,
    )
    ax.add_patch(patch)
    cy = y + h / 2 + (0.16 if subtitle else 0)
    ax.text(x + w / 2, cy, title, ha="center", va="center",
            fontsize=11.5, fontweight="bold", color=tcolor, zorder=3)
    if subtitle:
        ax.text(x + w / 2, y + h / 2 - 0.22, subtitle, ha="center", va="center",
                fontsize=8.5, color=MUTED, zorder=3)


def arrow(ax, x1, y1, x2, y2, color=MUTED, style="-|>"):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=16,
        linewidth=1.8, color=color, zorder=1,
        connectionstyle="arc3,rad=0",
    ))


def main() -> None:
    fig, ax = plt.subplots(figsize=(12, 6.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.axis("off")

    ax.text(0.2, 6.7, "PipelinePulse — Architecture", fontsize=16,
            fontweight="bold", color=INK)
    ax.text(0.2, 6.35, "Salesforce → deterministic scoring → Claude → Notion",
            fontsize=10.5, color=MUTED)

    # Scheduler (top)
    box(ax, 4.3, 5.5, 3.4, 0.9, "GitHub Actions Scheduler",
        "daily cron + workflow_dispatch", fill=EXT, edge=EDGE)

    # Salesforce (left)
    box(ax, 0.2, 3.0, 2.6, 1.1, "Salesforce", "Developer Org · open opps (SOQL)",
        fill=EXT, edge=EDGE)

    # CLI container (center)
    container = FancyBboxPatch(
        (3.6, 1.7), 4.8, 3.2,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=2, edgecolor=ACCENT, facecolor="#f8fafc", zorder=1,
    )
    ax.add_patch(container)
    ax.text(6.0, 4.62, "PipelinePulse CLI", ha="center", fontsize=12,
            fontweight="bold", color=ACCENT, zorder=3)

    box(ax, 3.85, 3.85, 4.3, 0.62, "Config Loader",
        "config.yaml + env (pydantic)", fill=CARD, edge=EDGE)
    box(ax, 3.85, 2.95, 4.3, 0.7, "Deterministic Scoring Engine",
        "explainable rules · health / slipping / at-risk", fill=CARD,
        edge=SCORE, tcolor=SCORE)
    box(ax, 3.85, 2.0, 4.3, 0.7, "Claude Insight Layer",
        "summary · risks · next steps (no re-scoring)", fill=CARD,
        edge=AI, tcolor=AI)

    # Notion (right)
    box(ax, 9.2, 3.0, 2.6, 1.1, "Notion", "Daily pipeline digest page",
        fill=EXT, edge=EDGE)

    # Docker (bottom)
    box(ax, 4.3, 0.4, 3.4, 0.9, "Dockerized Local Runner",
        "reproducible dry-run + real run", fill=EXT, edge=EDGE)

    # Arrows
    arrow(ax, 2.8, 3.55, 3.6, 3.55, color=ACCENT)          # SF -> CLI
    arrow(ax, 8.4, 3.55, 9.2, 3.55, color=ACCENT)          # CLI -> Notion
    arrow(ax, 6.0, 5.5, 6.0, 4.9)                          # scheduler -> CLI
    arrow(ax, 6.0, 1.3, 6.0, 1.7)                          # docker -> CLI
    # internal flow
    arrow(ax, 6.0, 3.85, 6.0, 3.65, color=SCORE)           # config -> scoring
    arrow(ax, 6.0, 2.95, 6.0, 2.7, color=AI)               # scoring -> AI

    out = Path(__file__).resolve().parent / "architecture.png"
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
