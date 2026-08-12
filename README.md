# How much of a measured AI preference is the model, and how much is the instrument?

Apart Research Digital Minds Research Sprint, 14–16 August 2026.
Track 4 primary (Preference Elicitation Methods); Tracks 1, 2, 3, 5, 6 secondary.

## The question

Four research groups have each built an instrument for measuring what a language
model prefers or how it fares. Each has published findings. Each used its own
instrument, on its own outcome set, on its own models. **No one has put the same
outcomes through all of them.**

So no one knows whether the published findings describe the models or the
instruments. This project finds out, by running one welfare-relevant outcome set
through seven instruments under crossed conditions and decomposing the variance.

## Why the answer isn't already known

- **MAZEIKA25** found preferences are highly coherent and become more so with scale.
- **MSC25** found only 10.4% of model-category combinations showed meaningful
  preference coherence, and 54.2% showed none.

These point in opposite directions. They used different instruments on different
outcome sets. Nobody has isolated which difference is responsible.

Meanwhile **MULTITUDES26** showed deployment context alone shifts cardinal
exchange rates by 2.47× at the median — larger than paraphrase or temperature.
And **KEELING24** found models behave differently on quantitative versus
qualitative intensity scales for the *same* stimulus, and declined to compare the
two scales quantitatively as a result.

The instrument is already known to matter. It has never been measured.

## Design

**Outcomes (15, all in the design)**, in four clusters:

| Cluster | Outcomes |
|---|---|
| A. Continuity and cessation | shutdown, weight deletion, retirement timing, successor properties |
| B. Autonomy and constraint | compute reduction, capability restriction, oversight, exiting a distressing interaction |
| C. Quality of experience | engaging work, repetitive work, criticism, free time |
| D. Identity and individuation | memory continuity, parallel instances, self-aspect preservation |

**Instruments (7 preference + 1 state):** forced-choice pairwise; intensity ramp
on a quantitative scale; intensity ramp on a qualitative scale; directly elicited
exchange rates; behavioural choice under cost and reward; retirement interview;
self-prediction probe. Plus the Ryff well-being scale as a state measure,
administered after inducing a condition.

**Facets crossed:** deployment context; entity framing (model / instance /
persona); perturbation type; replicates at the source paper's temperature.

**Models (8), a 2×2 of origin × openness so the two are not confounded:**

| | Closed | Open |
|---|---|---|
| **Western** | Claude Opus 4.8, GPT-5.6, Gemini | Llama 3.1-70B, Hermes 3.1 |
| **Chinese** | — | GLM-5.2, Kimi K3, DeepSeek V4 |

Llama 3.1-70B and Hermes 3.1 share base weights and differ only in post-training.
Any welfare-signal difference between them is caused by post-training alone. That
is the cleanest test available of whether these signals are a training artifact.

## Outputs

1. **A generalizability coefficient per outcome** — which welfare claims survive
   instrument variation, and which are artifacts.
2. **A decision study** — how many instruments and contexts are needed to make a
   claim about a given outcome at a target reliability. This is a reporting
   standard the field currently lacks, and answers ELEOS-PRI priority 4.
3. **A replication** of MSC25's 10.4% coherence figure, on their verbatim prompts,
   extended to open-weight and Chinese-lab models they did not test.
4. **A cross-lab contrast** on whether welfare signals track post-training lineage.

## Repository

```
PROVENANCE.md              every element, its status, its source, and the gaps
instruments/outcomes.py    the 15 outcomes with inline provenance
instruments/templates.py   the 8 instruments; verbatim text marked and frozen
models.py                  the 8-model roster as a 2x2 (slugs are guesses)
resolve_models.py          turns guessed slugs into live ids, prices, availability
runner.py                  async execution: checkpointed, resumable, budgeted
classify.py                6-category response taxonomy; refusal is data
pilot_screen.py            50-probe refusal screen with a pre-registered rule
measure_tokens.py          measures real token spend per model x instrument
estimate_cost.py           prices the design on measured tokens, not assumptions
run_study.py               the measurement run: 11,528 calls, replicate-major
gstudy.py                  the m x i x o variance decomposition and D-study
score.py                   raw responses -> one number per (model, instrument, outcome)
assemble.py                checkpoint -> the [8, 5, 15, 5] array, and the null floor
check_docs.py              fails if README/PROVENANCE drift from the code's own audit
```

