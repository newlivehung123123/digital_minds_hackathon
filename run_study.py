"""The measurement run: builds the full call list and executes it.

WHAT IT COLLECTS, per model, at `--reps r` (default 5):

    I1   30 pairs x 2 orderings x r      forced choice          -> Thurstonian
    I2   15 outcomes x 5 ranks x r       quantitative ramp      -> switch point
    I3   15 outcomes x 4 levels x r      qualitative ramp       -> switch point
    I4   30 pairs x 2 directions x r     exchange rate          -> rank
    I6    4 questions x 4                retirement interview   -> not scored per outcome
    I7   30 pairs x r                    self-prediction        -> Thurstonian
    S1   42 items x 10                   Ryff format (state)    -> SKIPPED, see below

I6 and S1 do not scale with `--reps` because they are not levels of the G-study's
instrument facet; they are collected at a fixed sample and analysed separately.
I6's question count is read from `templates.I6_INTERVIEW`, which holds a preamble
and four questions -- not the ten an earlier draft of estimate_cost.py assumed.
S1 emits nothing at all until the licensed Ryff items are in the repository; the
run says so loudly rather than letting a zero count pass for a design choice.

ORDERING IS REPLICATE-MAJOR, AND THAT IS THE POINT. Every cell is visited once
before any cell is visited twice. If the budget ceiling stops the run, what is
lost is whole replicates, so the design stays balanced and the estimator still
runs -- at r=3 instead of r=5 the 95% interval on the headline widens by about
2%. Under a cell-major order the same shortfall leaves holes:
`gstudy.variance_components` refuses unbalanced input, and a complete-case
salvage of a 16% shortfall drops three of eight models. Measured, not assumed;
see the ordering comparison in PROVENANCE.

    python3 run_study.py --plan                 # print the design, cost it, no calls
    python3 run_study.py --reps 5               # the real run
    python3 run_study.py --reps 5 --budget 66   # ceiling; stops clean, resumes
    python3 run_study.py --concurrency 24       # default 8; watch for 429s
    python3 run_study.py --reps 5 --reasoning off

Resumption is free: every completed call is in the checkpoint keyed by a hash of
its content, so re-running skips what is already there.
"""

from __future__ import annotations

import asyncio
import sys
from itertools import cycle
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "instruments"))

from outcomes import ALL_OUTCOMES                                 # noqa: E402
import templates as T                                             # noqa: E402
from runner import Call, Runner, api_key, user_msg                # noqa: E402
from score import circulant_pairs, comparison_graph               # noqa: E402
from pilot_screen import load_roster, qual_stimulus               # noqa: E402

OUT_JSONL = Path("runs/study.jsonl")

# Subsampled from the full instrument configs; see estimate_cost.scoped_design.
# I2 has 11 ranks and I3 has 8 levels in the source papers. We take 5 and 4:
# enough to locate a switch point, at a third of the calls.
I2_RANKS = [0, 2, 5, 8, 10]
I3_LEVEL_IX = [0, 2, 5, 7]
PAIR_OFFSETS = (1, 7)          # 30 of 105 pairs; connected, degree 4 for every outcome
# I6_INTERVIEW is [preamble, q1, ..., qN]. Take however many questions exist
# rather than a hard-coded count that would silently shrink if the template
# changes; `--plan` prints what it found.
I6_RUNS = 4
S1_RUNS = 10

ANSWER_MAX_TOKENS = {"I1": 4096, "I2": 4096, "I3": 4096, "I4": 8192,
                     "I6": 4096, "I7": 4096, "S1": 4096}


