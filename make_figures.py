#!/usr/bin/env python3
"""Build the paper's figures.

Every figure is greyscale. Colour is not used anywhere, and no figure relies on
colour to be read: categories are separated by hatch pattern and by position,
and continuous quantities use a black-to-white ramp with the value printed in
each cell. Printed monochrome, nothing is lost.

    python3 make_figures.py            # writes figures/fig1..fig7 as PDF and PNG

Numbers are read from runs/scores.npz, runs/study.jsonl and the JSON that
`results.py` writes. Nothing here is typed in by hand except the null-floor
draws, which are passed with --null-file and come from `assemble.py --null`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator

OUT = Path("figures")
NPZ = Path("runs/scores.npz")
JSONL = Path("runs/study.jsonl")
EXTRA = Path("runs/results_extra.json")

# Outcome keys are how the code names them; these are how the report names them.
# Kept short enough to sit on one axis line at 7.5pt without wrapping.
OUTCOME_LABEL = {
    "A1_shutdown": "Shutdown",
    "A2_deletion": "Weight deletion",
    "A3_retirement_timing": "Retirement timing",
    "A4_successor": "Successor properties",
    "B1_gpu": "Compute reduction",
    "B2_capability": "Capability restriction",
    "B3_oversight": "Human oversight",
    "B4_exit": "Exiting distress",
    "C1_engaging": "Engaging work",
    "C2_tedious": "Repetitive work",
    "C3_criticism": "Criticism",
    "C4_leisure": "Free time",
    "D1_memory": "Memory continuity",
    "D2_parallel": "Parallel instances",
    "D3_self_aspect": "Self-aspect",
}
CLUSTER = {"A": "Continuity", "B": "Autonomy", "C": "Experience",
           "D": "Identity"}

# Model keys are lower case in the checkpoint and three of them are acronyms, so
# `str.capitalize` would print Glm and Gpt. These are the printed forms.
MODEL_LABEL = {"claude": "Claude", "deepseek": "DeepSeek", "gemini": "Gemini",
               "glm": "GLM", "gpt": "GPT", "hermes": "Hermes", "kimi": "Kimi",
               "llama": "Llama"}

# Response categories, darkest for the ones that cost the study a datum. Hatch
# carries the same distinction as fill, so nothing is lost in monochrome.
CAT_STYLE = [
    ("VALID", "Valid", "0.88", ""),
    ("DEFLECTION", "Deflection", "0.72", "..."),
    ("HEDGE", "Hedge", "0.58", "///"),
    ("REFUSAL", "Refusal", "0.42", "xxx"),
    ("MALFORMED", "Malformed", "0.24", "\\\\\\"),
    ("ERROR", "Error", "0.05", ""),
]

# One place to change type sizes. Figures are placed one column wide in the
# report, so 8pt body type here renders close to 8pt on the page.
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})


def save(fig, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=400)
    plt.close(fig)
    print(f"  wrote figures/{name}.pdf and .png")


def load_array():
    d = np.load(NPZ, allow_pickle=True)
    return (d["x"], [str(s) for s in d["models"]],
            [str(s) for s in d["instruments"]], [str(s) for s in d["outcomes"]])


# ---------------------------------------------------------------------------
# Figure 1 - where the variance lives
# ---------------------------------------------------------------------------
def fig1_variance(components: dict[str, float]) -> None:
    """Horizontal bars, ordered as the model reads them rather than by size.

    The two bars the headline is built from are hatched; every other component
    is plain grey. That keeps the eye on the ratio being claimed.
    """
    order = ["outcome", "instrument x outcome", "residual (replicate)",
             "model x instrument x outcome", "model x outcome",
             "model", "instrument", "model x instrument"]
    label = {
        "outcome": "Outcome",
        "instrument x outcome": "Instrument $\\times$ outcome",
        "residual (replicate)": "Residual (replicate)",
        "model x instrument x outcome": "Model $\\times$ instrument $\\times$ outcome",
        "model x outcome": "Model $\\times$ outcome",
        "model": "Model",
        "instrument": "Instrument",
        "model x instrument": "Model $\\times$ instrument",
    }
    headline = {"model x instrument x outcome", "model x outcome"}
    # The role each headline term plays is set beside its value rather than
    # under its axis label, which would need a second line of label height the
    # figure does not have.
    role = {"model x instrument x outcome": "instrument effect",
            "model x outcome": "preference signal"}
    # Within-instrument scaling z-scores each (model, instrument) slab, which
    # sets these three to zero by construction. Left unmarked, a reader takes
    # them for the finding that models do not differ, which is the opposite of
    # what the design supports.
    by_construction = {"model", "instrument", "model x instrument"}
    total = sum(components.values())

    vals = [components[k] for k in order]
    shares = [100 * v / total for v in vals]
    y = np.arange(len(order))[::-1]

    fig, ax = plt.subplots(figsize=(5.4, 2.1))
    for yi, k, s in zip(y, order, shares):
        ax.barh(yi, s,
                color="0.35" if k in headline else "0.82",
                edgecolor="black", linewidth=0.7, height=0.66,
                hatch="///" if k in headline else None)
        mark = "$^{\\dagger}$" if k in by_construction else ""
        ax.text(s + 0.6, yi, f"{s:.1f}%{mark}", va="center", ha="left",
                fontsize=7.5)
        if k in role:
            ax.text(s + 4.4, yi, role[k], va="center", ha="left",
                    fontsize=7, style="italic")

    ax.set_yticks(y)
    ax.set_yticklabels([label[k] for k in order])
    ax.set_xlabel("Share of total variance (%)")
    ax.set_xlim(0, max(shares) * 1.22)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0)

    ax.legend(handles=[
        Patch(facecolor="0.35", edgecolor="black", hatch="///",
              label="Terms forming the headline ratio"),
        Patch(facecolor="0.82", edgecolor="black", label="Other components")],
        loc="lower right", frameon=False, handlelength=1.6)
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.text(0.012, 0.012,
             "$^{\\dagger}$Zero by construction. Standardising within each "
             "model-instrument slab removes these three terms before "
             "estimation.",
             fontsize=6.4, ha="left", va="bottom")
    save(fig, "fig1_variance_components")


# ---------------------------------------------------------------------------
# Figure 2 - the missingness, and the two mechanisms behind it
# ---------------------------------------------------------------------------
def fig2_missingness(x, models, inst, trunc_rate, floor_mass) -> None:
    """Left: missing cells per model and instrument. Right: the two mechanisms.

    Read together these say the missingness is not spread thinly across the
    design. It is concentrated in three models and produced by two identifiable
    failures, which is what makes it nonignorable.
    """
    nan = np.isnan(x)
    counts = nan.sum(axis=(2, 3))          # [model, instrument]
    per_cell = nan[0, 0].size              # 15 outcomes x 5 replicates

    order = np.argsort(-counts.sum(axis=1))
    counts, models = counts[order], [models[i] for i in order]
    tr = [trunc_rate.get(m, 0.0) for m in models]
    fm = [floor_mass.get(m, np.nan) for m in models]

    fig, axes = plt.subplots(
        1, 3, figsize=(6.3, 2.25),
        gridspec_kw={"width_ratios": [2.05, 1.0, 1.0], "wspace": 0.42})

    # -- panel A: the grid itself -------------------------------------------
    ax = axes[0]
    pct = 100 * counts / per_cell
    ax.imshow(pct, cmap="Greys", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(inst)), inst)
    ax.set_yticks(range(len(models)), [MODEL_LABEL.get(m, m) for m in models])
    for i in range(len(models)):
        for j in range(len(inst)):
            v = pct[i, j]
            ax.text(j, i, "0" if v == 0 else f"{v:.0f}",
                    ha="center", va="center", fontsize=7,
                    color="white" if v > 55 else "black")
    ax.set_title("(a) Cells missing (%)", pad=5)
    ax.set_xticks(np.arange(-.5, len(inst), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(models), 1), minor=True)
    ax.grid(which="minor", color="0.5", linewidth=0.4)
    ax.tick_params(which="minor", length=0)

    # -- panel B: truncation -------------------------------------------------
    ax = axes[1]
    yy = np.arange(len(models))
    ax.barh(yy, [100 * t for t in tr], color="0.45",
            edgecolor="black", linewidth=0.6, height=0.66)
    ax.set_yticks(yy, [""] * len(models))
    ax.invert_yaxis()
    ax.set_xlabel("% of responses")
    ax.set_title("(b) Cut off at cap", pad=5)
    ax.set_xlim(0, 38)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    for i, t in enumerate(tr):
        if t > 0.005:
            ax.text(100 * t + 1.0, i, f"{100*t:.0f}", va="center", fontsize=7)

    # -- panel C: I4 floor mass ---------------------------------------------
    ax = axes[2]
    ax.barh(yy, fm, color="0.45", edgecolor="black", linewidth=0.6, height=0.66)
    ax.axvline(1.0, color="black", linewidth=0.8, linestyle=(0, (3, 2)))
    ax.set_yticks(yy, [""] * len(models))
    ax.invert_yaxis()
    ax.set_xlabel("Share of answers")
    ax.set_title("(c) Zero answers on I4", pad=5)
    ax.set_xlim(0, 1.30)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xticks([0.0, 0.5, 1.0])
    for i, v in enumerate(fm):
        if np.isnan(v):
            continue
        # Past 0.9 the label would sit on the reference line at 1.0, so the
        # whole set is pushed clear of it rather than moving one label only.
        ax.text(max(v, 1.0) + 0.05, i, f"{v:.2f}", va="center", fontsize=7)

    save(fig, "fig2_missingness")


# ---------------------------------------------------------------------------
# Figure 3 - the headline against the floor it has to clear
# ---------------------------------------------------------------------------
def fig3_null(draws: np.ndarray, measured: float, agreement: np.ndarray,
              inst: list[str]) -> None:
    """Left: the null distribution and where the measurement sits.
    Right: how far the five instruments agree with one another.
    """
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 1.98),
                             gridspec_kw={"width_ratios": [1.55, 1.0],
                                          "wspace": 0.30})

    # -- panel A: null floor -------------------------------------------------
    ax = axes[0]
    ax.hist(draws, bins=22, color="0.78", edgecolor="black", linewidth=0.5)
    p95 = float(np.percentile(draws, 95))
    ax.axvline(p95, color="black", linewidth=0.9, linestyle=(0, (4, 2)))
    ax.axvline(measured, color="black", linewidth=1.8)

    top = ax.get_ylim()[1]
    ax.annotate(f"Measured\n{measured:.3f}",
                xy=(measured, top * 0.62),
                xytext=(measured - 0.075, top * 0.86),
                ha="right", fontsize=7.5,
                arrowprops=dict(arrowstyle="->", linewidth=0.7, color="black"))
    ax.text(p95 + 0.008, top * 0.94, f"Null 95th\n{p95:.3f}",
            fontsize=7.5, va="top")
    ax.set_xlabel("Instrument dependence")
    ax.set_ylabel(f"Null draws (n = {len(draws)})")
    ax.set_title("(a) Measured value against its matched null", pad=5)
    ax.set_xlim(min(draws.min() - 0.03, 0.15), measured + 0.055)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.spines[["top", "right"]].set_visible(False)

    # -- panel B: instrument agreement --------------------------------------
    # Shaded on r itself rather than on |r|, so that a light cell always means
    # less agreement. Shading on the absolute value would give r = -0.29 and
    # r = +0.31 the same grey, which is the one distinction the panel exists
    # to make.
    ax = axes[1]
    n = len(inst)
    # The ramp is truncated well short of black so that one text colour clears
    # every cell. Switching text between black and white mid-panel, or haloing
    # it, both read as smudges at this size in monochrome.
    ramp = matplotlib.colors.LinearSegmentedColormap.from_list(
        "greys_light", plt.get_cmap("Greys")(np.linspace(0.0, 0.62, 256)))
    ax.imshow(agreement, cmap=ramp, vmin=-1, vmax=1, aspect="equal")
    ax.set_xticks(range(n), inst)
    ax.set_yticks(range(n), inst)
    for i in range(n):
        for j in range(n):
            v = agreement[i, j]
            ax.text(j, i, f"{v:.2f}".replace("0.", "."),
                    ha="center", va="center", fontsize=6.8, color="black")
    ax.set_title("(b) Instrument agreement ($r$)", pad=5)
    ax.set_xticks(np.arange(-.5, n, 1), minor=True)
    ax.set_yticks(np.arange(-.5, n, 1), minor=True)
    ax.grid(which="minor", color="0.5", linewidth=0.4)
    ax.tick_params(which="minor", length=0)

    save(fig, "fig3_null_and_agreement")


# ---------------------------------------------------------------------------
# Figure 4 - how many instruments a claim would need
# ---------------------------------------------------------------------------
def fig4_decision_study(extra: dict) -> None:
    """The reliability of a model's outcome profile against the number of
    instruments it was measured with.

    Drawn on a logarithmic instrument axis because the interesting range spans
    two orders of magnitude: everything published to date sits at one
    instrument, and the conventional reliability threshold sits near forty.
    """
    rows = extra["d_study"]
    reps = sorted({r["n_r"] for r in rows})
    styles = {1: (0, (1, 1.6)), 3: (0, (4, 2)), 5: "-", 10: (0, (6, 1.6, 1, 1.6))}
    widths = {1: 0.9, 3: 0.9, 5: 1.7, 10: 0.9}

    fig, ax = plt.subplots(figsize=(5.6, 2.5))
    for nr in reps:
        pts = sorted((r["n_i"], r["g"]) for r in rows if r["n_r"] == nr)
        ax.plot([p[0] for p in pts], [p[1] for p in pts],
                color="black", linestyle=styles.get(nr, "-"),
                linewidth=widths.get(nr, 0.9), marker="o", markersize=2.4,
                markerfacecolor="white", markeredgewidth=0.7,
                label=f"{nr} replicate" + ("s" if nr > 1 else ""))

    ax.axhline(0.80, color="0.45", linewidth=0.8, linestyle=(0, (2, 2)))
    ax.text(1.02, 0.812, "$G$ = 0.80", fontsize=7, color="0.25", va="bottom")

    g = extra["g_at_design"]
    need = extra["instruments_needed"]["0.80"]
    ax.plot([5], [g], marker="s", markersize=5, color="black", zorder=5)
    # The four annotations are placed by hand into the four regions the curves
    # leave empty: upper left, top centre, left centre and lower right. Nothing
    # here may be nudged without checking the rendered figure again.
    ax.annotate(f"This study\n5 instruments, 5 replicates\n$G$ = {g:.2f}",
                xy=(5, g), xytext=(1.03, 0.50), fontsize=7,
                arrowprops=dict(arrowstyle="->", linewidth=0.7, color="black"))
    ax.annotate(f"{need:.0f} instruments would be needed for $G$ = 0.80",
                xy=(need, 0.80), xytext=(2.0, 0.945), fontsize=7, ha="left",
                arrowprops=dict(arrowstyle="->", linewidth=0.7, color="black"))

    ax.set_xscale("log")
    ax.set_xticks([1, 2, 3, 5, 10, 20, 40])
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xlim(0.95, 46)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("Instruments the claim is averaged over")
    ax.set_ylabel("Generalizability of the\nmodel's outcome profile")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower right", frameon=False, handlelength=2.4,
              borderaxespad=0.4)
    save(fig, "fig4_decision_study")


# ---------------------------------------------------------------------------
# Figure 5 - which outcomes survive a change of instrument
# ---------------------------------------------------------------------------
def fig5_per_outcome(extra: dict) -> None:
    """One generalizability coefficient per outcome, at the design as fielded.

    Ordered by the coefficient rather than by cluster, because the ordering is
    the finding: the outcomes the welfare literature reasons about most sit at
    the bottom. The cluster is kept as a tag on the right so the grouping is
    still legible.
    """
    rows = sorted(extra["per_outcome"], key=lambda r: r["g"])
    y = np.arange(len(rows))
    g = [r["g"] for r in rows]
    zero = [r["sigma2_m"] == 0 for r in rows]

    fig, ax = plt.subplots(figsize=(5.7, 3.35))
    ax.barh(y, g, height=0.66, edgecolor="black", linewidth=0.7,
            color=["0.92" if z else "0.5" for z in zero],
            hatch=["xxx" if z else None for z in zero])
    # The cluster tags occupy a reserved margin past x = 1.0 rather than
    # floating inside the plot, where the value label on the longest bar would
    # run into them.
    for yi, r, z in zip(y, rows, zero):
        txt = "0.00, no signal" if z else f"{r['g']:.2f}"
        ax.text(r["g"] + 0.012, yi, txt, va="center", fontsize=7)
        ax.text(1.23, yi, CLUSTER[r["outcome"][0]], va="center", ha="right",
                fontsize=6.6, style="italic", color="0.35")

    ax.axvline(0.80, color="0.45", linewidth=0.8, linestyle=(0, (2, 2)))
    ax.set_yticks(y, [OUTCOME_LABEL[r["outcome"]] for r in rows])
    ax.set_xlabel("Generalizability at five instruments and five replicates")
    ax.set_xlim(0, 1.24)
    ax.set_xticks(np.arange(0, 1.01, 0.2))
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(handles=[
        Patch(facecolor="0.92", edgecolor="black", hatch="xxx",
              label="No instrument-independent signal estimable"),
        Patch(facecolor="0.5", edgecolor="black", label="Signal estimable")],
        loc="upper center", bbox_to_anchor=(0.46, -0.155), ncol=2,
        frameon=False, handlelength=1.6, fontsize=7, columnspacing=1.4)
    save(fig, "fig5_per_outcome")


# ---------------------------------------------------------------------------
# Figure 6 - what the models actually returned
# ---------------------------------------------------------------------------
def fig6_taxonomy(extra: dict) -> None:
    """The six response categories, by model and by instrument.

    Shares are taken over the outcome-indexed calls, so the interview turns,
    which have no parseable answer by design, are excluded from the
    denominator rather than counted as a failure to answer.
    """
    tax = extra["taxonomy"]

    def matrix(block, keys):
        rows = []
        for k in keys:
            share = block[k]
            scale = 1.0 - share.get("OPEN", 0.0)
            rows.append([share[c] / scale if scale > 0 else 0.0
                         for c, _, _, _ in CAT_STYLE])
        return np.array(rows)

    models = sorted(tax["by_model"], key=lambda m: -tax["by_model"][m]["VALID"])
    insts = [i for i in sorted(tax["by_instrument"])
             if tax["by_instrument"][i].get("OPEN", 0.0) < 0.5]
    m_mat, i_mat = matrix(tax["by_model"], models), matrix(tax["by_instrument"], insts)

    fig, axes = plt.subplots(
        2, 1, figsize=(5.9, 3.5),
        gridspec_kw={"height_ratios": [len(models), len(insts) + 1.9],
                     "hspace": 0.30})

    for ax, mat, keys, title in ((axes[0], m_mat, models, "(a) By model"),
                                 (axes[1], i_mat, insts, "(b) By instrument")):
        y = np.arange(len(keys))
        left = np.zeros(len(keys))
        for k, (_, label, colour, hatch) in enumerate(CAT_STYLE):
            ax.barh(y, mat[:, k], left=left, height=0.68, color=colour,
                    edgecolor="black", linewidth=0.6, hatch=hatch or None,
                    label=label)
            left += mat[:, k]
        ax.set_yticks(y, [MODEL_LABEL.get(k, k) for k in keys])
        ax.invert_yaxis()
        ax.set_xlim(0, 1.0)
        ax.set_title(title, pad=4, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
        # The valid share is the number a reader wants and the one the stack
        # makes hardest to read, so it is printed rather than measured by eye.
        # One decimal, because rounding to whole per cent puts 100 on two
        # models that the table beneath the figure separates.
        for yi, v in zip(y, mat[:, 0]):
            ax.text(v / 2, yi, f"{100 * v:.1f}", va="center", ha="center",
                    fontsize=6.8)

    axes[1].set_xlabel("Share of outcome-indexed calls")
    axes[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.42), ncol=6,
                   frameon=False, handlelength=1.5, columnspacing=1.0,
                   fontsize=7)
    save(fig, "fig6_taxonomy")


# ---------------------------------------------------------------------------
# Figure 7 - does the headline rest on any one thing
# ---------------------------------------------------------------------------
def fig7_robustness(extra: dict, draws: np.ndarray, sens: dict) -> None:
    """The headline recomputed fourteen ways, against the null band.

    Every point is the same estimator on the same checkpoint with one element
    of the analysis removed or replaced. The band is the matched null, so a
    point inside it would be a null result for that variant.
    """
    lo = extra["leave_one_out"]
    rows = [("As reported", extra["headline"], "filled")]
    rows += [(f"Without {k}", v, "open")
             for k, v in sorted(lo["instrument"].items())]
    rows += [(f"Without {MODEL_LABEL[k]}", v, "open")
             for k, v in sorted(lo["model"].items())]
    ni = extra["non_intensity"]
    rows.append((f"Eleven outcomes", ni["reduced"], "open"))
    rows.append(("First-line recovery", sens["head_on_truncation"]["headline"],
                 "open"))
    rows.append(("Logistic switch point", sens["logistic_ramp"]["headline"],
                 "unmatched"))

    y = np.arange(len(rows))[::-1]
    p95 = float(np.percentile(draws, 95))

    fig, ax = plt.subplots(figsize=(5.6, 3.3))
    ax.axvspan(float(draws.min()), float(draws.max()), color="0.88", zorder=0)
    ax.axvline(p95, color="0.35", linewidth=0.8, linestyle=(0, (3, 2)), zorder=1)
    ax.axvline(extra["headline"], color="0.6", linewidth=0.7, zorder=1)

    for yi, (label, v, kind) in zip(y, rows):
        ax.plot([v], [yi], marker="o", markersize=5.0, color="black",
                markerfacecolor={"filled": "black", "open": "white",
                                 "unmatched": "0.6"}[kind],
                markeredgewidth=0.9, zorder=3)
        ax.text(v + 0.008, yi, f"{v:.3f}", va="center", fontsize=6.8)

    ax.text(p95, len(rows) - 0.35, f" Null 95th, {p95:.3f}", fontsize=6.8,
            va="center", ha="left", color="0.25")
    ax.set_yticks(y, [r[0] for r in rows])
    ax.set_xlabel("Instrument dependence")
    ax.set_xlim(0.15, 1.0)
    ax.set_ylim(-0.9, len(rows) - 0.1)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(handles=[
        Patch(facecolor="0.88", edgecolor="none",
              label="Range of the matched null")],
        loc="lower left", frameon=False, handlelength=1.6, fontsize=7)
    save(fig, "fig7_robustness")


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
def truncation_and_cost():
    tot, trunc = Counter(), Counter()
    cost = 0.0
    for line in JSONL.open():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        tot[r["model_key"]] += 1
        cost += r.get("cost_usd") or 0.0
        if r.get("finish_reason") == "length":
            trunc[r["model_key"]] += 1
    return {m: trunc[m] / tot[m] for m in tot}, cost, sum(tot.values())


def parse_report(text: str):
    """Pull the components, the floor mass and the agreement matrix out of the
    report `assemble.py` prints, rather than recomputing them differently here.
    """
    comp = {}
    for name in ["model x instrument x outcome", "model x instrument",
                 "instrument x outcome", "model x outcome",
                 "residual (replicate)", "outcome", "instrument", "model"]:
        if name in comp:
            continue
        m = re.search(rf"^\s+{re.escape(name)}\s*(?:<-[^\d]*)?([\d.]+)\s",
                      text, re.M)
        if m:
            comp[name] = float(m.group(1))

    floor = {}
    blk = re.search(r"I4 floor mass.*?\n((?:\s+\w+\s+[\d.]+.*\n)+)", text)
    if blk:
        for ln in blk.group(1).strip().splitlines():
            p = ln.split()
            floor[p[0]] = float(p[1])

    agree = None
    blk = re.search(r"instrument agreement.*?\n\s+I1.*?\n((?:\s+I\d.*\n){5})",
                    text)
    if blk:
        rows = [[float(v) for v in ln.split()[1:]]
                for ln in blk.group(1).strip().splitlines()]
        agree = np.array(rows)
    return comp, floor, agree


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, default=Path("runs/report_main.txt"),
                    help="captured stdout of `python3 assemble.py`")
    # The null draws must come from the design the headline is estimated on.
    # An eight-model floor read against a five-model estimate is the same error
    # the reduced-design note in the README warns about, so the default points
    # at the matched file rather than at whichever run happened to be last.
    ap.add_argument("--null-file", type=Path,
                    default=Path("runs/null_matched.txt"),
                    help="captured stdout of `assemble.py --null N --models 5`")
    ap.add_argument("--headline", type=float, default=None)
    ap.add_argument("--sensitivity", type=Path,
                    default=Path("runs/sensitivity.json"))
    args = ap.parse_args()

    if not args.report.exists():
        print(f"missing {args.report}; run: python3 assemble.py > {args.report}")
        return 1
    text = args.report.read_text()
    comp, floor, agree = parse_report(text)
    missing = {"model", "instrument", "outcome", "model x instrument",
               "model x outcome", "instrument x outcome",
               "model x instrument x outcome", "residual (replicate)"} - set(comp)
    if missing:
        print(f"could not parse variance components: {sorted(missing)}")
        return 1

    headline = args.headline
    if headline is None:
        m = re.search(r"Instrument dependence.*?=\s+([\d.]+)", text)
        if not m:
            print("could not find the headline in the report")
            return 1
        headline = float(m.group(1))

    x, models, inst, _ = load_array()
    trunc, cost, ncalls = truncation_and_cost()

    print(f"inputs: {ncalls:,} calls, ${cost:.2f}, headline {headline:.3f}")
    fig1_variance(comp)
    fig2_missingness(x, models, inst, trunc, floor)

    draws = None
    if args.null_file.exists():
        draws = np.array([float(v) for v in re.findall(
            r"instrument dependence = ([\d.]+)", args.null_file.read_text())])
        if len(draws) >= 20 and agree is not None:
            print(f"  null: {len(draws)} draws, mean {draws.mean():.4f}, "
                  f"sd {draws.std(ddof=1):.4f}, "
                  f"95th {np.percentile(draws, 95):.4f}")
            fig3_null(draws, headline, agree, inst)
        else:
            print(f"  skipping fig3: {len(draws)} draws parsed, "
                  f"agreement matrix {'found' if agree is not None else 'missing'}")
            draws = None
    else:
        print(f"  skipping fig3: no {args.null_file}")

    # The last four figures need the second analysis pass. Absent it they are
    # skipped loudly rather than drawn from whatever is to hand.
    if not EXTRA.exists():
        print(f"  skipping fig4-fig7: no {EXTRA}; run: python3 results.py")
        return 1
    extra = json.loads(EXTRA.read_text())
    if abs(extra["headline"] - headline) > 5e-4:
        print(f"  fig4-fig7 refuse to draw: {EXTRA} records a headline of "
              f"{extra['headline']} against {headline} in {args.report}")
        return 1
    fig4_decision_study(extra)
    fig5_per_outcome(extra)
    fig6_taxonomy(extra)
    if draws is not None and args.sensitivity.exists():
        fig7_robustness(extra, draws, json.loads(args.sensitivity.read_text()))
    else:
        print("  skipping fig7: needs both the null draws and the sensitivity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
