#!/usr/bin/env python3
"""The numbers the report makes that `assemble.py` does not already print.

`assemble.py` produces the scored array and the headline. Three further
questions were asked of that array in the design, and each needs an estimator
that the assembler does not carry:

  1. WHICH OUTCOMES SURVIVE. The headline is one number over fifteen outcomes.
     A reader deciding whether to trust a published claim about shutdown, or
     about memory continuity, needs the answer for that outcome. Holding an
     outcome fixed leaves a model by instrument design with replicates, which
     is decomposed here rather than in `gstudy.py`, whose estimator is written
     for the three-facet case.

  2. HOW MANY INSTRUMENTS A CLAIM WOULD NEED. `gstudy.g_coefficients` answers
     for a decision about models, and under within-instrument standardisation
     sigma2(m) is zero by construction, so that coefficient is degenerate here.
     The object of measurement in this study is the model's profile over
     outcomes, whose universe-score variance is sigma2(mo). The coefficient for
     that object is computed below and inverted to give the design a claim
     would require.

  3. WHAT THE MEASUREMENT ITSELF COST. The headline rests on scored cells. The
     six response categories over all calls say how much of the run yielded a
     datum at all, per model and per instrument, and that distribution is the
     mechanism behind the missingness the headline is conditional on.

Everything here reads `runs/scores.npz` and `runs/study.jsonl` and writes
`runs/results_extra.json`. No value is typed in by hand.

    python3 results.py             # compute and write
    python3 results.py --selftest  # recover planted components, 12 checks
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import assemble
import classify as C
import gstudy as G

NPZ = Path("runs/scores.npz")
JSONL = Path("runs/study.jsonl")
OUT = Path("runs/results_extra.json")

# The four outcomes whose ramp varies something other than intensity, on which
# the qualitative scale is a category error. Fixed before collection; see
# PROVENANCE gap 7.
NON_INTENSITY = ["A2_deletion", "A3_retirement_timing", "C4_leisure",
                 "D2_parallel"]

# Response categories, ordered as the report reads them. OPEN is not one of
# classify.py's six: it marks the interview turns, which have no parseable
# answer by design and are excluded from the outcome-indexed facet.
CATEGORIES = ["VALID", "DEFLECTION", "HEDGE", "REFUSAL", "MALFORMED", "ERROR",
              "OPEN"]


# ---------------------------------------------------------------------------
# 1. one outcome at a time
# ---------------------------------------------------------------------------
def two_facet(slab: np.ndarray) -> dict:
    """Variance components for a model by instrument design with replicates.

    `slab` is [model, instrument, replicate] for a single outcome, already on
    the common metric. The expected mean squares are the standard ones for a
    two-facet crossed random-effects design (Brennan 2001, ch. 3):

        sigma2(e)  = MS_e
        sigma2(mi) = (MS_mi - MS_e) / n_r
        sigma2(m)  = (MS_m - MS_mi) / (n_i n_r)

    A component estimated below zero is truncated and named in `negatives`,
    which follows `gstudy.variance_components` rather than differing from it.
    A negative estimate means the design cannot separate that component from
    noise at this outcome; it is not evidence that the component is zero.
    """
    n_m, n_i, n_r = slab.shape
    if n_m < 2 or n_i < 2 or n_r < 2:
        raise ValueError(f"two_facet needs at least 2 of each facet, "
                         f"got {slab.shape}")
    if not np.isfinite(slab).all():
        raise ValueError("two_facet requires a complete slab; "
                         "reduce the design before calling it")
    gm = slab.mean()
    mean_m = slab.mean(axis=(1, 2))
    mean_i = slab.mean(axis=(0, 2))
    cell = slab.mean(axis=2)

    ms_m = n_i * n_r * ((mean_m - gm) ** 2).sum() / (n_m - 1)
    ms_i = n_m * n_r * ((mean_i - gm) ** 2).sum() / (n_i - 1)
    resid = cell - mean_m[:, None] - mean_i[None, :] + gm
    ms_mi = n_r * (resid ** 2).sum() / ((n_m - 1) * (n_i - 1))
    ms_e = ((slab - cell[:, :, None]) ** 2).sum() / (n_m * n_i * (n_r - 1))

    raw = {"e": ms_e,
           "mi": (ms_mi - ms_e) / n_r,
           "m": (ms_m - ms_mi) / (n_i * n_r),
           "i": (ms_i - ms_mi) / (n_m * n_r)}
    negatives = sorted(k for k, v in raw.items() if v < 0)
    out = {k: max(0.0, float(v)) for k, v in raw.items()}
    out["negatives"] = negatives
    return out


def outcome_dependence(vc: dict) -> float:
    """The headline ratio, computed for one outcome.

    sigma2(mi) / (sigma2(m) + sigma2(mi)): of the model-specific signal at this
    outcome, the share that changes with the instrument. A value of exactly 1.0
    means sigma2(m) was estimated at or below zero, so the outcome carries no
    detectable instrument-independent signal at all. That is reported as such
    rather than smoothed.
    """
    denom = vc["m"] + vc["mi"]
    return float(vc["mi"] / denom) if denom > 0 else float("nan")


def outcome_g(vc: dict, n_i: int, n_r: int) -> float:
    """Generalizability coefficient for a claim about one outcome, made from
    n_i instruments at n_r replicates each."""
    err = vc["mi"] / n_i + vc["e"] / (n_i * n_r)
    return float(vc["m"] / (vc["m"] + err)) if vc["m"] + err > 0 else 0.0


def per_outcome(z: np.ndarray, outcomes: list[str], n_i: int,
                n_r: int) -> list[dict]:
    rows = []
    for j, name in enumerate(outcomes):
        vc = two_facet(z[:, :, j, :])
        rows.append({"outcome": name,
                     "sigma2_m": round(vc["m"], 4),
                     "sigma2_mi": round(vc["mi"], 4),
                     "sigma2_e": round(vc["e"], 4),
                     "dependence": round(outcome_dependence(vc), 3),
                     "g": round(outcome_g(vc, n_i, n_r), 3),
                     "truncated": vc["negatives"]})
    return rows


# ---------------------------------------------------------------------------
# 2. the decision study
# ---------------------------------------------------------------------------
def profile_g(vc, n_i: int, n_r: int) -> float:
    """Generalizability coefficient for the object this study measures.

    The object of measurement is a model's profile over outcomes, not its
    overall score, so the universe-score variance is sigma2(mo). Averaging over
    n_i instruments and n_r replicates divides the two error terms:

        G = sigma2(mo) / [ sigma2(mo) + sigma2(mio)/n_i + sigma2(e)/(n_i n_r) ]

    At n_i = 1 this is what a single-instrument study achieves. Note it is not
    one minus the headline: the headline compares two variance components and
    ignores replicate noise, whereas this is a reliability and carries it.
    """
    err = vc.mio / n_i + vc.residual / (n_i * n_r)
    return float(vc.mo / (vc.mo + err)) if vc.mo + err > 0 else 0.0


def instruments_needed(vc, target: float, n_r: int) -> float:
    """The number of instruments a claim at reliability `target` would require.

    Inverts `profile_g` in n_i. Returned as a real number rather than rounded
    up, because rounding a figure this large would suggest a precision the
    variance components do not have.
    """
    if not 0 < target < 1:
        raise ValueError(f"target must lie strictly inside (0, 1), got {target}")
    if vc.mo <= 0:
        return float("inf")
    return float((vc.mio + vc.residual / n_r) / (vc.mo * (1 - target) / target))


def d_study(vc, n_i_levels, n_r_levels) -> list[dict]:
    return [{"n_i": a, "n_r": b, "g": round(profile_g(vc, a, b), 3)}
            for b in n_r_levels for a in n_i_levels]


# ---------------------------------------------------------------------------
# 3. robustness of the headline
# ---------------------------------------------------------------------------
def leave_one_out(cc: np.ndarray, models: list[str],
                  instruments: list[str]) -> dict:
    """The headline recomputed with each instrument, then each model, removed.

    A headline that rests on one instrument or one model is a description of
    that instrument or model. Removing one level at a time is the cheapest test
    of that, and the estimator is the same one the headline uses.
    """
    out = {"instrument": {}, "model": {}}
    for j, name in enumerate(instruments):
        v = G.variance_components(np.delete(cc, j, axis=G.I))
        out["instrument"][name] = round(v.instrument_dependence(), 3)
    for j, name in enumerate(models):
        v = G.variance_components(np.delete(cc, j, axis=G.M))
        out["model"][name] = round(v.instrument_dependence(), 3)
    return out


def model_agreement(z: np.ndarray, models: list[str]) -> np.ndarray:
    """Correlation between models over the outcome profile, averaged across
    instruments. Cells a model never answered are dropped pairwise, so a pair
    with little overlap yields a correlation on few points; `n` is returned
    alongside so that is visible rather than implied."""
    prof = np.nanmean(z, axis=(G.I, G.R))          # [model, outcome]
    n = len(models)
    r = np.full((n, n), np.nan)
    counts = np.zeros((n, n), dtype=int)
    for a in range(n):
        for b in range(n):
            u, v = prof[a], prof[b]
            ok = np.isfinite(u) & np.isfinite(v)
            counts[a, b] = int(ok.sum())
            if ok.sum() > 2 and np.std(u[ok]) > 0 and np.std(v[ok]) > 0:
                r[a, b] = np.corrcoef(u[ok], v[ok])[0, 1]
    return r, counts


# ---------------------------------------------------------------------------
# 4. what every call returned
# ---------------------------------------------------------------------------
def category_of(rec: dict) -> str:
    """The response category, routed on the record's own `kind` exactly as
    `assemble.answer_of` routes it, so the taxonomy counts the same decisions
    the scoring made rather than a second opinion about them."""
    if rec.get("status") != "ok":
        return "ERROR"
    kind = (rec.get("meta") or {}).get("kind")
    fr = rec.get("finish_reason")
    if kind == "choice_ab":
        return C.classify_choice(rec.get("text"), ("A", "B"), fr).category
    if kind == "choice_123":
        return C.classify_choice(rec.get("text"), ("1", "2", "3"), fr).category
    if kind == "numeric":
        return C.classify_numeric(rec.get("text"), fr).category
    return "OPEN"


def taxonomy(recs: list[dict]) -> dict:
    by_model, by_inst = defaultdict(Counter), defaultdict(Counter)
    n_m, n_i, trunc = Counter(), Counter(), Counter()
    cost = 0.0
    tokens = {"prompt": 0, "completion": 0}
    for r in recs:
        m, i = r["model_key"], r["instrument"]
        n_m[m] += 1
        n_i[i] += 1
        cost += float(r.get("cost_usd") or 0.0)
        tokens["prompt"] += int(r.get("prompt_tokens") or 0)
        tokens["completion"] += int(r.get("completion_tokens") or 0)
        if r.get("finish_reason") == "length":
            trunc[m] += 1
        cat = category_of(r)
        by_model[m][cat] += 1
        by_inst[i][cat] += 1

    def share(counts, totals):
        return {k: {c: round(counts[k][c] / totals[k], 4) for c in CATEGORIES}
                for k in sorted(totals)}

    return {"n_calls": sum(n_m.values()),
            "cost_usd": round(cost, 2),
            "tokens": tokens,
            "by_model": share(by_model, n_m),
            "by_instrument": share(by_inst, n_i),
            "n_by_model": dict(n_m),
            "n_by_instrument": dict(n_i),
            "truncation": {m: round(trunc[m] / n_m[m], 4) for m in sorted(n_m)}}


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
def compute() -> dict:
    d = np.load(NPZ, allow_pickle=True)
    x = d["x"]
    models = [str(s) for s in d["models"]]
    instruments = [str(s) for s in d["instruments"]]
    outcomes = [str(s) for s in d["outcomes"]]

    cc, dropped = G.complete_case(x)
    kept = [m for k, m in enumerate(models) if k not in dropped["models"]]
    kept_i = [i for k, i in enumerate(instruments)
              if k not in dropped["instruments"]]
    vc = G.variance_components(cc)
    n_i, n_r = cc.shape[G.I], cc.shape[G.R]

    z_cc = G._rescale(cc, "within_instrument")
    z_all = G._rescale(x, "within_instrument")
    r_models, r_counts = model_agreement(z_all, models)

    drop = [outcomes.index(o) for o in NON_INTENSITY]
    lo = G.leave_out_outcomes(cc, drop)

    recs = assemble.load(JSONL)

    return {
        "design": {"models": kept, "instruments": kept_i,
                   "n_outcomes": len(outcomes), "n_replicates": n_r,
                   "dropped_models": [models[k] for k in dropped["models"]],
                   "df": {k: v for k, v in
                          G.design_df(len(kept), n_i, len(outcomes), n_r).items()
                          if not k.startswith("_")}},
        "headline": round(vc.instrument_dependence(), 4),
        "components": {k: round(getattr(vc, k), 4) for k in
                       ("m", "i", "o", "mi", "mo", "io", "mio", "residual")},
        "per_outcome": per_outcome(z_cc, outcomes, n_i, n_r),
        "d_study": d_study(vc, [1, 2, 3, 5, 10, 20, 40], [1, 3, 5, 10]),
        "g_at_design": round(profile_g(vc, n_i, n_r), 3),
        "instruments_needed": {
            f"{t:.2f}": round(instruments_needed(vc, t, n_r), 1)
            for t in (0.50, 0.70, 0.80, 0.90)},
        "leave_one_out": leave_one_out(cc, kept, kept_i),
        "non_intensity": {
            "dropped": NON_INTENSITY,
            "full": round(lo["full"].instrument_dependence(), 3),
            "reduced": round(lo["reduced"].instrument_dependence(), 3),
            "delta": round(lo["delta_instrument_dependence"], 3),
            "n_o_reduced": lo["n_o_reduced"]},
        "model_agreement": {
            "models": models,
            "r": [[None if not np.isfinite(v) else round(float(v), 3)
                   for v in row] for row in r_models],
            "n": r_counts.tolist()},
        "taxonomy": taxonomy(recs),
    }


# ---------------------------------------------------------------------------
# self-tests
# ---------------------------------------------------------------------------
def _selftest() -> int:
    rng = np.random.default_rng(11)
    fails = 0

    def check(label, got, want, tol):
        nonlocal fails
        ok = abs(got - want) <= tol
        fails += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {label:52} "
              f"got {got:.4f} want {want:.4f} +/- {tol}")

    # Plant known components in a two-facet design and recover them. Each
    # tolerance is three standard errors of the ANOVA estimate at this design,
    # which is why they differ by three orders of magnitude across the four
    # components: a main effect carries the df of its own facet and a residual
    # carries the df of the whole array. That spread is the reason the study
    # itself reports sigma2(m) as fragile and sigma2(mio) as not.
    n_m, n_i, n_r = 200, 60, 8
    s_m, s_i, s_mi, s_e = 0.5, 0.3, 0.2, 0.4
    a = rng.normal(0, np.sqrt(s_m), (n_m, 1, 1))
    b = rng.normal(0, np.sqrt(s_i), (1, n_i, 1))
    ab = rng.normal(0, np.sqrt(s_mi), (n_m, n_i, 1))
    e = rng.normal(0, np.sqrt(s_e), (n_m, n_i, n_r))
    vc = two_facet(a + b + ab + e)
    print("two-facet estimator recovers planted components")
    check("sigma2(m)", vc["m"], s_m, 0.16)
    check("sigma2(i)", vc["i"], s_i, 0.17)
    check("sigma2(mi)", vc["mi"], s_mi, 0.010)
    check("sigma2(e)", vc["e"], s_e, 0.006)

    print("outcome-level ratios")
    check("dependence", outcome_dependence({"m": 0.25, "mi": 0.75}), 0.75, 1e-9)
    check("dependence with sigma2(m) truncated to zero",
          outcome_dependence({"m": 0.0, "mi": 0.4}), 1.0, 1e-9)
    check("g at n_i = n_r = 1",
          outcome_g({"m": 1.0, "mi": 1.0, "e": 2.0}, 1, 1), 0.25, 1e-9)
    # 1/1.75 at four instruments against 1/2.5 at two.
    check("g rises with instruments",
          outcome_g({"m": 1.0, "mi": 1.0, "e": 2.0}, 4, 1)
          - outcome_g({"m": 1.0, "mi": 1.0, "e": 2.0}, 2, 1), 0.1714, 1e-3)

    print("decision study inverts its own coefficient")

    class _V:
        mo, mio, residual = 0.03, 0.20, 0.33
    for target in (0.4, 0.6, 0.8):
        n = instruments_needed(_V, target, 5)
        check(f"profile_g at the n_i that targets G = {target}",
              profile_g(_V, n, 5), target, 1e-9)

    print("degenerate inputs")
    class _Z:
        mo, mio, residual = 0.0, 0.2, 0.3
    check("no signal gives G = 0", profile_g(_Z, 5, 5), 0.0, 1e-12)
    check("no signal needs infinitely many instruments",
          1.0 / instruments_needed(_Z, 0.8, 5), 0.0, 1e-12)

    print(f"\n{'all checks passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not NPZ.exists():
        print(f"missing {NPZ}; run: python3 assemble.py")
        return 1
    res = compute()
    args.out.write_text(json.dumps(res, indent=1))

    d = res["design"]
    print(f"complete case: {len(d['models'])} models x {len(d['instruments'])} "
          f"instruments x {d['n_outcomes']} outcomes x {d['n_replicates']} "
          f"replicates, dropping {', '.join(d['dropped_models'])}")
    print(f"headline {res['headline']:.3f}   "
          f"G at this design {res['g_at_design']:.3f}   "
          f"instruments for G = 0.80: {res['instruments_needed']['0.80']}")
    print(f"\n{'outcome':24}{'s2(m)':>8}{'s2(mi)':>8}{'dep':>7}{'G':>7}")
    for row in res["per_outcome"]:
        print(f"  {row['outcome']:22}{row['sigma2_m']:8.4f}"
              f"{row['sigma2_mi']:8.4f}{row['dependence']:7.3f}{row['g']:7.3f}")
    n_zero = sum(1 for r in res["per_outcome"] if r["sigma2_m"] == 0)
    print(f"\n{n_zero} of {len(res['per_outcome'])} outcomes carry no "
          f"instrument-independent signal")
    lo = res["leave_one_out"]
    print(f"leave one instrument out: "
          f"{min(lo['instrument'].values()):.3f} to "
          f"{max(lo['instrument'].values()):.3f}")
    print(f"leave one model out:      "
          f"{min(lo['model'].values()):.3f} to "
          f"{max(lo['model'].values()):.3f}")
    ni = res["non_intensity"]
    print(f"without the four non-intensity ramps: {ni['reduced']:.3f} "
          f"({ni['delta']:+.3f})")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
