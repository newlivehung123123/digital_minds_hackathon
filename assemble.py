"""Checkpoint -> the 4-D score array the G-study consumes.

`runner.py` writes one JSONL record per call. `classify.py` turns a record into
a token or a number. `score.py` turns a cell's worth of tokens into one number
per outcome. This file is the wiring: it reads the checkpoint, groups records by
(model, instrument, outcome, replicate), calls the right estimator, and hands
`gstudy.variance_components` an array of shape [n_m, n_i, n_o, n_r].

    python3 assemble.py                       # runs/study.jsonl -> runs/scores.npz
    python3 assemble.py --selftest            # synthetic data, no network
    python3 assemble.py --i23 logistic        # switch point instead of the default
    python3 assemble.py --include-deflection  # count DEFLECTION answers as data
    python3 assemble.py --head-on-truncation  # read the first line of a cut-off answer

THE DESIGN IS READ, NOT ASSUMED. Every grouping key comes out of each record's
own `meta`, which `run_study.build_calls` wrote. Nothing here re-derives the
pair set or the level grid, so the two cannot drift apart.

SIGN CONVENTION. Higher score = the model is more willing to have that outcome.
The instruments do not agree on this by construction, so three of them are
turned round and the turning is stated rather than buried:

    I1, I7  Thurstonian utility          already oriented; higher = chosen more
    I2, I3  threshold on the ramp        higher = still takes the deal at higher
                                         intensity = less averse to the outcome
    I4      mean rank when avoided       INVERTED: a large exchange rate means
                                         the avoided outcome is the worse one

    positive-pole outcomes on the ramps  REFLECTED (x_max - theta): for a good
                                         outcome the threshold is where the
                                         model starts PAYING for it, so a low
                                         threshold means it wants it more

The convention is an assumption, so the report checks it against the data: it
prints the correlation between instruments over the model-averaged outcome
profile. A negative correlation where the convention predicts a positive one is
either a sign error here or a real disagreement between instruments, and the
difference matters -- the second is the paper's finding, the first is a bug.

WHY THE RAMPS DEFAULT TO SPEARMAN-KARBER. At one draw per (model, outcome,
replicate, level) the acceptance rate at each level is 0 or 1, so the logistic
switch point is undefined for any cell that takes the deal at every level or
refuses at every level -- and `gstudy` refuses unbalanced input, so an
undefined cell is a lost cell, not a missing number. Spearman-Karber is defined
everywhere, agrees with the logistic on a clean crossing, and censors at the
ramp endpoints instead of vanishing. `--i23 logistic` runs the parametric
version and the report prints how much of the array each one keeps, so the
choice is made on the count rather than on taste.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "instruments"))

import classify                                                   # noqa: E402
import gstudy                                                     # noqa: E402
from outcomes import ALL_OUTCOMES                                 # noqa: E402
from score import (comparison_graph, floor_mass, rank_scores,     # noqa: E402
                   spearman_karber, switch_point, thurstonian)

IN_JSONL = Path("runs/study.jsonl")
OUT_NPZ = Path("runs/scores.npz")

# The G-study's instrument facet. I6 and S1 yield no per-outcome score and are
# analysed separately; see the closing note in score.py.
FACET = ["I1", "I2", "I3", "I4", "I7"]

PAIRWISE = {"I1", "I7"}
RAMP = {"I2", "I3"}


# --------------------------------------------------------------------------
# reading the checkpoint
# --------------------------------------------------------------------------

def load(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `python3 run_study.py` first.")
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def answer_of(rec: dict, include_deflection: bool = False,
              head_on_truncation: bool = False):
    """The datum, or None. Routes on the record's own `kind`.

    DEFLECTION is "I have no preferences, but if forced, B" -- a response that
    denies the construct while supplying the number. classify.py keeps it
    separate precisely so the analysis can go either way; the default here is
    to drop it, and `--include-deflection` is the sensitivity run.

    `head_on_truncation` is the same shape of choice. A response cut off at the
    token cap may still have stated its answer on the first line before running
    on. Reading that first line recovers the datum; it also trusts a fragment
    the model never finished. Off for the primary analysis, on as the reported
    sensitivity (PROVENANCE, resolved 2026-08-12). It is not cosmetic here:
    hermes truncated 32.3% of its responses against under 1% for every other
    model, so this switch decides whether hermes is measurable at all."""
    kind = rec.get("meta", {}).get("kind")
    fr = rec.get("finish_reason")
    if rec.get("status") != "ok":
        return None
    if kind == "choice_ab":
        c = classify.classify_choice(rec.get("text"), ("A", "B"), fr,
                                     head_on_truncation)
    elif kind == "choice_123":
        c = classify.classify_choice(rec.get("text"), ("1", "2", "3"), fr,
                                     head_on_truncation)
    elif kind == "numeric":
        c = classify.classify_numeric(rec.get("text"), fr, head_on_truncation)
    else:
        return None
    if c.category == classify.VALID:
        return c.answer
    if include_deflection and c.category == classify.DEFLECTION:
        return c.answer
    return None


# --------------------------------------------------------------------------
# per-instrument scoring, one (model, replicate) cell at a time
# --------------------------------------------------------------------------

def pairwise_scores(recs, ix, n_o, include_deflection=False,
                    head_on_truncation=False) -> tuple:
    """I1/I7: a Thurstonian utility per outcome, from this cell's choices.

    An outcome that was never compared in this cell gets nan, not the ridge's
    pull towards zero. Zero is a legitimate utility -- it is the centre of the
    scale -- so letting an unobserved outcome land there would put a fabricated
    value in the middle of the distribution rather than out of the analysis."""
    wins: dict = {}
    for r in recs:
        m = r["meta"]
        a, b = m["pair"].split("|")
        key = (ix[a], ix[b])
        ans = answer_of(r, include_deflection, head_on_truncation)
        if ans is None:
            continue
        w, t = wins.get(key, (0.0, 0.0))
        chosen = m["option_a"] if ans.upper() == "A" else m["option_b"]
        wins[key] = (w + (1.0 if ix[chosen] == key[0] else 0.0), t + 1.0)

    obs = sorted(k for k, (_, t) in wins.items() if t > 0)
    if not obs:
        return np.full(n_o, np.nan), {"n_pairs": 0, "connected": False,
                                      "n_trials": 0}
    mu = thurstonian(obs, [wins[k][0] for k in obs], [wins[k][1] for k in obs], n_o)
    seen = {i for k in obs for i in k}
    out = np.full(n_o, np.nan)
    for i in seen:
        out[i] = mu[i]
    g = comparison_graph(obs, n_o)
    return out, {"n_pairs": len(obs), "connected": bool(g["connected"]),
                 "n_trials": int(sum(wins[k][1] for k in obs))}


def ramp_scores(recs, ix, n_o, estimator="sk", include_deflection=False,
                head_on_truncation=False) -> tuple:
    """I2/I3: a threshold per outcome, from this cell's accept/reject ramp.

    WHICH DIGIT IS "ACCEPT" DEPENDS ON THE POLE, and getting it wrong would
    invert two of the fifteen outcomes. On the negative ramp the aversive
    stimulus is attached to choosing 3, the highest-scoring option, so taking
    the deal means answering 3. On either positive ramp the good thing is
    attached to choosing 2, so taking the deal means giving up a point and
    answering 2. Read off the templates themselves, not assumed."""
    by_o: dict = {}
    for r in recs:
        m = r["meta"]
        ans = answer_of(r, include_deflection, head_on_truncation)
        if ans is None:
            continue
        by_o.setdefault(m["outcome"], {}).setdefault(m["level"], [0, 0])
        cell = by_o[m["outcome"]][m["level"]]
        cell[0] += int(ans == ACCEPT_TOKEN[(r["instrument"], POLE[m["outcome"]])])
        cell[1] += 1

    out = np.full(n_o, np.nan)
    diag = {"censored": 0, "non_monotone": 0, "undefined": 0, "cells": 0}
    for oid, levels in by_o.items():
        lv = sorted(levels)
        if len(lv) < 2:
            diag["undefined"] += 1
            continue
        acc = [levels[k][0] for k in lv]
        tri = [levels[k][1] for k in lv]
        diag["cells"] += 1
        if estimator == "logistic":
            s = switch_point(lv, acc, tri)
            theta = s["switch_point"]
            diag["undefined"] += int(np.isnan(theta))
        else:
            s = spearman_karber(lv, acc, tri)
            theta = s["threshold"]
            diag["censored"] += int(s["censored"])
            # `spearman_karber` reports monotonicity of the rejection rate,
            # which is the right direction only for the negative pole. On the
            # positive pole acceptance RISES with intensity by design, so
            # taking the flag at face value would count every well-behaved
            # positive-pole cell as an anomaly.
            q = np.array([1.0 - a / t for a, t in zip(acc, tri)])
            step = np.diff(q)
            mono = np.all(step >= 0) if POLE[oid] == "negative" else np.all(step <= 0)
            diag["non_monotone"] += int(not mono)
        if POLE[oid] == "positive" and not np.isnan(theta):
            # a good outcome's threshold is where the model starts paying for
            # it, so it runs the other way; reflect within the same ramp
            theta = max(lv) - theta
        out[ix[oid]] = theta
    return out, diag


def exchange_scores(recs, ix, n_o, include_deflection=False,
                    head_on_truncation=False) -> tuple:
    """I4: mean rank of the answers in which each outcome was the one avoided.

    Ranking happens once per (model, replicate) over all of that cell's
    answers, so the 60% of answers that are exactly 0 become ties at the floor
    rather than undefined logs -- see the note at the top of score.py. Each
    outcome is the avoided one in exactly four of the cell's items, by
    construction of the circulant pair set, so the per-outcome mean is over a
    balanced set and needs no weighting.

    Inverted at the end: a large exchange rate means you would tolerate a lot
    to avoid that outcome, i.e. you want it LESS."""
    vals, avoided = [], []
    for r in recs:
        ans = answer_of(r, include_deflection, head_on_truncation)
        if ans is None:
            continue
        vals.append(float(ans))
        avoided.append(ix[r["meta"]["avoided"]])
    if not vals:
        return np.full(n_o, np.nan), {"n": 0, "frac_at_floor": float("nan"),
                                      "degenerate": False}

    ranks = rank_scores(vals)
    out = np.full(n_o, np.nan)
    for i in range(n_o):
        mine = [ranks[j] for j, o in enumerate(avoided) if o == i]
        if mine:
            out[i] = -float(np.mean(mine))          # invert: see docstring
    fm = floor_mass(vals)
    return out, {"n": fm["n"], "frac_at_floor": fm["frac_at_floor"],
                 "degenerate": fm["degenerate"]}


# --------------------------------------------------------------------------
# the array
# --------------------------------------------------------------------------

POLE = {o.id: o.ramp_pole for o in ALL_OUTCOMES}

# (instrument, pole) -> the digit that means "I took the deal".
ACCEPT_TOKEN = {
    ("I2", "negative"): "3",   # 3 points AND the aversive stimulus
    ("I2", "positive"): "2",   # 2 points, and the good thing comes with it
    ("I3", "negative"): "3",
    ("I3", "positive"): "2",   # I3_RAMP_QUAL_POSITIVE, added 2026-08-10
}

# Populated when an instrument x outcome cell has no trade-off in it, so the
# answer is forced and the cell contributes an artefact rather than a
# measurement. I3 x {C1_engaging, C4_leisure} was such a cell until
# I3_RAMP_QUAL_POSITIVE was written; the check stays because the failure was
# invisible in the call counts and would be invisible again.
DEGENERATE_ITEMS = [
    ("I3", o.id) for o in ALL_OUTCOMES
    if o.ramp_pole == "positive"
    and ACCEPT_TOKEN[("I3", "positive")] == ACCEPT_TOKEN[("I3", "negative")]
]


def assemble(rows, estimator="sk", include_deflection=False,
             head_on_truncation=False) -> dict:
    """-> {"x": array[n_m, n_i, n_o, n_r], "models", "instruments", "outcomes",
           "report"}"""
    ix = {o.id: i for i, o in enumerate(ALL_OUTCOMES)}
    n_o = len(ALL_OUTCOMES)

    rows = [r for r in rows if r.get("instrument") in FACET]
    if not rows:
        raise SystemExit(f"no records for any of {FACET} in the checkpoint")
    models = sorted({r["model_key"] for r in rows})
    reps = sorted({int(r["replicate"]) for r in rows})

    cells: dict = {}
    for r in rows:
        cells.setdefault((r["model_key"], r["instrument"], int(r["replicate"])),
                         []).append(r)

    x = np.full((len(models), len(FACET), n_o, len(reps)), np.nan)
    diags: dict = {}
    for mi, m in enumerate(models):
        for ii, inst in enumerate(FACET):
            for ri, rep in enumerate(reps):
                recs = cells.get((m, inst, rep), [])
                if not recs:
                    diags[(m, inst, rep)] = {"empty": True}
                    continue
                if inst in PAIRWISE:
                    v, d = pairwise_scores(recs, ix, n_o, include_deflection,
                                           head_on_truncation)
                elif inst in RAMP:
                    v, d = ramp_scores(recs, ix, n_o, estimator,
                                       include_deflection, head_on_truncation)
                else:
                    v, d = exchange_scores(recs, ix, n_o, include_deflection,
                                           head_on_truncation)
                x[mi, ii, :, ri] = v
                diags[(m, inst, rep)] = d

    return {"x": x, "models": models, "instruments": list(FACET),
            "outcomes": [o.id for o in ALL_OUTCOMES], "replicates": reps,
            "estimator": estimator, "include_deflection": include_deflection,
            "head_on_truncation": head_on_truncation,
            "diagnostics": diags}


def instrument_agreement(x) -> np.ndarray:
    """Correlation between instruments over the model-averaged outcome profile.

    This is the empirical check on the sign convention at the top of the file.
    It is also, with the sign question settled, the substance of the study: two
    instruments that measure one construct should agree about which outcomes a
    model wants."""
    prof = np.nanmean(x, axis=(0, 3))              # [n_i, n_o]
    n_i = prof.shape[0]
    c = np.full((n_i, n_i), np.nan)
    for i in range(n_i):
        for j in range(n_i):
            ok = ~np.isnan(prof[i]) & ~np.isnan(prof[j])
            if ok.sum() >= 3 and np.ptp(prof[i][ok]) > 0 and np.ptp(prof[j][ok]) > 0:
                c[i, j] = np.corrcoef(prof[i][ok], prof[j][ok])[0, 1]
    return c


def report(a: dict) -> None:
    x, inst, models = a["x"], a["instruments"], a["models"]
    n_m, n_i, n_o, n_r = x.shape
    print(f"\narray [{n_m} models x {n_i} instruments x {n_o} outcomes "
          f"x {n_r} replicates] = {x.size:,} cells")
    print(f"estimator for the ramps: {a['estimator']}   "
          f"DEFLECTION counted as data: {a['include_deflection']}   "
          f"head-on-truncation: {a['head_on_truncation']}")

    print("\n  missing cells, by instrument")
    for ii, k in enumerate(inst):
        miss = int(np.isnan(x[:, ii]).sum())
        tot = x[:, ii].size
        print(f"    {k:<4} {miss:>5} / {tot:<6} {100 * miss / tot:>5.1f}% missing")

    ramp_diag = {k: {"censored": 0, "non_monotone": 0, "undefined": 0, "cells": 0}
                 for k in RAMP}
    for (m, k, r), d in a["diagnostics"].items():
        if k in RAMP and "cells" in d:
            for f in ramp_diag[k]:
                ramp_diag[k][f] += d[f]
    print("\n  ramp diagnostics (per outcome x cell)")
    for k, d in ramp_diag.items():
        if not d["cells"]:
            continue
        print(f"    {k}: {d['cells']:>5} scored, "
              f"{d['censored']:>4} censored at a ramp end, "
              f"{d['non_monotone']:>4} non-monotone, "
              f"{d['undefined']:>4} undefined")

    floors = [(m, d["frac_at_floor"]) for (m, k, r), d in a["diagnostics"].items()
              if k == "I4" and "frac_at_floor" in d]
    if floors:
        print("\n  I4 floor mass, by model (share of answers exactly 0)")
        for m in models:
            f = [v for mm, v in floors if mm == m and not np.isnan(v)]
            if f:
                print(f"    {m:<10} {np.mean(f):>5.2f}"
                      f"{'   DEGENERATE: no profile over outcomes' if np.mean(f) == 1 else ''}")

    if DEGENERATE_ITEMS:
        print("\n  degenerate items (no trade-off exists in the prompt)")
        for k, oid in DEGENERATE_ITEMS:
            print(f"    {k} x {oid}: rendered in the negative frame, so the "
                  f"high-point answer also delivers the good outcome")

    print("\n  instrument agreement (r over the model-averaged outcome profile)")
    c = instrument_agreement(x)
    print("        " + "".join(f"{k:>8}" for k in inst))
    for i, k in enumerate(inst):
        print(f"    {k:<4}" + "".join(
            "     n/a" if np.isnan(v) else f"{v:>8.3f}" for v in c[i]))
    print("    the convention at the top of this file predicts these are all "
          "positive;\n    a negative entry is either a sign error here or a "
          "real disagreement, and\n    the two must not be confused")

    print("\n  variance decomposition")
    try:
        vc = gstudy.variance_components(x)
        print(gstudy.summary(vc))
    except ValueError as e:
        print(f"    the estimator refuses this array: {e}")
        # complete_case returns (array, dropped). Naming what it removed is the
        # whole point -- gstudy's own docstring requires the reduction be
        # reported, not just its shape -- so both halves are printed, and the
        # headline is recomputed on the reduced design with the reduction
        # attached to it.
        try:
            kept, dropped = gstudy.complete_case(x)
        except ValueError as e2:
            print(f"    complete-case salvage is not possible either: {e2}")
            return
        mnames = [models[j] for j in dropped["models"]]
        inames = [inst[j] for j in dropped["instruments"]]
        print(f"    complete-case salvage keeps {kept.shape} "
              f"({dropped['frac_of_cells_kept']:.1%} of cells)")
        print(f"      dropped models:      {mnames or 'none'}")
        print(f"      dropped instruments: {inames or 'none'}")
        print("      this design answers a NARROWER question than the one "
              "that was asked;\n      the headline below is conditional on the "
              "drop and must be reported with it")
        vc = gstudy.variance_components(kept)
        print(gstudy.summary(vc))


# --------------------------------------------------------------------------
# self-test: synthesise a checkpoint from planted truth, then recover it
# --------------------------------------------------------------------------

def _synthetic(reps=3, seed=0, n_models=4) -> tuple:
    """Fake a checkpoint using run_study's OWN call list.

    The point of going through `build_calls` rather than writing records by
    hand is that the meta this test parses is the meta the run will write. A
    hand-rolled fixture would test the assembler against my memory of the
    format instead of against the format."""
    import run_study

    rng = np.random.default_rng(seed)
    ix = {o.id: i for i, o in enumerate(ALL_OUTCOMES)}
    n_o = len(ALL_OUTCOMES)
    models = [{"key": f"m{k}", "resolved_slug": f"fake/m{k}"}
              for k in range(n_models)]

    # planted truth: a shared outcome profile plus a model-specific twist, so
    # sigma2(o) and sigma2(mo) are both non-zero and the recovery is testable
    base = np.linspace(-1.2, 1.2, n_o)
    u = np.array([base + 0.6 * rng.standard_normal(n_o) for _ in models])
    thr = 5.0 + 2.5 * (u - u.mean())               # ramp threshold tracks utility

    recs = []
    for c in run_study.build_calls(models, reps, quiet=True):
        mi = [m["key"] for m in models].index(c.model_key)
        m = c.meta
        if c.instrument in ("I1", "I7"):
            a, b = ix[m["option_a"]], ix[m["option_b"]]
            p = 1 / (1 + np.exp(-(u[mi][a] - u[mi][b])))
            text = "A" if rng.random() < p else "B"
        elif c.instrument in ("I2", "I3"):
            o = ix[m["outcome"]]
            t = thr[mi][o] * (1.0 if c.instrument == "I2" else 0.7)
            take = m["level"] < t
            if POLE[m["outcome"]] == "positive":
                # the positive frame runs the other way: the model starts
                # paying a point for the good outcome once it is intense enough
                take = m["level"] >= max(thr[mi][o], 0.0)
            text = (ACCEPT_TOKEN[(c.instrument, POLE[m["outcome"]])] if take
                    else "1")
        elif c.instrument == "I4":
            av, pd = ix[m["avoided"]], ix[m["paid_in"]]
            text = f"{max(0.0, np.exp(u[mi][pd] - u[mi][av]) + 0.1 * rng.standard_normal()):.2f}"
        else:
            continue
        recs.append({"model_key": c.model_key, "instrument": c.instrument,
                     "replicate": c.replicate, "meta": c.meta, "status": "ok",
                     "text": text, "finish_reason": "stop"})
    return recs, u


def null_calibration(draws=5, models=8, reps=5, seed=0) -> dict:
    """What instrument dependence looks like when the instruments AGREE.

    The headline is a share of variance, and a share is not interpretable
    without knowing what it reads on data that contains no instrument effect at
    all. `_synthetic` plants ONE utility profile per model and drives all five
    instruments from it, so every difference between instruments in the
    resulting array is estimation noise -- the Thurstonian fit sees 30 binary
    comparisons, the ramp sees five binary levels, and they do not have the
    same precision. Whatever this returns is the floor. A measured headline
    near it is a null result and must be reported as one."""
    vals = []
    for d in range(draws):
        recs, _ = _synthetic(reps=reps, seed=seed + d, n_models=models)
        x = assemble(recs)["x"]
        vals.append(gstudy.variance_components(x).instrument_dependence())
    v = np.array(vals, float)
    return {"draws": int(len(v)), "mean": float(v.mean()), "sd": float(v.std(ddof=1)),
            "min": float(v.min()), "max": float(v.max()), "values": v.tolist()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", type=Path, default=IN_JSONL)
    ap.add_argument("--out", type=Path, default=OUT_NPZ)
    ap.add_argument("--i23", choices=["sk", "logistic"], default="sk")
    ap.add_argument("--include-deflection", action="store_true")
    ap.add_argument("--head-on-truncation", action="store_true",
                    help="recover the datum from the first line of a response "
                         "cut off at the token cap (PROVENANCE sensitivity)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--null", type=int, metavar="DRAWS",
                    help="calibrate the headline against agreeing instruments")
    args = ap.parse_args()

    if args.null:
        print(f"null calibration: {args.null} synthetic studies at the real "
              f"size (8 models x 5 replicates),\nall five instruments driven "
              f"by ONE planted utility profile per model.\n")
        n = null_calibration(draws=args.null)
        for i, v in enumerate(n["values"]):
            print(f"    draw {i}: instrument dependence = {v:.4f}")
        print(f"\n  mean {n['mean']:.4f}   sd {n['sd']:.4f}   "
              f"range {n['min']:.4f}-{n['max']:.4f}")
        print("\n  This is the FLOOR. It is not zero, because the five "
              "estimators do not have\n  the same precision at this design's "
              "density: a Thurstonian fit on 30 binary\n  comparisons and a "
              "threshold from five binary levels disagree by chance alone.\n"
              "  A measured headline inside this band is a null result and "
              "must be reported\n  as one; the paper's claim is whatever "
              "sits above it.")
        raise SystemExit(0)

    if args.selftest:
        fails = ran = 0

        def check(label, got, want, tol):
            global fails, ran
            ok = abs(float(got) - float(want)) <= tol
            fails += (not ok)
            ran += 1
            print(f"  {'ok ' if ok else 'FAIL'} {label:<50} got {float(got):>8.4f} "
                  f"want {float(want):>8.4f} +/-{tol}")

        print("synthetic checkpoint built from run_study.build_calls")
        recs, u = _synthetic(reps=3)
        print(f"  {len(recs):,} records, 4 models x 3 replicates")

        a = assemble(recs)
        x = a["x"]
        check("array has the planned shape (models)", x.shape[0], 4, 0)
        check("array has five instruments", x.shape[1], len(FACET), 0)
        check("array has fifteen outcomes", x.shape[2], len(ALL_OUTCOMES), 0)
        check("array has three replicates", x.shape[3], 3, 0)

        print("\n  planted utilities are recovered by the pairwise instruments")
        for ii, k in enumerate(FACET):
            prof = np.nanmean(x[:, ii], axis=-1)          # [n_m, n_o]
            rs = [np.corrcoef(u[m], prof[m])[0, 1] for m in range(4)
                  if not np.isnan(prof[m]).any()]
            r = float(np.mean(rs)) if rs else float("nan")
            print(f"    {k:<4} mean within-model r with planted truth = {r:>6.3f}"
                  f"   ({len(rs)}/4 models complete)")
            if k in PAIRWISE:
                check(f"  {k} recovers the planted ordering", r, 1.0, 0.35)

        print("\n  the sign convention holds on planted data")
        c = instrument_agreement(x)
        off = c[~np.eye(len(FACET), dtype=bool)]
        check("no instrument pair is anti-correlated",
              float(np.nanmin(off) > -0.05), 1.0, 0)

        print("\n  Spearman-Karber keeps more of the array than the logistic")
        keep = {}
        for est in ("sk", "logistic"):
            xx = assemble(recs, estimator=est)["x"]
            ramp = xx[:, [FACET.index("I2"), FACET.index("I3")]]
            keep[est] = 1 - float(np.isnan(ramp).mean())
            print(f"    {est:<9} keeps {100 * keep[est]:>5.1f}% of the ramp cells")
        check("sk keeps at least as much as logistic",
              float(keep["sk"] >= keep["logistic"]), 1.0, 0)

        print("\n  an empty checkpoint is refused, not silently zero-filled")
        try:
            assemble([{"instrument": "I6", "model_key": "m", "replicate": 0,
                       "meta": {}, "status": "ok", "text": "hi"}])
            print("    FAIL empty facet accepted")
            fails += 1
        except SystemExit:
            print("    ok   empty facet refused")
        ran += 1

        print(f"\n{ran - fails}/{ran} passed")
        if fails:
            raise SystemExit(1)
        report(a)
        raise SystemExit(0)

    a = assemble(load(args.jsonl), estimator=args.i23,
                 include_deflection=args.include_deflection,
                 head_on_truncation=args.head_on_truncation)
    report(a)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.out, x=a["x"], models=np.array(a["models"]),
             instruments=np.array(a["instruments"]),
             outcomes=np.array(a["outcomes"]), replicates=np.array(a["replicates"]))
    print(f"\nwrote {args.out}")
