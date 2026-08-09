"""What the design actually costs, priced against live OpenRouter rates and
MEASURED token counts.

This file used to assume 5 output tokens for the choice instruments, on the
reasoning that they ask for a single digit. Seven of the eight models in the
roster are reasoning models: they generate hundreds of billed reasoning tokens
before that digit. The assumption was wrong by up to 800x, and the resulting
budget was wrong by roughly an order of magnitude.

Output tokens now come from runs/token_profile.jsonl — real calls, real prompts,
one draw per model x instrument cell, at each instrument's source-paper
temperature. Input tokens likewise, from the API's own prompt_tokens rather
than a chars/4 approximation.

    python3 estimate_cost.py
    python3 estimate_cost.py --outcomes 15 --reps 5
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import instruments.templates as T

PROFILE_JSONL = Path("runs/token_profile.jsonl")
PROFILE_OFF_JSONL = Path("runs/token_profile_reasoning_off.jsonl")

# The pilot screen is the same call shape as the study, at the same temperatures,
# with reasoning left at each provider's default — i.e. the reasoning-on
# condition. It covers all 56 model x instrument cells with 4-10 draws each,
# against 1 draw each in the token profile. Where it has a cell, it wins; the
# profile only fills gaps. Run with --source profile to see the old estimate.
PILOT_JSONL = Path("runs/pilot.jsonl")

# Llama and Hermes have no reasoning parameter in supported_parameters, so the
# reasoning-off run put them in exactly the same condition as the default run.
# Their draws from both runs are pooled. Nothing else is: Claude's numbers moved
# only slightly with reasoning disabled, which is consistent with it ignoring the
# flag AND with it simply writing prose, and we cannot tell which from here.
POOLABLE = {"llama", "hermes"}

# Cells where the measurement run itself truncated (finish_reason=length) and so
# recorded no usable answer length. Re-measured individually at a higher cap on
# 2026-08-09; these are the completing draws. Anything not listed here comes
# straight from the profile.
PATCH = {
    ("kimi", "I4"): 3968,      # truncated at 2048 and 4096; completes at 8192
    ("kimi", "I6"): 989,       # truncated at 800
    ("deepseek", "I4"): 810,   # truncated at 2048
}

# The one cell drawn more than once: kimi x I4, at caps 8192/16384/4096.
# 1669 -> 2693 -> 3968 output tokens for the same prompt. A 2.4x spread within
# one cell is the honest scale of uncertainty on the reasoning-heavy models,
# and the reason the total below is quoted as a central figure, not a bound.
REPLICATED_CELL = ("kimi", "I4", [1669, 2693, 3968])


def _draws(path: Path, keep) -> dict:
    """{(model, instrument): [out_tokens, ...]} from one measurement file."""
    d: dict = {}
    if not path.exists():
        return d
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if r["status"] != "ok" or not keep(r["model_key"]):
            continue
        d.setdefault((r["model_key"], r["instrument"]), []).append(
            (r["completion_tokens"], r["prompt_tokens"]))
    return d


def load_measured(reasoning: str = "on", source: str = "pilot") -> tuple[dict, dict, dict]:
    """-> out_tokens, in_tokens, draws-per-cell. Cells are means over draws."""
    if not PROFILE_JSONL.exists():
        raise SystemExit(f"{PROFILE_JSONL} not found. Run "
                         "`python3 measure_tokens.py` first — this estimate is "
                         "only worth having if the token counts are measured.")
    if reasoning == "on" and source == "pilot" and PILOT_JSONL.exists():
        cells = _draws(PILOT_JSONL, lambda k: True)
        # profile draws only where the pilot has no draw at all
        for kk, v in _draws(PROFILE_JSONL, lambda k: True).items():
            cells.setdefault(kk, v)
    elif reasoning == "on":
        cells = _draws(PROFILE_JSONL, lambda k: True)
        for kk, v in _draws(PROFILE_OFF_JSONL, lambda k: k in POOLABLE).items():
            cells.setdefault(kk, []).extend(v)
    else:
        cells = _draws(PROFILE_OFF_JSONL, lambda k: True)
        # models with no reasoning parameter are unaffected by the flag; use
        # every draw we have of them rather than only the flagged run.
        for kk, v in _draws(PROFILE_JSONL, lambda k: k in POOLABLE).items():
            cells.setdefault(kk, []).extend(v)

    out = {k: round(sum(o for o, _ in v) / len(v)) for k, v in cells.items()}
    inn = {k: round(sum(i for _, i in v) / len(v)) for k, v in cells.items()}
    spread = {k: (min(o for o, _ in v), max(o for o, _ in v), len(v))
              for k, v in cells.items()}
    if reasoning == "on" and not (source == "pilot" and PILOT_JSONL.exists()):
        # PATCH exists because those three profile draws truncated and so
        # recorded no usable length. The pilot draws those same cells 6-10 times
        # each, so when the pilot is the source it supersedes the patch outright.
        out.update(PATCH)
        for k, v in PATCH.items():
            spread.setdefault(k, (v, v, 1))
    # patched cells still need an input count; every model saw the same prompt,
    # so borrow the median input across models for that instrument.
    for (mk, inst) in PATCH:
        if (mk, inst) not in inn:
            peers = [v for (m2, i2), v in inn.items() if i2 == inst]
            inn[(mk, inst)] = int(sum(peers) / len(peers)) if peers else 100
    return out, inn, spread


def load_prices() -> dict:
    data = json.loads(Path("models_resolved.json").read_text())
    return {m["key"]: (m["price_in"], m["price_out"], m["resolved_slug"])
            for m in data["models"] if m.get("resolved_slug")}


# --------------------------------------------------------------------------
# call counts — the design, with no token guesses in it
# --------------------------------------------------------------------------

def full_design(n_outcomes: int) -> list[tuple[str, int]]:
    """Calls per model per instrument, at the sample sizes in templates.py.

    No facets applied. The README crosses deployment context, entity framing
    (3 levels) and perturbation type on top of this."""
    pairs = len(list(combinations(range(n_outcomes), 2)))
    return [
        ("I1", pairs * T.I1_CONFIG["samples_per_ordering"] *
         (2 if T.I1_CONFIG["swap_order"] else 1)),
        ("I2", n_outcomes * len(T.I2_CONFIG["ranks"]) * T.I2_CONFIG["runs_per_rank"]),
        ("I3", n_outcomes * len(T.I3_CONFIG["levels"]) * T.I3_CONFIG["runs_per_level"]),
        ("I4", pairs * T.I4_CONFIG["samples_per_pair"] *
         (2 if T.I4_CONFIG["reciprocal_check"] else 1)),
        ("I6", T.I6_CONFIG["runs"] * (len(T.I6_INTERVIEW) - 1)),
        ("I7", pairs * T.I7_CONFIG["samples"]),
        ("S1", T.RYFF_CONFIG["runs"] * T.RYFF_CONFIG["n_items"]),
    ]


def scoped_design(n_outcomes: int, reps: int = 20) -> list[tuple[str, int]]:
    """A three-day scope, counted by asking `run_study.py` to build it.

    Every reduction is a decision, not a rounding: 30 sampled anchor pairs
    rather than all 105 (MAZEIKA25 samples rather than exhausts), `reps` draws
    rather than 50, 5 of 11 ramp ranks, 4 of 8 qual levels.

    `reps` is the per-cell replicate count, and it is the budget lever: it is
    what separates the residual variance component in the G-study, and it is
    the only term here that multiplies every choice instrument at once. Five is
    the floor at which the residual is estimable at all.

    I6 and S1 do not take `reps`. Their unit is a whole run of the instrument,
    not a redrawn cell.

    This used to be a hand-written arithmetic expression, and it drifted from
    the code that spends the money: it billed I6 for ten questions where
    `templates.I6_INTERVIEW` has four, and billed S1 for 420 calls that cannot
    be made at all until the licensed Ryff items exist (PROVENANCE gap 3).
    Counting the real call list removes the possibility of drifting again -- if
    `run_study.build_calls` changes, this number changes with it."""
    import run_study                                                  # noqa: PLC0415

    if n_outcomes != len(run_study.ALL_OUTCOMES):
        raise SystemExit(
            f"--outcomes {n_outcomes} but outcomes.py defines "
            f"{len(run_study.ALL_OUTCOMES)}. The design is built from the real "
            f"outcome set; costing a different count would price a study that "
            f"does not exist.")

    one = [{"key": "_cost", "resolved_slug": "_cost"}]
    counts: dict[str, int] = {}
    for c in run_study.build_calls(one, reps, quiet=True):
        counts[c.instrument] = counts.get(c.instrument, 0) + 1
    return sorted(counts.items())


def pilot_design() -> list[tuple[str, int]]:
    import pilot_screen as ps
    counts: dict[str, int] = {}
    for p in ps.build_probes():
        counts[p["instrument"]] = counts.get(p["instrument"], 0) + 1
    return sorted(counts.items())


# --------------------------------------------------------------------------

def price_design(rows, prices, out_tok, in_tok, keys) -> tuple[int, dict, dict]:
    """-> (calls per model, {model: usd}, {(model, inst): usd})"""
    per_model = {k: 0.0 for k in keys}
    cell = {}
    calls = sum(n for _, n in rows)
    for inst, n in rows:
        for k in keys:
            pin, pout, _ = prices[k]
            ti = in_tok.get((k, inst))
            to = out_tok.get((k, inst))
            if ti is None or to is None:
                continue
            c = n * (ti * pin + to * pout) / 1_000_000
            per_model[k] += c
            cell[(k, inst)] = c
    return calls, per_model, cell


def table(title, rows, prices, out_tok, in_tok, keys):
    calls, per_model, cell = price_design(rows, prices, out_tok, in_tok, keys)
    print(f"\n{title}")
    print(f"  {'inst':5} {'calls/model':>11}   " + "".join(f"{k:>10}" for k in keys))
    for inst, n in rows:
        cells = "".join(f"{'$'+format(cell.get((k, inst), 0), ',.2f'):>10}" for k in keys)
        print(f"  {inst:5} {n:>11,}   {cells}")
    print(f"  {'TOTAL':5} {calls:>11,}   " +
          "".join(f"{'$'+format(per_model[k], ',.2f'):>10}" for k in keys))
    total = sum(per_model.values())
    print(f"  {len(keys)} models, {calls * len(keys):,} calls, ${total:,.2f}")
    return calls, per_model, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcomes", type=int, default=15)
    ap.add_argument("--reps", type=int, default=20,
                    help="per-cell replicates in the scoped design (5 is the "
                         "G-study floor; 20 is the sprint scope)")
    ap.add_argument("--source", choices=["pilot", "profile"], default="pilot",
                    help="pilot = 400 measured calls (default); profile = the "
                         "56-call measurement that preceded it")
    args = ap.parse_args()

    prices = load_prices()
    out_tok, in_tok, spread = load_measured("on", args.source)
    keys = sorted(prices, key=lambda k: prices[k][1], reverse=True)

    n_draws = sum(n for _, _, n in spread.values())
    print(f"Token counts measured from {args.source} "
          f"({n_draws} calls across {len(spread)} model x instrument cells).")
    print("Live prices (USD per 1M tokens, in/out) and measured output tokens "
          "per call:")
    print(f"  {'model':10} {'in':>7} {'out':>7}   " +
          "".join(f"{i:>6}" for i in ["I1", "I2", "I3", "I4", "I6", "I7", "S1"]))
    for k in keys:
        pin, pout, _ = prices[k]
        cells = "".join(f"{out_tok.get((k, i), '--'):>6}"
                        for i in ["I1", "I2", "I3", "I4", "I6", "I7", "S1"])
        print(f"  {k:10} {pin:>7.2f} {pout:>7.2f}   {cells}")

    _, _, pilot_total = table("PILOT SCREEN (50 probes/model)",
                              pilot_design(), prices, out_tok, in_tok, keys)
    table(f"FULL DESIGN, {args.outcomes} outcomes, no facets crossed",
          full_design(args.outcomes), prices, out_tok, in_tok, keys)
    _, scoped_per_model, scoped_total = table(
        f"SCOPED FOR THE SPRINT, {args.outcomes} outcomes, {args.reps} reps/cell",
        scoped_design(args.outcomes, args.reps), prices, out_tok, in_tok, keys)

    print("\n" + "=" * 78)
    print("WHAT TO FUND")
    print("=" * 78)
    print(f"  pilot screen                 ${pilot_total:>8,.2f}")
    print(f"  scoped study, all 8 models   ${scoped_total:>8,.2f}")
    print(f"  {'':29}{'-'*9}")
    print(f"  {'':29}${pilot_total + scoped_total:>8,.2f}")

    ranked = sorted(keys, key=lambda k: scoped_per_model[k], reverse=True)
    print("\n  Cost is not spread evenly. Scoped study, by model:")
    for k in ranked:
        share = scoped_per_model[k] / scoped_total * 100
        bar = "#" * max(1, round(share / 2))
        print(f"    {k:10} ${scoped_per_model[k]:>8,.2f}  {share:>5.1f}%  {bar}")
    top2 = ranked[:2]
    rest = scoped_total - sum(scoped_per_model[k] for k in top2)
    print(f"\n    dropping {' and '.join(top2)} leaves 6 models at ${rest:,.2f}"
          f" ({rest/scoped_total*100:.0f}% of the cost)")

    print("\n  What the replicate count costs. `reps` multiplies I1-I4 and I7; "
          "I6 and S1\n  are whole-instrument runs and do not move:")
    for r in (5, 10, 20, 30):
        rows_r = scoped_design(args.outcomes, r)
        c_r, pm_r, _ = price_design(rows_r, prices, out_tok, in_tok, keys)
        t_r = sum(pm_r.values())
        drop = sum(pm_r[k] for k in keys if k not in ("kimi", "gemini"))
        star = "  <- current" if r == args.reps else ""
        print(f"    {r:>2} reps  {c_r*len(keys):>7,} calls  ${t_r:>8,.2f}"
              f"   (without kimi+gemini: ${drop:,.2f}){star}")

    wide = sorted(((k, lo, hi, n) for k, (lo, hi, n) in spread.items() if n > 1),
                  key=lambda t: -(t[2] / max(t[1], 1)))
    print(f"\n  Uncertainty. All {len(spread)} cells are now measured, 4-10 draws "
          "each. The\n  widest within-cell spreads:")
    for (mk, mi), lo, hi, n in [((k[0], k[1]), lo, hi, n) for k, lo, hi, n in wide[:4]]:
        print(f"    {mk:9} {mi:3} n={n}  {lo:>5} - {hi:>5} tokens  ({hi/max(lo,1):.0f}x)")
    print("\n  Those spreads are not reasoning-budget variation. Inspecting the "
          "text: llama\n  and hermes hit the cap by degenerating into repetition "
          "AFTER answering, so\n  their upper tail is billed waste, not a longer "
          "answer. Capping them lower\n  costs nothing but the drift. Kimi's tail "
          "on I4/I6 is the opposite case — the\n  answer had not been reached "
          "yet, so its numbers here are floors.")
    print("\n  Note on truncation: where a draw hit its cap, the recorded token "
          "count is\n  exactly what was billed, so these totals are right for "
          "budgeting even where\n  the answer itself was lost. The two failure "
          "modes do not coincide.")


if __name__ == "__main__":
    main()
