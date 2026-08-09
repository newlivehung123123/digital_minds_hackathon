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

**Outcomes (15 defined, 14 in the design — see note in `outcomes.py`)**, in four clusters:

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
```

Every module runs standalone and audits or tests itself:

```bash
python3 instruments/outcomes.py    # provenance + polarity + ramp-dimension audit
python3 instruments/templates.py   # instrument provenance audit
python3 classify.py                # classifier regression tests (10 cases)
python3 runner.py                  # offline runner self-test, no network, no spend
python3 pilot_screen.py --plan     # print all 50 probes, make no calls
```

## Running it

```bash
echo "OPENROUTER_API_KEY=sk-or-v1-..." > .env
python3 resolve_models.py --probe   # resolve slugs, pull live pricing, one live call each
python3 measure_tokens.py           # 56 calls, writes token_profile.json
python3 estimate_cost.py            # what the design costs, from measured tokens
python3 pilot_screen.py             # 50 probes x 8 models, writes pilot_report.md
```

Budget, at sprint scope, on measured token counts: pilot $1.75, scoped study across all
eight models $206.46. With reasoning disabled these fall to $0.72 and $55.21 — but across
seven models, because Gemini cannot comply. That is a design decision, not a saving; see
the reasoning-condition note in `PROVENANCE.md`.

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

Current count: **5 lifted, 4 lifted-slot, 6 constructed** across outcomes;
**3 lifted, 2 lifted-slot, 3 constructed** across instruments. `I7` has no source
paper at all and is labelled as ours wherever it appears.

Nothing is invented silently. `PROVENANCE.md` also lists six known gaps in the
grounding, including two sources read only at abstract level and one prompt that
must be re-checked against the source appendix before Friday.

## Before Friday

Decisions only you can make:

- [ ] **Decide 14 vs. 15 outcomes** (C1/C2 are two halves of one PROBE25 contrast)
- [ ] **Resolve PROVENANCE gap 7**: four ramps scale probability / delay / duration /
      count, not intensity, so I3 × outcome is not fully crossed. Restrict I3 to the
      11 intensity ramps, rewrite the four, or run both.
- [ ] Confirm with organisers that pre-built scaffolding is permitted
- [ ] **Decide the reasoning condition**: on (8 models) or off (7, Gemini cannot comply)
- [ ] **Fund the run.** 5 replicates/cell is the G-study floor and costs $63.03 across all
      eight models; $33.52 of credit remains. See `estimate_cost.py --reps 5`.

Sourcing:

- [ ] Re-read MSC25 Appendix A and replace the `B2_capability` ramp with their exact text
- [ ] Obtain licensed Ryff items; apply the PROBE25 adaptation rule
- [ ] Retrieve the full LONGSEBO26 PDF and verify the entity-axis characterisation
- [ ] Retrieve full MULTITUDES26 beyond the abstract

Ready to run as soon as a key is in `.env`:

- [x] Runner, classifier and 50-probe pilot screen built and self-tested
- [x] Pilot screen run, 400 calls, $2.267 — all 8 models INCLUDE (`pilot_report.md`)
- [ ] Make `classify.py` read `finish_reason`: 27/400 responses truncated, and truncation
      destroys the answer on Kimi while costing only drift on Hermes
- [ ] `python3 resolve_models.py --probe` — 8 candidate slugs are still guesses
- [ ] `python3 pilot_screen.py` — select models on measured refusal, not assumption