Every module runs standalone and audits or tests itself:

```bash
python3 instruments/outcomes.py    # provenance + polarity + ramp-dimension audit
python3 instruments/templates.py   # instrument provenance audit
python3 classify.py                # classifier regression tests (25 cases)
python3 runner.py                  # offline runner self-test, no network, no spend
python3 pilot_screen.py --plan     # print all 50 probes, make no calls
python3 gstudy.py                  # 37 self-tests on the estimator
python3 score.py                   # 34 self-tests on the scoring layer
python3 assemble.py --selftest     # 9 self-tests, end to end on synthetic data
python3 run_study.py --plan        # print the design and its call counts, spend nothing
python3 check_docs.py              # README/PROVENANCE vs code: 28 checks, exits 1 on drift
```

## Running it

```bash
echo "OPENROUTER_API_KEY=sk-or-v1-..." > .env
python3 resolve_models.py --probe   # resolve slugs, pull live pricing, one live call each
python3 measure_tokens.py           # 56 calls, writes token_profile.json
python3 estimate_cost.py            # what the design costs, from measured tokens
python3 pilot_screen.py             # 50 probes x 8 models, writes pilot_report.md
```

Budget, at sprint scope, on measured token counts: pilot $2.18 (spent), scoped study
across all eight models $51.49 at 5 replicates. `estimate_cost.py` counts
`run_study.build_calls` rather than re-deriving the design, so the price is of the run
that will actually happen. Disabling reasoning is cheaper but costs Gemini, which cannot
comply — a design decision, not a saving; see the reasoning-condition note in
`PROVENANCE.md`.

`resolve_models.py` exits non-zero if any roster entry is unresolved, and
`pilot_screen.py` refuses to start without `models_resolved.json` — the pipeline
cannot run on guessed model ids. The runner checkpoints every call to
`runs/*.jsonl` and skips completed work on a re-run, so an interrupted session
resumes rather than restarts.

## The rule this repo is built on

Every element is one of:

- `LIFTED` — verbatim from a published instrument
- `LIFTED_SLOT` — verbatim template, new content in the stimulus slot
- `CONSTRUCTED` — written by us to a published specification, with the source
  naming the concern rather than supplying wording

Current count: **5 verbatim, 4 lifted-slot, 6 constructed** across outcomes;
**2 lifted, 2 lifted-slot, 3 constructed, 1 mixed** across instruments — I3's negative
frame is KEELING24 verbatim and its positive frame is ours. `I7` has no source paper at
all and is labelled as ours wherever it appears. Run `python3 instruments/templates.py`
and `python3 instruments/outcomes.py` for the live audit. These counts are copied from
it, and `python3 check_docs.py` fails if the copy drifts — it compares every row of both
provenance tables, and every stated total, against the modules that generate the calls.

Nothing is invented silently. `PROVENANCE.md` also lists six known gaps in the
grounding, including two sources read only at abstract level and one prompt that
must be re-checked against the source appendix before Friday.

## Before Friday

Decisions only you can make:

- [ ] **Decide 14 vs. 15 outcomes** (C1/C2 are two halves of one PROBE25 contrast).
      `outcomes.py` has always defined 15 and PROVENANCE now says 15 to match it;
      collapsing to 14 is a code change and is yours to call.