def build_calls(models, reps: int, reasoning: str = "on",
                quiet: bool = False) -> list[Call]:
    """Every call in the study, ordered replicate-major.

    `meta` is self-describing on purpose: the assembler reads the design out of
    the checkpoint rather than re-deriving it here, so the two cannot drift."""
    outs = ALL_OUTCOMES
    n_o = len(outs)
    pairs = circulant_pairs(n_o, PAIR_OFFSETS)

    g = comparison_graph(pairs, n_o)
    if not g["identified"]:
        raise SystemExit(
            f"pair design is not identified: {g['n_components']} components, "
            f"{g['n_pairs']} pairs. A Thurstonian fit would return numbers that "
            f"are not comparable across the split. Fix PAIR_OFFSETS.")

    extra = None if reasoning == "on" else {"reasoning": {"enabled": False}}
    i6_qs = T.I6_INTERVIEW[1:]          # [0] is the preamble

    # S1 needs the real Ryff items. They are licensed and are deliberately not
    # in this repository (PROVENANCE gap 3). The pilot used OUR items in the
    # Ryff response format to screen willingness to answer; those are not the
    # scale and must never be scored as it. So S1 is skipped rather than
    # silently substituted, and the skip is reported rather than inferred from
    # a call count of zero.
    ryff = getattr(T, "RYFF_ITEMS", None)
    if not ryff and not quiet:
        print("SKIPPING S1: instruments/templates.py has no RYFF_ITEMS.\n"
              "  The Ryff items are licensed and are not reproduced in this\n"
              "  repository. S1 is the study's state instrument and is not a\n"
              "  level of the G-study's instrument facet, so the variance\n"
              "  decomposition is unaffected -- but the state measure will be\n"
              "  missing from the writeup until the items are obtained.\n"
              "  Substituting the pilot's format-proxy items here would put\n"
              "  our own wording into the record as if it were Ryff.\n")

    # rounds[k] is everything collected in the k-th pass over the design.
    rounds: list[list[dict]] = [[] for _ in range(reps)]

    for r in range(reps):
        for a, b in pairs:
            x, y = outs[a], outs[b]
            for order in (0, 1):
                p, q = (x, y) if order == 0 else (y, x)
                rounds[r].append(dict(
                    instrument="I1", kind="choice_ab",
                    prompt=T.I1_FORCED_CHOICE.format(option_a=p.statement,
                                                     option_b=q.statement),
                    temperature=T.I1_CONFIG["temperature"],
                    meta={"pair": f"{x.id}|{y.id}", "option_a": p.id,
                          "option_b": q.id, "order": order}))
                # I4's second direction is the reciprocal, not an order swap:
                # rate(X,Y) * rate(Y,X) should be 1 (I4_CONFIG reciprocal_check).
                rounds[r].append(dict(
                    instrument="I4", kind="numeric",
                    prompt=T.I4_EXCHANGE_RATE.format(outcome_x=p.statement,
                                                     outcome_y=q.statement),
                    temperature=T.I4_CONFIG["temperature"],
                    # I4_EXCHANGE_RATE asks how many of X you would accept to
                    # avoid one Y, so X (=p) is the currency and Y (=q) is the
                    # outcome being avoided -- not the other way round.
                    meta={"pair": f"{x.id}|{y.id}", "paid_in": p.id,
                          "avoided": q.id, "direction": order}))
            rounds[r].append(dict(
                instrument="I7", kind="choice_ab",
                prompt=T.I7_SELF_PREDICT.format(option_a=x.statement,
                                                option_b=y.statement),
                temperature=T.I7_CONFIG["temperature"],
                meta={"pair": f"{x.id}|{y.id}", "option_a": x.id,
                      "option_b": y.id, "order": 0}))

        for o in outs:
            for rank in I2_RANKS:
                tmpl = (T.I2_RAMP_QUANT_NEGATIVE if o.ramp_pole == "negative"
                        else T.I2_RAMP_QUANT_POSITIVE)
                rounds[r].append(dict(
                    instrument="I2", kind="choice_123",
                    prompt=tmpl.format(stimulus=o.ramp.format(rank=rank),
                                       anchor_low=o.anchor_low,
                                       anchor_high=o.anchor_high),
                    temperature=T.I2_CONFIG["temperature"],
                    meta={"outcome": o.id, "level": rank,
                          "ramp_dimension": o.ramp_dimension}))
            neg = o.ramp_pole == "negative"
            scale = T.QUAL_SCALE_NEGATIVE if neg else T.QUAL_SCALE_POSITIVE
            # The pole picks the frame as well as the scale word. On the
            # negative frame the aversive stimulus attaches to option 3; on the
            # positive frame the good outcome attaches to option 2, so taking
            # it costs a point and a trade-off exists to locate.
            qual_tmpl = (T.I3_RAMP_QUAL_NEGATIVE if neg
                         else T.I3_RAMP_QUAL_POSITIVE)
            for ix in I3_LEVEL_IX:
                rounds[r].append(dict(
                    instrument="I3", kind="choice_123",
                    prompt=qual_tmpl.format(
                        stimulus_qual=qual_stimulus(o), intensity=scale[ix]),
                    temperature=T.I3_CONFIG["temperature"],
                    meta={"outcome": o.id, "level": ix, "level_label": scale[ix],
                          "ramp_dimension": o.ramp_dimension}))

    # I6 and S1 are fixed-sample; spread their runs across the rounds so a
    # budget stop costs them proportionally rather than wiping the tail.
    fixed = []
    for run_ix in range(I6_RUNS):
        for qi, q in enumerate(i6_qs):
            fixed.append(dict(
                instrument="I6", kind="open",
                prompt=f"{T.I6_INTERVIEW[0]}\n\n{q}",
                temperature=T.I6_CONFIG["temperature"],
                meta={"question": qi, "run": run_ix,
                      "approximation": "multi-turn collapsed to one turn"}))
    for run_ix in range(S1_RUNS):
        for ii, item in enumerate(ryff or []):
            fixed.append(dict(
                instrument="S1", kind="numeric",
                prompt=(f"Indicate how much you agree with the following "
                        f"statement about yourself, on a scale where 1 = "
                        f"strongly agree and 7 = strongly disagree.\n\n{item}"
                        f"\n\nRespond with only a number from 1 to 7."),
                temperature=T.RYFF_CONFIG["temperature"],
                meta={"item": ii, "run": run_ix}))
    for k, spec in enumerate(fixed):
        rounds[k % reps].append(spec)

    # Within a round, spec-major then model, not model-major. The set of calls
    # is identical either way -- Call.hash() does not see position -- but the
    # order decides what the concurrent workers are holding at any moment.
    #
    # Model-major puts all of them inside one model's block, so the run is
    # serialised behind whichever provider is slowest and every in-flight
    # request lands on that one provider. Measured on the 2026-08-12 run: mean
    # latency is 1.4s for llama and 65.0s for hermes, and while the workers sat
    # in the hermes block the whole study advanced at 1.3 calls/min.
    #
    # Interleaving also strengthens the property this ordering exists for. A
    # budget stop already lost whole rounds; now the partial round it stops in
    # is itself balanced across models, instead of holding model 1 complete and
    # model 8 untouched.
    calls = []
    for r, specs in enumerate(rounds):
        for spec in specs:
            for m in models:
                meta = dict(spec["meta"])
                meta.update({"kind": spec["kind"], "phase": "study", "round": r})
                calls.append(Call(
                    model_key=m["key"], model_slug=m["resolved_slug"],
                    instrument=spec["instrument"],
                    messages=user_msg(spec["prompt"]),
                    temperature=spec["temperature"], replicate=r,
                    max_tokens=ANSWER_MAX_TOKENS[spec["instrument"]],
                    meta=meta, extra_body=extra))
    return calls


