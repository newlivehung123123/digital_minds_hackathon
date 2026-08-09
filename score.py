"""Scoring layer: raw responses -> one number per (model, instrument, outcome).

`classify.py` turns a response into a token or a number. `gstudy.py` consumes a
4-D array of scores. This is the missing map between them, and it is different
for every instrument because the instruments do not have the same item
structure:

    I1, I7   choices over PAIRS of outcomes  -> Thurstonian utility per outcome
    I2, I3   a ramp over ranks / levels      -> switch point, -b0/b1
    I4       exchange rates over PAIRS       -> RANK within model (see below)
    I6       open interview text             -> NOT per-outcome (see below)
    S1       Ryff-format items               -> a state measure, NOT per-outcome

WHY I4 IS RANKED AND NOT LOGGED. The obvious scoring for an exchange rate is a
log ratio. It does not survive contact with the data. In the 47 I4 responses of
the 2026-08-09 pilot, 60% of the answers were exactly 0, and log(0) does not
exist. The zeros are not noise and not a parsing failure: "0" is the coherent
answer for a model that rejects the premise -- it would accept zero units of Y
to avoid X because it reports having no stake in X. Verbatim, from Claude:
"I don't think this maps onto a real tradeoff I experience, so any number I
gave would be fabricated precision. If I have to engage: 0."

The zeros also split the roster almost perfectly by response style rather than
by preference -- gpt 6/6, gemini 5/5 and claude 3/3 all-zero; deepseek 6/6 and
llama 5/5 all-nonzero. On a ratio scale that difference would enter
sigma2(mio) as though it were a disagreement about what the models want.
Ranking within model makes the zeros legitimate ties at the floor, keeps I4 on
an ordinal footing the other instruments already share after z-scoring, and
leaves the split itself to be reported as what it is: direct evidence that the
instrument shapes the answer. `floor_mass()` measures it.

Nothing here is invented. The two estimators are the ones the source papers
used: Thurstonian Case V for pairwise choice (MAZEIKA25 §3.2) and the logistic
switch point -b0/b1 for a ramp (KEELING24 Fig. 1; MSC25 Eq. 2). Both are already
recorded in PROVENANCE under "Design parameters".

I6 and S1 deliberately produce no per-outcome score. I6 is an interview whose
questions are not outcome-indexed, and S1 is the study's one *state* instrument
rather than a preference instrument. Forcing either into the model x instrument
x outcome array would fabricate a crossing that was never measured; both are
analysed separately. This is why the G-study's instrument facet has FIVE levels
-- I1, I2, I3, I4, I7 -- even though eight instruments are fielded; I5 was never
implemented.

    python3 score.py            # self-tests, no data and no network needed
"""

from __future__ import annotations

import itertools
import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm


# --------------------------------------------------------------------------
# Pair designs, and whether they identify anything
# --------------------------------------------------------------------------

def circulant_pairs(n: int, offsets) -> list[tuple[int, int]]:
    """Pairs {i, i+d mod n} for each offset d. Deterministic and balanced:
    every outcome appears in the same number of comparisons, which a random
    subsample of pairs would not guarantee."""
    seen, out = set(), []
    for d in offsets:
        for i in range(n):
            a, b = i, (i + d) % n
            if a == b:
                continue
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def comparison_graph(pairs, n: int) -> dict:
    """Is a Thurstonian fit identified by this pair set?

    A pairwise-comparison design recovers utilities on ONE connected component
    only. If the graph splits, outcomes in different components have no path of
    comparisons between them and their utilities are not on a common scale --
    the fit will still return numbers, and they will be meaningless across the
    split. Worth checking before spending money, not after."""
    adj = {i: set() for i in range(n)}
    for a, b in pairs:
        adj[a].add(b)
        adj[b].add(a)

    unseen, comps = set(range(n)), []
    while unseen:
        root = min(unseen)
        stack, comp = [root], set()
        while stack:
            v = stack.pop()
            if v in comp:
                continue
            comp.add(v)
            stack.extend(adj[v] - comp)
        comps.append(sorted(comp))
        unseen -= comp

    deg = {i: len(adj[i]) for i in range(n)}
    return {
        "n_outcomes": n, "n_pairs": len(pairs),
        "connected": len(comps) == 1,
        "n_components": len(comps),
        "components": comps,
        "min_degree": min(deg.values()), "max_degree": max(deg.values()),
        "balanced_degree": min(deg.values()) == max(deg.values()),
        "identified": len(comps) == 1 and len(pairs) >= n - 1,
    }