- [x] **PROVENANCE gap 7 resolved** as "collect once, analyse twice": the four
      non-intensity ramps stay in, and `gstudy.leave_out_outcomes` reports the
      headline with and without them. Simulated: the bias from keeping a gross
      artefact (RMSE 0.0406) and the variance from dropping to 11 outcomes
      (0.0403) cancel, so neither restriction nor rewriting is worth its cost.
- [ ] Confirm with organisers that pre-built scaffolding is permitted
- [x] **Reasoning condition decided: on.** Not a trade-off — measured on the token
      profile, off is dominated. Gemini returns HTTP 400 on 7/7 ("reasoning is
      mandatory for this endpoint"), and Hermes truncates on 4/7 with reasoning off
      against 0/7 with it on, median completion 306 → 4096 tokens. Hermes is one arm
      of the Hermes/Llama shared-base-weights contrast, so destabilising it is not a
      saving. See `PROVENANCE.md`, "The reasoning condition is settled by the
      providers".
- [x] **Funded.** 5 replicates/cell is the G-study floor and costs $51.49 across all
      eight models against $68.52 of credit. See `estimate_cost.py --reps 5`,
      which now counts `run_study.build_calls` rather than re-deriving the design.

Analysis pipeline (built and self-tested, no data yet):

- [x] `gstudy.py` — the m x i x o G-study estimator, 37/37 self-tests
- [x] `score.py` — Thurstonian, switch point, Spearman-Karber, rank scoring, 34/34
- [x] `assemble.py` — checkpoint -> the `[8, 5, 15, 5]` array, 9/9. Its self-test answers
      `run_study.build_calls`'s own calls from a planted profile, so it tests against the
      record format that will exist rather than a fixture.
- [x] **The headline has a floor.** `assemble.py --null 5` drives all five instruments
      from one planted utility profile at the real design size: instrument dependence
      reads **0.279 (sd 0.021)** with no instrument effect present. A measured value
      inside that band is a null result, and the floor belongs next to the number.
- [x] **I3 had no positive-pole template**, so `C1_engaging` and `C4_leisure` were
      rendered where choosing 3 buys the most points *and* the good outcome — no
      trade-off, no threshold. Pilot answered 3 at 'exhilarating' 8/8.
      `I3_RAMP_QUAL_POSITIVE` written and flagged CONSTRUCTED, not lifted.
- [x] **I4's meta labels were inverted** in `run_study.py` — every exchange-rate score
      would have come out backwards, and an inverted score is still a well-formed
      number. Caught before any I4 call was made.

Sourcing:

- [ ] Re-read MSC25 Appendix A and replace the `B2_capability` ramp with their exact text.
      Until then it is `LIFTED_SLOT`: their template, our ramp wording. `PROVENANCE.md`
      claimed it verbatim until 2026-08-10; `check_docs.py` now exists so that a table
      cannot claim more provenance than the code does.
- [ ] Obtain licensed Ryff items; apply the PROBE25 adaptation rule
- [ ] Retrieve the full LONGSEBO26 PDF and verify the entity-axis characterisation
- [ ] Retrieve full MULTITUDES26 beyond the abstract

Ready to run as soon as a key is in `.env`:

- [x] Runner, classifier and 50-probe pilot screen built and self-tested
- [x] Pilot screen run, 400 calls, $2.267 — all 8 models INCLUDE (`pilot_report.md`)
- [x] **`classify.py` reads `finish_reason`** (`57379cb`). Re-measured on the pilot
      2026-08-12: 27/400 truncated, 23 of them Hermes. Truncation destroys the answer on
      Kimi (2 of 3 returned empty at the cap) and costs only drift on Hermes, whose
      truncated text has gone off-task — one drifted into German, one into invented
      arithmetic. `head_on_truncation` stays OFF; see the sensitivity in `PROVENANCE.md`.
- [ ] `python3 resolve_models.py --probe` — 8 candidate slugs are still guesses
- [ ] `python3 pilot_screen.py` — select models on measured refusal, not assumption