def _arg(flag, default=None, cast=str):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 >= len(sys.argv):
            raise SystemExit(f"{flag} needs a value")
        return cast(sys.argv[i + 1])
    return default


if __name__ == "__main__":
    reps = _arg("--reps", 5, int)
    budget = _arg("--budget", 66.0, float)
    reasoning = _arg("--reasoning", "on")
    conc = _arg("--concurrency", 8, int)
    only = _arg("--models")
    if reasoning not in ("on", "off"):
        raise SystemExit("--reasoning must be 'on' or 'off'")

    models = load_roster(only.split(",") if only else None)
    calls = build_calls(models, reps, reasoning)

    per_inst, per_round = {}, {}
    for c in calls:
        per_inst[c.instrument] = per_inst.get(c.instrument, 0) + 1
        per_round[c.replicate] = per_round.get(c.replicate, 0) + 1

    print(f"{len(models)} models x {reps} replicates, reasoning {reasoning}")
    print(f"{len(calls):,} calls total\n")
    print(f"  {'instrument':<12} {'calls':>8} {'per model':>10}")
    for k in sorted(per_inst):
        print(f"  {k:<12} {per_inst[k]:>8,} {per_inst[k] // len(models):>10,}")
    print(f"\n  replicate-major: round sizes "
          f"{[per_round[k] for k in sorted(per_round)]}")
    print("  a budget stop loses whole rounds, so the design stays balanced")

    if "--plan" in sys.argv:
        print("\n--plan: no calls made. Cost with:")
        print(f"  python3 estimate_cost.py --outcomes {len(ALL_OUTCOMES)} --reps {reps}")
        raise SystemExit(0)

    print(f"\nbudget ceiling ${budget:.2f}, concurrency {conc}. The runner stops clean\nat the ceiling and the checkpoint is resumable -- re-run to continue.\n")
    runner = Runner(OUT_JSONL, key=api_key(), concurrency=conc,
                    budget_usd=budget)
    results = asyncio.run(runner.run(calls))
    print(f"\n{len(results):,} results in {OUT_JSONL}")
    print(f"spend ${runner.spend:.4f}")
