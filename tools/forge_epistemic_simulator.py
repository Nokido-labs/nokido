"""Epistemic dynamics simulator — visualise trajectoire confidence_score
d'un claim dans le temps sous l'effet de l'equation:

    epistemic_weight(t) = alpha*trust_weight + beta*recency_decay(t)
                        + gamma*citation_norm + delta*peer_review_bonus
                        + epsilon*refutation_penalty(t)

Usage:
    LAFORGE_PYTHON tools/forge_epistemic_simulator.py           # show plot
    LAFORGE_PYTHON tools/forge_epistemic_simulator.py --tune    # interactive sliders
    LAFORGE_PYTHON tools/forge_epistemic_simulator.py --json out.json  # data export

Cas de reference (Gemini Web 2026-05-28) :
    Claim A: preprint 2020 "stegano LSB indetectable", peu cite, non peer-reviewed.
    Claim B: peer-reviewed 2023 "deep stegano-analyse 90% detection", cite, refute A.
    Domaine half-life 1.5 ans (steganographie = velocite haute).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

# Default weights (calibrer via tools/forge_epistemic_calibrate.py)
DEFAULT_ALPHA = 0.30  # trust_weight (source authority)
DEFAULT_BETA = 0.25  # recency_decay
DEFAULT_GAMMA = 0.15  # citation_norm
DEFAULT_DELTA = 0.20  # peer_review_bonus
DEFAULT_EPSILON = 0.10  # refutation_penalty


@dataclass
class EpistemicChunk:
    id: str
    publication_year: float  # e.g. 2020.5 = mid-2020
    trust_weight: float  # 0-1 (peer-review source authority)
    citation_count: int
    peer_reviewed: bool
    domain_half_life_years: float = 1.5
    # refutation events: list of (year, refuter_id)
    refutations: list = field(default_factory=list)


def epistemic_weight(
    chunk: EpistemicChunk,
    t_now: float,
    alpha: float = DEFAULT_ALPHA,
    beta: float = DEFAULT_BETA,
    gamma: float = DEFAULT_GAMMA,
    delta: float = DEFAULT_DELTA,
    epsilon: float = DEFAULT_EPSILON,
) -> float:
    """Calcule epistemic_weight au temps t_now (annees decimales)."""
    if t_now < chunk.publication_year:
        return 0.0  # claim n'existe pas encore

    # Recency: half-life exponentielle
    age = t_now - chunk.publication_year
    recency_decay = math.exp(-age * math.log(2) / chunk.domain_half_life_years)

    # Citations: log normalize, cap ~e^6 (citations elevees plafonnees)
    citation_norm = math.log1p(chunk.citation_count) / 6.0
    citation_norm = min(1.0, citation_norm)

    # Peer review: bonus binaire
    peer_review_bonus = 1.0 if chunk.peer_reviewed else 0.0

    # Refutation: penalty cumulative quand refutations sont publiees AVANT t_now
    n_active_refutations = sum(1 for (yr, _) in chunk.refutations if yr <= t_now)
    refutation_penalty = 1.0 / (1.0 + 0.5 * n_active_refutations)

    return (
        alpha * chunk.trust_weight
        + beta * recency_decay
        + gamma * citation_norm
        + delta * peer_review_bonus
        + epsilon * refutation_penalty
    )


def simulate_trajectory(
    chunk: EpistemicChunk,
    t_start: float,
    t_end: float,
    n_points: int = 100,
    weight_fn: Callable | None = None,
    **kwargs,
) -> list[tuple[float, float]]:
    """Retourne [(t, epistemic_weight)] sur [t_start, t_end]."""
    fn = weight_fn or epistemic_weight
    if n_points < 2:
        return []
    step = (t_end - t_start) / (n_points - 1)
    return [(t_start + i * step, fn(chunk, t_start + i * step, **kwargs)) for i in range(n_points)]


# --- Scenario reference Gemini Web ---


def scenario_stego() -> tuple[EpistemicChunk, EpistemicChunk]:
    """Cas pathologique : preprint 2020 indetectable, refute par peer 2023."""
    a = EpistemicChunk(
        id="preprint_2020_undetectable",
        publication_year=2020.0,
        trust_weight=0.5,  # preprint, faible authority
        citation_count=5,
        peer_reviewed=False,
        domain_half_life_years=1.5,
        refutations=[(2023.0, "peer_2023_detectable")],  # refute en 2023
    )
    b = EpistemicChunk(
        id="peer_2023_detectable",
        publication_year=2023.0,
        trust_weight=0.95,  # peer-reviewed top-tier
        citation_count=18,
        peer_reviewed=True,
        domain_half_life_years=1.5,
        refutations=[],
    )
    return a, b


# --- Visualisation ---


def plot_static(traj_a, traj_b, save: str | None = None):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib absent. pip install matplotlib", file=sys.stderr)
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        [t for t, _ in traj_a],
        [w for _, w in traj_a],
        label="Claim A: preprint 2020 'undetectable'",
        color="#c0392b",
        lw=2,
    )
    ax.plot(
        [t for t, _ in traj_b],
        [w for _, w in traj_b],
        label="Claim B: peer 2023 'detectable'",
        color="#27ae60",
        lw=2,
    )
    ax.axvline(
        x=2023.0,
        ls="--",
        color="gray",
        alpha=0.7,
        label="B published (A refutation_penalty kicks in)",
    )
    ax.set_xlabel("Time (years)")
    ax.set_ylabel("Epistemic weight")
    ax.set_title("Epistemic dynamics — steganography velocity domain (half-life 1.5y)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    ax.set_ylim(0, 1.0)
    plt.tight_layout()
    if save:
        plt.savefig(save, dpi=120)
        print(f"Saved {save}")
    else:
        plt.show()


def interactive_tune():
    """Sliders matplotlib pour tuner alpha/beta/gamma/delta/epsilon en live."""
    try:
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Slider
    except ImportError:
        print("matplotlib absent. pip install matplotlib", file=sys.stderr)
        return

    a, b = scenario_stego()
    times = [(2020.0 + 6.0 * i / 99) for i in range(100)]

    fig, ax = plt.subplots(figsize=(11, 6))
    plt.subplots_adjust(left=0.08, bottom=0.40, right=0.97, top=0.93)
    (line_a,) = ax.plot(times, [0] * 100, label="Claim A (preprint 2020)", color="#c0392b", lw=2)
    (line_b,) = ax.plot(times, [0] * 100, label="Claim B (peer 2023)", color="#27ae60", lw=2)
    ax.axvline(x=2023.0, ls="--", color="gray", alpha=0.7)
    ax.set_xlabel("Time (years)")
    ax.set_ylabel("Epistemic weight")
    ax.set_title("Tune coefficients live")
    ax.set_ylim(0, 1.0)
    ax.legend()
    ax.grid(alpha=0.3)

    # Sliders
    ax_alpha = plt.axes([0.10, 0.28, 0.78, 0.025])
    ax_beta = plt.axes([0.10, 0.23, 0.78, 0.025])
    ax_gamma = plt.axes([0.10, 0.18, 0.78, 0.025])
    ax_delta = plt.axes([0.10, 0.13, 0.78, 0.025])
    ax_epsilon = plt.axes([0.10, 0.08, 0.78, 0.025])
    ax_halflife = plt.axes([0.10, 0.03, 0.78, 0.025])

    s_alpha = Slider(ax_alpha, "alpha (trust)", 0.0, 1.0, valinit=DEFAULT_ALPHA)
    s_beta = Slider(ax_beta, "beta (recency)", 0.0, 1.0, valinit=DEFAULT_BETA)
    s_gamma = Slider(ax_gamma, "gamma (cite)", 0.0, 1.0, valinit=DEFAULT_GAMMA)
    s_delta = Slider(ax_delta, "delta (peer)", 0.0, 1.0, valinit=DEFAULT_DELTA)
    s_epsilon = Slider(ax_epsilon, "epsilon (refut)", 0.0, 1.0, valinit=DEFAULT_EPSILON)
    s_halflife = Slider(ax_halflife, "domain half-life (y)", 0.5, 10.0, valinit=1.5)

    def update(_):
        a.domain_half_life_years = s_halflife.val
        b.domain_half_life_years = s_halflife.val
        kw = dict(
            alpha=s_alpha.val,
            beta=s_beta.val,
            gamma=s_gamma.val,
            delta=s_delta.val,
            epsilon=s_epsilon.val,
        )
        line_a.set_ydata([epistemic_weight(a, t, **kw) for t in times])
        line_b.set_ydata([epistemic_weight(b, t, **kw) for t in times])
        fig.canvas.draw_idle()

    for s in (s_alpha, s_beta, s_gamma, s_delta, s_epsilon, s_halflife):
        s.on_changed(update)
    update(None)
    plt.show()


# --- Export JSON pour ingest dashboard web ---


def export_json(out: str):
    a, b = scenario_stego()
    times = [(2020.0 + 6.0 * i / 99) for i in range(100)]
    data = {
        "claim_a": {
            "id": a.id,
            "trajectory": [{"t": t, "w": epistemic_weight(a, t)} for t in times],
        },
        "claim_b": {
            "id": b.id,
            "trajectory": [{"t": t, "w": epistemic_weight(b, t)} for t in times],
        },
        "coefficients": {
            "alpha": DEFAULT_ALPHA,
            "beta": DEFAULT_BETA,
            "gamma": DEFAULT_GAMMA,
            "delta": DEFAULT_DELTA,
            "epsilon": DEFAULT_EPSILON,
        },
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true", help="Interactive sliders")
    ap.add_argument("--json", metavar="FILE", help="Export trajectories JSON")
    ap.add_argument("--save", metavar="PNG", help="Save plot to PNG")
    args = ap.parse_args()

    if args.tune:
        interactive_tune()
    elif args.json:
        export_json(args.json)
    else:
        a, b = scenario_stego()
        times = [(2020.0 + 6.0 * i / 99) for i in range(100)]
        traj_a = simulate_trajectory(a, 2020.0, 2026.0)
        traj_b = simulate_trajectory(b, 2020.0, 2026.0)
        plot_static(traj_a, traj_b, save=args.save)


if __name__ == "__main__":
    main()