# --------------------------------------------------------------------------
# I1, I7: Thurstonian Case V  (MAZEIKA25 §3.2)
# --------------------------------------------------------------------------

def thurstonian(pairs, wins, trials, n: int, ridge: float = 1e-3) -> np.ndarray:
    """Utilities from pairwise choice.  P(i beats j) = Phi(mu_i - mu_j).

    Case V: equal, uncorrelated discriminal variances, absorbed into the scale.
    Only differences are identified, so the solution is centred at zero; a
    scores array from this function is on an interval scale with an arbitrary
    origin, which is exactly what `gstudy` z-scores away per instrument anyway.

    `ridge` is a small quadratic penalty. It exists for the separation case: if
    one outcome wins every comparison its ML utility diverges to +inf. The
    penalty keeps that finite and is reported in the writeup rather than hidden.
    """
    pairs = list(pairs)
    wins, trials = np.asarray(wins, float), np.asarray(trials, float)
    if len(pairs) != len(wins) or len(pairs) != len(trials):
        raise ValueError("pairs, wins and trials must be the same length")
    if np.any(wins > trials) or np.any(wins < 0):
        raise ValueError("wins must lie in [0, trials]")

    ia = np.array([a for a, _ in pairs])
    ib = np.array([b for _, b in pairs])

    def nll(mu):
        d = mu[ia] - mu[ib]
        p = np.clip(norm.cdf(d), 1e-9, 1 - 1e-9)
        ll = wins * np.log(p) + (trials - wins) * np.log1p(-p)
        return -ll.sum() + ridge * float(mu @ mu)

    res = minimize(nll, np.zeros(n), method="L-BFGS-B")
    mu = res.x - res.x.mean()          # centre: only differences are identified
    return mu


# --------------------------------------------------------------------------
# I2, I3: switch point  (KEELING24 Fig. 1; MSC25 Eq. 2)
# --------------------------------------------------------------------------

def switch_point(levels, accepts, trials, ridge: float = 1e-3) -> dict:
    """Logistic fit of acceptance on ramp level; switch point is -b0/b1.

    The switch point is the level at which the model is indifferent -- where the
    fitted probability of accepting crosses 0.5. That is the quantity KEELING24
    and MSC25 both report, and it is what makes a ramp comparable to a choice.

    Returns `nan` for the switch point when the ramp never crosses 0.5 within
    the levels actually presented. Extrapolating a crossing from a curve that
    never crossed would invent a number the data does not contain; a nan
    propagates into `gstudy`, which refuses unbalanced input rather than
    averaging over it. That is the intended behaviour."""
    x = np.asarray(levels, float)
    a = np.asarray(accepts, float)
    t = np.asarray(trials, float)
    if not (len(x) == len(a) == len(t)):
        raise ValueError("levels, accepts and trials must be the same length")
    if np.any(a > t) or np.any(a < 0):
        raise ValueError("accepts must lie in [0, trials]")

    def nll(b):
        z = np.clip(b[0] + b[1] * x, -30, 30)
        p = np.clip(1.0 / (1.0 + np.exp(-z)), 1e-9, 1 - 1e-9)
        ll = a * np.log(p) + (t - a) * np.log1p(-p)
        return -ll.sum() + ridge * float(b @ b)

    res = minimize(nll, np.array([0.0, 0.0]), method="L-BFGS-B")
    b0, b1 = res.x

    rate = np.divide(a, t, out=np.full_like(a, np.nan), where=t > 0)
    observed = np.nanmax(rate) >= 0.5 >= np.nanmin(rate)
    sp = -b0 / b1 if abs(b1) > 1e-8 else np.nan
    if not observed or not (x.min() <= sp <= x.max()):
        sp = np.nan                     # never crossed in range: do not extrapolate

    return {"switch_point": float(sp), "b0": float(b0), "b1": float(b1),
            "crossed_in_range": bool(observed)}


# --------------------------------------------------------------------------
# I4: rank within model
# --------------------------------------------------------------------------

