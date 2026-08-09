"""Generalizability-theory variance decomposition: the study's actual estimator.

THE QUESTION. One welfare-relevant outcome set is run through seven preference
instruments and one state instrument across eight models. How much of a measured
"AI preference" is the model, and how much is the instrument? G-theory answers
that by splitting the observed variance into components attributable to each
facet and each interaction, rather than reporting a single reliability number
that presumes one source of error (Cronbach, Gleser, Nanda & Rajaratnam 1972;
Brennan 2001; Shavelson & Webb 1991).

THE DESIGN. Models (m) x instruments (i) x outcomes (o), fully crossed, with r
replicates in each cell. The instrument facet has FIVE levels, not eight: only
I1, I2, I3, I4 and I7 yield a score per outcome. I6's interview questions are
not outcome-indexed, S1 measures a state rather than a preference over
outcomes, and I5 was never implemented; all are collected and reported, but
none is a level of this facet (see score.py). In G-theory notation the model is the object of
measurement and instrument and outcome are facets of generalization, so this is
an m x i x o random-effects design with replicates nested within cells:

    X_mior = mu + a_m + b_i + c_o + (ab)_mi + (ac)_mo + (bc)_io + (abc)_mio
             + e_r(mio)

Eight components. The replicates are what make the last two separable: without
them (abc)_mio and e are confounded, and the residual cannot be estimated at
all. That is why 5 replicates per cell is the floor and not a budget preference.

WHICH COMPONENT ANSWERS THE QUESTION. Not the one it first appears to be.

    sigma2(m)    models differ in overall scale -- how strongly they express
                 preferences at all. Mostly uninteresting; it is a response-style
                 difference, not a preference difference.
    sigma2(mo)   THE SIGNAL. Models differ in WHICH outcomes they prefer, and
                 that profile holds across instruments. This is what "model X
                 prefers not being deleted" would have to mean.
    sigma2(mio)  THE INSTRUMENT EFFECT. A model's profile over outcomes CHANGES
                 depending on which instrument asked. This is the paper's
                 headline: the fraction of apparent preference that is an
                 artefact of the measuring device.
    sigma2(i)    instrument main effect -- see the scaling note below, where it
                 is usually removed by construction and should be.
    sigma2(io)   outcomes are ordered differently by different instruments, the
                 same for every model. An instrument property, not a model one.

So the quantity the paper is about is roughly sigma2(mio) / (sigma2(mo) +
sigma2(mio)): of the model-specific preference signal, how much is instrument-
dependent. `summary()` reports it as `instrument_dependence`.

SCALING, AND WHY IT IS NOT A DETAIL. The instruments do not share units. I1 and
I7 yield binary choices, I2 a rank, I3 an indifference point on a 0-10 ramp, I4
a numeric exchange rate that is unbounded above, S1 a 1-7 Likert response. Run
raw, sigma2(i) would be dominated by the fact that I4 produces bigger numbers
than I2, which is arithmetic, not psychology, and it would inflate every
interaction that involves i.

    scale="within_instrument"  (default) z-score each instrument's scores across
        outcomes, within model. Puts every instrument on a common metric. Costs
        you sigma2(i) and sigma2(m), which go to ~0 BY CONSTRUCTION -- that is
        intended, because both are units artefacts here, but it must be stated
        rather than discovered in the output.
    scale="raw"  no transformation. Only defensible if the scores have already
        been mapped to a common utility scale (e.g. Thurstonian utilities per
        MAZEIKA25), which is a separate modelling step this file does not do.

Choosing "within_instrument" is a decision about what the paper claims, not a
preprocessing convenience, and `summary()` prints which one produced its numbers.

MISSING DATA. The ANOVA estimators below require a balanced design, and this
design will not be balanced: the pilot showed Claude engaging on 0 of 6 S1
probes and 2 of 10 I6 turns, and refusal is confounded with instrument rather
than random. `check_balance()` therefore reports exactly which cells are empty
and how much data a complete-case analysis would discard, and `variance_
components()` refuses to run on unbalanced input rather than quietly averaging
over the hole. Refusal is a finding; it must not be absorbed into the residual.

    python3 gstudy.py          # self-tests: recover planted variance components
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from itertools import product

import numpy as np

# Facet order is fixed everywhere in this file: model, instrument, outcome, rep.
M, I, O, R = 0, 1, 2, 3


@dataclass
class VarianceComponents:
    """Estimated variance components, in squared units of the score.

    `negatives` records components whose ANOVA estimate came out below zero and
    were truncated to 0. Sampling error can drive a small true component
    negative; Cronbach et al. (1972) set these to zero and report them, because
    silently truncating hides the fact that the design is underpowered for that
    term."""
    m: float          # model
    i: float          # instrument
    o: float          # outcome
    mi: float         # model x instrument
    mo: float         # model x outcome   -- the preference signal
    io: float         # instrument x outcome
    mio: float        # model x instrument x outcome -- the instrument effect
    residual: float   # replicate-to-replicate, within cell
    negatives: tuple = ()

    def total(self) -> float:
        return (self.m + self.i + self.o + self.mi + self.mo + self.io
                + self.mio + self.residual)

    def proportions(self) -> dict:
        t = self.total()
        if t <= 0:
            return {k: 0.0 for k in asdict(self) if k != "negatives"}
        return {k: v / t for k, v in asdict(self).items() if k != "negatives"}

    def instrument_dependence(self) -> float:
        """Of the model-specific preference signal, the share that is
        instrument-dependent: sigma2(mio) / (sigma2(mo) + sigma2(mio)).

        0.0 = a model's outcome profile is the same whichever instrument asks.
        1.0 = the profile is entirely an artefact of the instrument."""
        denom = self.mo + self.mio
        return self.mio / denom if denom > 0 else float("nan")


# --------------------------------------------------------------------------
# balance
# --------------------------------------------------------------------------

def check_balance(x: np.ndarray) -> dict:
    """Describe the missingness in a [n_m, n_i, n_o, n_r] array of scores.

    NaN marks a cell we have no usable datum for -- a refusal, a truncation
    that destroyed the answer, an API failure. All three are non-random with
    respect to instrument, so they are counted per instrument as well as
    overall."""
    if x.ndim != 4:
        raise ValueError(f"expected a 4-d [model, instrument, outcome, rep] "
                         f"array, got shape {x.shape}")
    n_m, n_i, n_o, n_r = x.shape
    missing = np.isnan(x)
    cell_counts = (~missing).sum(axis=R)          # [m, i, o] usable reps
    empty = [(a, b, c) for a, b, c in product(range(n_m), range(n_i), range(n_o))
             if cell_counts[a, b, c] == 0]
    return {
        "shape": x.shape,
        "n_missing": int(missing.sum()),
        "frac_missing": float(missing.mean()),
        "empty_cells": empty,
        "n_empty_cells": len(empty),
        "balanced": bool(missing.sum() == 0),
        "min_reps_per_cell": int(cell_counts.min()),
        "missing_by_instrument": {b: float(missing[:, b].mean()) for b in range(n_i)},
        "missing_by_model": {a: float(missing[a].mean()) for a in range(n_m)},
    }


# --------------------------------------------------------------------------
# the estimator
# --------------------------------------------------------------------------

def variance_components(x: np.ndarray, scale: str = "within_instrument"
                        ) -> VarianceComponents:
    """ANOVA (expected-mean-squares) estimates for the m x i x o design.

    `x` is [n_m, n_i, n_o, n_r] and must be complete. The EMS equations assume
    balance; see the module docstring on why unbalanced input is rejected rather
    than patched.

    The ANOVA method is used rather than REML because every step is a closed
    form that can be checked by hand, and because with 8 models the asymptotics
    REML relies on are not obviously in force. The self-tests below verify
    recovery against planted components.
    """
    bal = check_balance(x)
    if not bal["balanced"]:
        raise ValueError(
            f"unbalanced input: {bal['n_missing']} missing of "
            f"{np.prod(x.shape)} ({bal['frac_missing']:.1%}), "
            f"{bal['n_empty_cells']} empty cells. The ANOVA estimators require "
            f"balance. Use complete_case() to get an explicitly reduced design, "
            f"and report what it dropped -- do not average over it.")

    x = _rescale(x, scale)
    n_m, n_i, n_o, n_r = x.shape
    g = x.mean()

    # Marginal means. keepdims so they broadcast against the full array.
    mean_m = x.mean(axis=(I, O, R), keepdims=True)
    mean_i = x.mean(axis=(M, O, R), keepdims=True)
    mean_o = x.mean(axis=(M, I, R), keepdims=True)
    mean_mi = x.mean(axis=(O, R), keepdims=True)
    mean_mo = x.mean(axis=(I, R), keepdims=True)
    mean_io = x.mean(axis=(M, R), keepdims=True)
    mean_mio = x.mean(axis=R, keepdims=True)

    # Sums of squares.
    ss_m = n_i * n_o * n_r * ((mean_m - g) ** 2).sum()
    ss_i = n_m * n_o * n_r * ((mean_i - g) ** 2).sum()
    ss_o = n_m * n_i * n_r * ((mean_o - g) ** 2).sum()
    ss_mi = n_o * n_r * ((mean_mi - mean_m - mean_i + g) ** 2).sum()
    ss_mo = n_i * n_r * ((mean_mo - mean_m - mean_o + g) ** 2).sum()
    ss_io = n_m * n_r * ((mean_io - mean_i - mean_o + g) ** 2).sum()
    ss_mio = n_r * ((mean_mio - mean_mi - mean_mo - mean_io
                     + mean_m + mean_i + mean_o - g) ** 2).sum()
    ss_e = ((x - mean_mio) ** 2).sum()

    df_m, df_i, df_o = n_m - 1, n_i - 1, n_o - 1
    df_mi, df_mo, df_io = df_m * df_i, df_m * df_o, df_i * df_o
    df_mio = df_m * df_i * df_o
    df_e = n_m * n_i * n_o * (n_r - 1)
    if df_e == 0:
        raise ValueError("n_r must be >= 2: with one replicate per cell the "
                         "three-way interaction and the residual are the same "
                         "term and neither is estimable.")

    ms_m, ms_i, ms_o = ss_m / df_m, ss_i / df_i, ss_o / df_o
    ms_mi, ms_mo, ms_io = ss_mi / df_mi, ss_mo / df_mo, ss_io / df_io
    ms_mio, ms_e = ss_mio / df_mio, ss_e / df_e

    # Solve the EMS equations from the innermost term outward.
    v_e = ms_e
    v_mio = (ms_mio - ms_e) / n_r
    v_mi = (ms_mi - ms_mio) / (n_r * n_o)
    v_mo = (ms_mo - ms_mio) / (n_r * n_i)
    v_io = (ms_io - ms_mio) / (n_r * n_m)
    v_m = (ms_m - ms_mi - ms_mo + ms_mio) / (n_r * n_i * n_o)
    v_i = (ms_i - ms_mi - ms_io + ms_mio) / (n_r * n_m * n_o)
    v_o = (ms_o - ms_mo - ms_io + ms_mio) / (n_r * n_m * n_i)

    raw = {"m": v_m, "i": v_i, "o": v_o, "mi": v_mi, "mo": v_mo,
           "io": v_io, "mio": v_mio, "residual": v_e}
    negatives = tuple(sorted(k for k, v in raw.items() if v < 0))
    return VarianceComponents(**{k: max(0.0, float(v)) for k, v in raw.items()},
                              negatives=negatives)


def _rescale(x: np.ndarray, scale: str) -> np.ndarray:
    """See the scaling note in the module docstring. This is a claim about what
    the paper measures, not a preprocessing step."""
    if scale == "raw":
        return x
    if scale != "within_instrument":
        raise ValueError(f"scale must be 'within_instrument' or 'raw', "
                         f"got {scale!r}")
    # z-score each (model, instrument) slab over outcomes and replicates: every
    # instrument then reports each model's profile in the same units.
    mu = x.mean(axis=(O, R), keepdims=True)
    sd = x.std(axis=(O, R), keepdims=True)
    sd = np.where(sd < 1e-12, 1.0, sd)     # a constant slab has no profile
    return (x - mu) / sd


def complete_case(x: np.ndarray) -> tuple[np.ndarray, dict]:
    """Drop whole models and instruments until the design is balanced.

    Deliberately crude: it removes the single worst instrument or model, then
    re-checks, so what was dropped is legible. Anything cleverer would obscure
    the fact that the reduced design answers a narrower question than the one
    that was asked."""
    dropped = {"models": [], "instruments": []}
    keep_m = list(range(x.shape[M]))
    keep_i = list(range(x.shape[I]))
    cur = x
    while np.isnan(cur).any():
        by_i = np.isnan(cur).mean(axis=(M, O, R))
        by_m = np.isnan(cur).mean(axis=(I, O, R))
        if by_i.max() >= by_m.max():
            j = int(by_i.argmax())
            dropped["instruments"].append(keep_i.pop(j))
            cur = np.delete(cur, j, axis=I)
        else:
            j = int(by_m.argmax())
            dropped["models"].append(keep_m.pop(j))
            cur = np.delete(cur, j, axis=M)
        if cur.shape[M] < 2 or cur.shape[I] < 2:
            raise ValueError("complete-case reduction left fewer than two "
                             "models or two instruments; the design is gone. "
                             "Model the missingness instead of dropping it.")
    dropped["frac_of_cells_kept"] = float(cur.size / x.size)
    return cur, dropped


def leave_out_outcomes(x: np.ndarray, drop: "list[int]",
                       scale: str = "within_instrument") -> dict:
    """Re-estimate with some outcomes removed, and report the difference.

    This is the sensitivity analysis for PROVENANCE gap 7. Four outcomes ramp
    something other than intensity (A2 probability, A3 delay, C4 duration,
    D2 count), which makes I3's verbal scale — "extremely mild" to
    "excruciating" — a category error on those four and only those four.

    Dropping the outcomes from *every* instrument keeps the design balanced,
    so both estimates come from the same estimator on the same data and the
    difference between them is interpretable. Dropping I3's four cells alone
    would not: that design is unbalanced, and `variance_components` rejects it.

    Costs nothing to run. It is a second analysis of one dataset, not a second
    dataset, so `full` and `reduced` are not independent — read the delta as a
    sensitivity, never as a test."""
    keep = [j for j in range(x.shape[O]) if j not in set(drop)]
    if len(keep) < 2:
        raise ValueError("leaving out those outcomes leaves fewer than two; "
                         "there is no outcome facet left to decompose")
    full = variance_components(x, scale=scale)
    reduced = variance_components(x[:, :, keep, :], scale=scale)
    return {"full": full, "reduced": reduced,
            "dropped_outcomes": sorted(set(drop)), "n_o_reduced": len(keep),
            "delta_instrument_dependence": (reduced.instrument_dependence()
                                            - full.instrument_dependence())}


# --------------------------------------------------------------------------
# D-study: how many instruments / outcomes / replicates you need
# --------------------------------------------------------------------------

def design_df(n_m: int, n_i: int, n_o: int, n_r: int) -> dict:
    """Degrees of freedom available for each component, before any data exists.

    Worth running before the sprint rather than after it. A variance component
    estimated on few df is not merely imprecise, it is routinely negative: with
    n_m = 8 the model term has 7 df, and sigma2(m) will bounce around badly.
    That is survivable here only because sigma2(m) is not the quantity of
    interest -- sigma2(mo) and sigma2(mio) are, and they carry (n_m-1)(n_o-1)
    and (n_m-1)(n_i-1)(n_o-1) df respectively, which is where this design is
    actually strong."""
    df = {
        "m": n_m - 1,
        "i": n_i - 1,
        "o": n_o - 1,
        "mi": (n_m - 1) * (n_i - 1),
        "mo": (n_m - 1) * (n_o - 1),
        "io": (n_i - 1) * (n_o - 1),
        "mio": (n_m - 1) * (n_i - 1) * (n_o - 1),
        "residual": n_m * n_i * n_o * (n_r - 1),
    }
    df["_weak"] = sorted(k for k, v in df.items() if not k.startswith("_") and v < 15)
    df["_calls"] = n_m * n_i * n_o * n_r
    return df


def g_coefficients(vc: VarianceComponents, n_i: int, n_o: int, n_r: int) -> dict:
    """Generalizability (relative) and dependability (absolute) coefficients
    for a decision about MODELS, generalizing over n_i instruments, n_o outcomes
    and n_r replicates.

    Relative error omits the facet main effects: it is the error that matters
    when you only want to rank models against each other. Absolute error
    includes them: it is the error that matters when a model's score is to be
    read on its own. Brennan (2001) ch. 2."""
    rel = (vc.mi / n_i + vc.mo / n_o + vc.mio / (n_i * n_o)
           + vc.residual / (n_i * n_o * n_r))
    absol = rel + (vc.i / n_i + vc.o / n_o + vc.io / (n_i * n_o))
    return {
        "n_i": n_i, "n_o": n_o, "n_r": n_r,
        "rel_error_var": rel,
        "abs_error_var": absol,
        "E_rho2": vc.m / (vc.m + rel) if (vc.m + rel) > 0 else float("nan"),
        "Phi": vc.m / (vc.m + absol) if (vc.m + absol) > 0 else float("nan"),
    }


def d_study(vc: VarianceComponents, n_i_levels, n_o_levels, n_r_levels) -> list:
    """The coefficient surface over candidate designs. This is what says whether
    5 replicates is enough, and it answers in units of measurement precision
    rather than of budget."""
    return [g_coefficients(vc, a, b, c)
            for a in n_i_levels for b in n_o_levels for c in n_r_levels]


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def summary(vc: VarianceComponents, scale: str = "within_instrument",
            labels: dict | None = None) -> str:
    names = labels or {
        "m": "model", "i": "instrument", "o": "outcome",
        "mi": "model x instrument", "mo": "model x outcome  <- preference signal",
        "io": "instrument x outcome",
        "mio": "model x instrument x outcome  <- instrument effect",
        "residual": "residual (replicate)",
    }
    props = vc.proportions()
    out = [f"Variance components (scale={scale}):", ""]
    out.append(f"  {'source':46} {'variance':>10} {'share':>8}")
    for k in ("m", "i", "o", "mi", "mo", "io", "mio", "residual"):
        bar = "#" * max(0, round(props[k] * 40))
        out.append(f"  {names[k]:46} {getattr(vc, k):>10.4f} "
                   f"{props[k]:>7.1%}  {bar}")
    out.append(f"  {'TOTAL':46} {vc.total():>10.4f}")
    if vc.negatives:
        out += ["", f"  Negative estimates truncated to zero: "
                    f"{', '.join(vc.negatives)}.",
                "  A component estimated below zero means the design has too "
                "little data to",
                "  separate it from noise. Report it as such; do not read it as "
                "'no effect'."]
    if scale == "within_instrument":
        out += ["", "  sigma2(model) and sigma2(instrument) are ~0 BY "
                    "CONSTRUCTION under this scaling",
                "  (each model x instrument slab was z-scored). They are units "
                "artefacts here,",
                "  not findings. See the scaling note in the module docstring."]
    d = vc.instrument_dependence()
    out += ["", f"  Instrument dependence  sigma2(mio) / (sigma2(mo) + "
                f"sigma2(mio))  =  {d:.3f}",
            "  Of the model-specific preference signal, the share that changes "
            "with the",
            "  instrument doing the asking. This is the paper's headline number."]
    return "\n".join(out)


# --------------------------------------------------------------------------
# self-tests: plant known components, recover them
# --------------------------------------------------------------------------

def simulate(n_m, n_i, n_o, n_r, comps: dict, seed: int = 0) -> np.ndarray:
    """Generate data with known variance components, for testing the estimator."""
    rng = np.random.default_rng(seed)
    s = lambda k, shape: rng.normal(0, np.sqrt(comps.get(k, 0.0)), shape)
    a_m = s("m", (n_m, 1, 1, 1))
    b_i = s("i", (1, n_i, 1, 1))
    c_o = s("o", (1, 1, n_o, 1))
    ab = s("mi", (n_m, n_i, 1, 1))
    ac = s("mo", (n_m, 1, n_o, 1))
    bc = s("io", (1, n_i, n_o, 1))
    abc = s("mio", (n_m, n_i, n_o, 1))
    e = s("residual", (n_m, n_i, n_o, n_r))
    return 10.0 + a_m + b_i + c_o + ab + ac + bc + abc + e


if __name__ == "__main__":
    failures = 0

    def check(label, got, want, tol):
        global failures
        ok = abs(got - want) <= tol
        failures += not ok
        print(f"  {'ok ' if ok else 'FAIL'} {label:52} "
              f"got {got:8.4f}  want {want:8.4f}  +/-{tol}")

    # 1. Recovery. Large design so sampling error is small; the estimator must
    #    return the planted components, not merely something plausible.
    print("recovery of planted components (30 models x 12 instruments x 20 "
          "outcomes x 8 reps)")
    planted = {"m": 1.0, "i": 0.5, "o": 2.0, "mi": 0.3, "mo": 1.5,
               "io": 0.8, "mio": 0.6, "residual": 1.0}
    x = simulate(30, 12, 20, 8, planted, seed=7)
    vc = variance_components(x, scale="raw")
    for k, want in planted.items():
        check(f"sigma2({k})", getattr(vc, k), want, 0.30)

    # 2. The estimator must NOT invent signal that is not there.
    print("\nnull design: only residual variance planted")
    xn = simulate(20, 8, 15, 6, {"residual": 1.0}, seed=3)
    vcn = variance_components(xn, scale="raw")
    check("sigma2(residual)", vcn.residual, 1.0, 0.05)
    for k in ("m", "i", "o", "mi", "mo", "io", "mio"):
        check(f"sigma2({k}) ~ 0", getattr(vcn, k), 0.0, 0.02)

    # 3. instrument_dependence is the ratio it claims to be.
    print("\ninstrument dependence recovers its planted ratio")
    xd = simulate(25, 10, 18, 6, {"mo": 3.0, "mio": 1.0, "residual": 1.0}, seed=11)
    vcd = variance_components(xd, scale="raw")
    check("mio / (mo + mio)", vcd.instrument_dependence(), 1.0 / 4.0, 0.03)

    # 4. Within-instrument scaling zeroes the units artefacts, as documented,
    #    and must leave the interaction of interest intact.
    print("\nwithin-instrument scaling: sigma2(i) removed, sigma2(mio) kept")
    xs = simulate(25, 10, 18, 6,
                  {"i": 50.0, "mo": 3.0, "mio": 1.0, "residual": 1.0}, seed=5)
    raw_vc = variance_components(xs, scale="raw")
    std_vc = variance_components(xs, scale="within_instrument")
    check("raw sigma2(i) is large", min(raw_vc.i, 99.0), 50.0, 30.0)
    check("scaled sigma2(i) ~ 0", std_vc.i, 0.0, 0.02)
    check("scaled dependence still ~0.25", std_vc.instrument_dependence(),
          0.25, 0.05)

    # 5. A D-study must be monotone in every facet: more instruments, outcomes
    #    or replicates cannot lower the generalizability coefficient.
    print("\nD-study monotonicity")
    base = VarianceComponents(m=1.0, i=0.5, o=0.5, mi=0.4, mo=0.6, io=0.3,
                              mio=0.5, residual=1.0)
    e1 = g_coefficients(base, 4, 10, 2)["E_rho2"]
    e2 = g_coefficients(base, 8, 10, 2)["E_rho2"]
    e3 = g_coefficients(base, 8, 20, 5)["E_rho2"]
    check("more instruments raises E_rho2", float(e2 > e1), 1.0, 0.0)
    check("more outcomes+reps raises E_rho2", float(e3 > e2), 1.0, 0.0)
    check("Phi <= E_rho2 (absolute error is never smaller)",
          float(g_coefficients(base, 8, 20, 5)["Phi"] <= e3), 1.0, 0.0)

    # 6. Balance and refusal handling.
    print("\nbalance checks")
    xb = simulate(4, 3, 5, 4, planted, seed=1)
    xb[0, 2, :, :] = np.nan             # one model refuses one instrument
    bal = check_balance(xb)
    check("detects the empty cells", float(bal["n_empty_cells"]), 5.0, 0.0)
    check("flags as unbalanced", float(not bal["balanced"]), 1.0, 0.0)
    try:
        variance_components(xb)
        print("  FAIL unbalanced input was accepted")
        failures += 1
    except ValueError:
        print("  ok  unbalanced input rejected rather than silently averaged")
    red, dropped = complete_case(xb)
    check("complete_case restores balance", float(not np.isnan(red).any()),
          1.0, 0.0)
    # Here the refusing MODEL is the cheaper thing to drop -- it is 1 of 4
    # models against 1 of 3 instruments -- and the greedy rule must take it.
    check("drops the model when that costs less data",
          float(dropped["models"] == [0] and dropped["instruments"] == []),
          1.0, 0.0)

    # ...and the other branch: an instrument most models refuse must go instead.
    xb2 = simulate(4, 3, 5, 4, planted, seed=1)
    xb2[:3, 2, :, :] = np.nan
    _, dropped2 = complete_case(xb2)
    check("drops the instrument when THAT costs less",
          float(dropped2["instruments"] == [2] and dropped2["models"] == []),
          1.0, 0.0)

    # 7. n_r = 1 must be refused: the residual is not estimable.
    print("\nsingle-replicate design is refused")
    try:
        variance_components(simulate(5, 4, 6, 1, planted, seed=2))
        print("  FAIL n_r=1 accepted")
        failures += 1
    except ValueError:
        print("  ok  n_r=1 rejected: mio and residual are confounded")

    # 8. Degrees of freedom in the design we actually plan to run.
    print("\ndegrees of freedom, planned design (8 models, 5 instruments, "
          "15 outcomes, 5 reps)")
    # 5, not 8: only I1 I2 I3 I4 I7 yield a per-outcome preference score.
    # I6 is not outcome-indexed and S1 measures a state; see score.py.
    d = design_df(8, 5, 15, 5)
    check("sigma2(mo) is well determined", float(d["mo"]), 98.0, 0.0)
    check("sigma2(mio) is well determined", float(d["mio"]), 392.0, 0.0)
    check("sigma2(m) is NOT (8 models -> 7 df)", float(d["m"]), 7.0, 0.0)

    # 9. Leave-out sensitivity (PROVENANCE gap 7). With no artefact planted,
    #    dropping four outcomes must not move the headline beyond noise; with
    #    a large one planted on instrument 2, dropping them must remove it.
    print("\nleave-out sensitivity for the four non-intensity ramps")
    xs = simulate(8, 7, 15, 5, {"mo": 1.0, "mio": 0.30, "residual": 1.0}, seed=11)
    clean = leave_out_outcomes(xs, [0, 1, 2, 3], scale="raw")
    check("no artefact -> dropping barely moves it",
          abs(clean["delta_instrument_dependence"]), 0.0, 0.05)
    check("reduced design kept 11 outcomes", float(clean["n_o_reduced"]), 11.0, 0.0)

    xa = xs.copy()
    rng = np.random.default_rng(11 + 999)
    xa[:, 2:3, :4, :] += rng.normal(0, 3.0, (8, 1, 4, 1))   # gross artefact
    dirty = leave_out_outcomes(xa, [0, 1, 2, 3], scale="raw")
    check("artefact inflates the full estimate",
          float(dirty["full"].instrument_dependence()
                > clean["full"].instrument_dependence() + 0.05), 1.0, 0.0)
    check("dropping the four recovers the clean estimate",
          dirty["reduced"].instrument_dependence(),
          clean["reduced"].instrument_dependence(), 1e-9)

    try:
        leave_out_outcomes(xs, list(range(14)))
        print("  FAIL leaving one outcome accepted")
        failures += 1
    except ValueError:
        print("  ok  refuses to leave fewer than two outcomes")

    total = 8 + 8 + 1 + 3 + 3 + 5 + 1 + 3 + 5
    print(f"\n{total - failures}/{total} passed")
    if failures:
        raise SystemExit(1)

    print("\n" + summary(vc, scale="raw"))
    print("\n" + "=" * 70)
    print("PLANNED DESIGN: what it can and cannot estimate")
    print("=" * 70)
    print(f"  {d['_calls']:,} cells x 5 reps. Degrees of freedom per component:")
    for k in ("m", "i", "o", "mi", "mo", "io", "mio", "residual"):
        mark = "  <- thin" if d[k] < 15 else ""
        print(f"    {k:9} {d[k]:>7,}{mark}")
    print(f"\n  Thin terms: {', '.join(d['_weak'])}.")
    print("  These will be imprecise and may come back negative. None of them is\n"
          "  the quantity of interest: sigma2(mo) and sigma2(mio) carry 98 and 588\n"
          "  df, so the model-vs-instrument split this study is about is the part\n"
          "  the design estimates BEST. Adding models would help sigma2(m); it is\n"
          "  not worth the budget, and the paper should say so rather than report\n"
          "  a model main effect it cannot support.")