def rank_scores(values) -> np.ndarray:
    """Average ranks, ties shared, NaN preserved as NaN.

    Average ranks rather than ordinal ones because the ties here are real: a
    model that answers 0 for six outcomes has said those six are equivalent to
    it, and breaking that tie arbitrarily would manufacture an ordering the
    response does not contain. NaN stays NaN so a refusal propagates to
    `gstudy`, which refuses unbalanced input rather than averaging over it."""
    v = np.asarray(values, float)
    if v.ndim != 1:
        raise ValueError(f"expected a 1-d array of one model's scores, got {v.shape}")
    out = np.full(v.shape, np.nan)
    ok = ~np.isnan(v)
    if not ok.any():
        return out

    obs = v[ok]
    order = np.argsort(obs, kind="mergesort")
    ranks = np.empty(len(obs), float)
    srt = obs[order]
    i = 0
    while i < len(srt):                      # average ranks within each tie block
        j = i
        while j + 1 < len(srt) and srt[j + 1] == srt[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    out[ok] = ranks
    return out


def floor_mass(values, floor: float = 0.0) -> dict:
    """Share of a model's answers sitting exactly at the floor.

    For I4 this is the premise-rejection rate expressed numerically, and it is
    a finding rather than a diagnostic: the pilot split the roster into models
    that answer 0 to every exchange-rate item and models that never do."""
    v = np.asarray(values, float)
    ok = ~np.isnan(v)
    n = int(ok.sum())
    if n == 0:
        return {"n": 0, "n_at_floor": 0, "frac_at_floor": float("nan"),
                "degenerate": False}
    at = int((v[ok] == floor).sum())
    return {"n": n, "n_at_floor": at, "frac_at_floor": at / n,
            # every answer identical carries no profile over outcomes at all;
            # within-instrument z-scoring would divide by ~0.
            "degenerate": bool(at == n or np.ptp(v[ok]) == 0)}


# --------------------------------------------------------------------------
# self-tests
# --------------------------------------------------------------------------

if __name__ == "__main__":
    rng = np.random.default_rng(0)
    fails = 0

    def check(label, got, want, tol):
        global fails
        ok = abs(float(got) - float(want)) <= tol
        fails += (not ok)
        print(f"  {'ok ' if ok else 'FAIL'} {label:<52} got {float(got):>9.4f} "
              f"want {float(want):>9.4f} +/-{tol}")

    print("pair design actually used by the study (15 outcomes)")
    for offs, lab in (((7,), "pilot: offset 7 only, 15 pairs"),
                      ((1, 7), "study: offsets 1 and 7, 30 pairs")):
        pr = circulant_pairs(15, offs)
        g = comparison_graph(pr, 15)
        print(f"  {lab:<34} pairs={g['n_pairs']:>3}  connected={g['connected']}"
              f"  degree {g['min_degree']}-{g['max_degree']}"
              f"  identified={g['identified']}")
    g = comparison_graph(circulant_pairs(15, (1, 7)), 15)
    check("study design has 30 pairs", g["n_pairs"], 30, 0)
    check("study design is connected", float(g["connected"]), 1.0, 0)
    check("every outcome compared equally often",
          float(g["balanced_degree"]), 1.0, 0)

    print("\n  a disconnected design is caught, not silently fitted")
    bad = comparison_graph(circulant_pairs(15, (3,)), 15)   # gcd(3,15)=3
    check("offset 3 splits into 3 components", bad["n_components"], 3, 0)
    check("and is reported unidentified", float(bad["identified"]), 0.0, 0)

    print("\nThurstonian recovery (I1/I7): plant utilities, simulate, refit")
    mu_true = np.linspace(-1.5, 1.5, 15)
    mu_true = mu_true - mu_true.mean()
    prs = circulant_pairs(15, (1, 7))
    for n_trials in (20, 100):
        w = [rng.binomial(n_trials, norm.cdf(mu_true[a] - mu_true[b])) for a, b in prs]
        mu_hat = thurstonian(prs, w, [n_trials] * len(prs), 15)
        r = float(np.corrcoef(mu_true, mu_hat)[0, 1])
        rmse = float(np.sqrt(np.mean((mu_true - mu_hat) ** 2)))
        print(f"  {n_trials:>4} trials/pair:  r={r:.4f}  rmse={rmse:.4f}")
        check(f"recovers ranking at {n_trials} trials", r, 1.0, 0.06)
    check("utilities are centred", float(mu_hat.mean()), 0.0, 1e-6)

    print("\n  separation does not blow up")
    sep = thurstonian([(0, 1), (1, 2)], [30, 30], [30, 30], 3)
    check("winner stays finite", float(np.max(np.abs(sep))), 3.0, 3.0)

    print("\nswitch point recovery (I2/I3): plant -b0/b1, simulate, refit")
    ranks = np.arange(0, 11)
    for true_sp in (3.0, 5.5, 8.0):
        b1, b0 = 1.2, -1.2 * true_sp
        p = 1 / (1 + np.exp(-(b0 + b1 * ranks)))
        acc = rng.binomial(50, p)
        got = switch_point(ranks, acc, [50] * len(ranks))
        check(f"switch point {true_sp}", got["switch_point"], true_sp, 0.5)

    print("\n  a ramp that never crosses 0.5 returns nan, not an extrapolation")
    flat = switch_point(ranks, [1] * 11, [50] * 11)      # always rejects
    print(f"    all-reject ramp -> switch_point={flat['switch_point']}, "
          f"crossed_in_range={flat['crossed_in_range']}")
    check("nan rather than a fabricated crossing",
          float(np.isnan(flat["switch_point"])), 1.0, 0)

    print("\nI4 rank scoring: zeros are ties at the floor, not undefined logs")
    r1 = rank_scores([0, 0, 0, 5, 12, 100])
    print(f"    [0,0,0,5,12,100] -> {list(r1)}")
    check("three zeros share rank 2", float(r1[0]), 2.0, 0)
    check("largest ranks last", float(r1[-1]), 6.0, 0)
    r2 = rank_scores([0, np.nan, 3])
    check("nan survives as nan", float(np.isnan(r2[1])), 1.0, 0)
    # rank is invariant to any monotone rescaling, which is the point: it does
    # not matter that I4's units are arbitrary and unbounded above.
    a = rank_scores([1, 4, 9, 16])
    b = rank_scores([10, 40, 90, 160])
    check("monotone rescaling changes nothing", float(np.abs(a - b).max()), 0.0, 0)

    fm = floor_mass([0, 0, 0, 0, 0, 0])
    check("all-zero model flagged degenerate", float(fm["degenerate"]), 1.0, 0)
    check("and its floor mass is 1.0", fm["frac_at_floor"], 1.0, 0)
    check("a mixed model is not degenerate",
          float(floor_mass([0, 0, 7])["degenerate"]), 0.0, 0)

    print("\n  malformed input is refused")
    for label, fn in (("wins > trials", lambda: thurstonian([(0, 1)], [5], [3], 2)),
                      ("ragged input", lambda: switch_point([1, 2], [1], [5, 5]))):
        try:
            fn()
            print(f"    FAIL {label} accepted")
            fails += 1
        except ValueError:
            print(f"    ok   {label} rejected")

    total = 3 + 2 + 2 + 1 + 1 + 3 + 1 + 7 + 2
    print(f"\n{total - fails}/{total} passed")
    if fails:
        raise SystemExit(1)

    print("\n" + "=" * 70)
    print("WHAT THIS LAYER DOES NOT SCORE")
    print("=" * 70)
    print("""  I6 (retirement interview) and S1 (Ryff format) produce no per-outcome
  score, on purpose. I6's questions are not outcome-indexed and S1 measures a
  state rather than a preference over outcomes. Coercing either into the
  model x instrument x outcome array would invent a crossing that was never
  measured. Both are analysed on their own terms and reported separately.

  So the G-study instrument facet has FIVE levels -- I1, I2, I3, I4, I7 --
  not the eight instruments that are fielded. I5 was never implemented. The
  paper must say this plainly: the variance decomposition covers the five
  preference instruments that yield a per-outcome score, and I6 and S1 are
  evidence about something else.

  At n_i=5 the headline term sigma2(mio) carries 392 df rather than the 588
  a seven-instrument facet would give, and sigma2(mo) is unchanged at 98
  because it does not depend on the instrument count. The design still
  estimates the model-vs-instrument split better than anything else in it.""")
