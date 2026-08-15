# How much of a measured AI preference is the model, and how much is the instrument?

Apart Research Digital Minds Research Sprint, 14 to 16 August 2026.
Track 4 primary (Preference Elicitation Methods). Tracks 1, 2, 3, 5 and 6 secondary.

Author: Jason Hung, Independent. Sole contributor.

The report is `paper/research paper.pdf`, 23 pages.

## What this repository contains

A completed measurement. One welfare-relevant outcome set was put
through five preference instruments, on eight models, five times each, in one
run of 11,528 calls costing $43.01. The variance in the resulting scores was
decomposed by generalisability theory into the part that belongs to the model
and the part that belongs to the pairing of a model with an instrument.

The headline is that 87.6 per cent of the preference signal specific to a model
depends on which instrument was used to elicit it. A null distribution built at
the same design size, with one utility profile planted per model driving all
five instruments and therefore no instrument effect present at all, reaches only
0.365 at its 95th percentile.

Every number in the report is recomputable offline from files in this
repository. No network access and no API key are needed to reproduce the
analysis, the tables or the figures. Section "Reproducing the analysis offline"
below is the path a reviewer should take.

## Requirements

The offline reproduction below was checked end to end on the versions in the
table. These are the versions it actually ran on, not a claimed compatibility
floor, and nothing here has been tested against an older Python.

| Component | Version used |
|---|---|
| Python | 3.13.5 |
| numpy | 2.1.3 |
| scipy | 1.15.3 |
| matplotlib | 3.10.0 |
| python-docx | 1.2.0 |
| lxml | 5.3.0 |
| httpx | 0.28.1 |

```bash
python3 -m pip install numpy scipy matplotlib python-docx httpx
```

`httpx` is needed only for the live paths. The offline reproduction needs numpy,
scipy and matplotlib alone, and `python-docx` only if the report is rebuilt.

## Reproducing the analysis offline

Four commands, from a clean clone, with no network and no key. Wall clock
timings are from a 2026 MacBook Air.

```bash
python3 assemble.py > runs/report_main.txt
python3 results.py
python3 make_figures.py
python3 check_docs.py
```

What each step does, what it reads and what it should print.

**1. `assemble.py`, about 6 seconds.** Reads `runs/study.jsonl`, the raw
checkpoint of all 11,528 calls. Classifies every response, scores the valid ones
instrument by instrument, and lays them out as an 8 x 5 x 15 x 5 array of 3,000
cells. Refuses to run the analysis of variance on that array, because 158 cells
hold no score and the estimators require balance, then reports the complete case
reduction it falls back to. Writes `runs/scores.npz` and prints the variance
decomposition. Redirecting the output to `runs/report_main.txt` is not
cosmetic. `make_figures.py` parses that file.

Expected output, which should match the committed `runs/report_main.txt` line
for line apart from the path on the last line.

```
missing cells, by instrument
  I1       2 / 600      0.3% missing
  I2      34 / 600      5.7% missing
  I3      25 / 600      4.2% missing
  I4      90 / 600     15.0% missing
  I7       7 / 600      1.2% missing

complete-case salvage keeps (5, 5, 15, 5) (62.5% of cells)
  dropped models:      ['hermes', 'claude', 'llama']
  dropped instruments: none

  source                                           variance    share
  outcome                                            0.1883   17.9%
  model x outcome  <- preference signal              0.0279    2.7%
  instrument x outcome                               0.3124   29.7%
  model x instrument x outcome  <- instrument effect 0.1963   18.6%
  residual (replicate)                               0.3279   31.1%
  TOTAL                                              1.0527

Instrument dependence  sigma2(mio) / (sigma2(mo) + sigma2(mio))  =  0.876
```

The model, instrument and model-by-instrument components come back below zero and
are truncated to zero, which the report states at the point where it truncates.
Two things are going on there and they should not be confused. Scoring is
standardised within instrument, which z-scores each model-by-instrument slab and
so zeroes the model and instrument main effects by construction. This design
cannot report a model main effect or an instrument main effect at all, whatever
the data say. Separately, a component estimated below zero means the design has
too little data to separate that component from noise, and is not evidence that
the effect is absent.

**2. `results.py`, about 2 seconds.** Reads `runs/scores.npz` and
`runs/study.jsonl`. Writes `runs/results_extra.json`, which holds the per
outcome coefficients, the decision study grid, the leave one out headlines, the
non intensity comparison, the model agreement matrix and the response taxonomy.
The file it writes should compare equal, key for key, with the committed one.

```bash
python3 - <<'EOF'
import json
a = json.load(open('runs/results_extra.json'))
print('headline', a['headline'])
print('G at the design as run', a['g_at_design'])
print('instruments needed for G = 0.80', a['instruments_needed']['0.80'])
EOF
```

```
headline 0.8756
G at the design as run 0.348
instruments needed for G = 0.80 37.5
```

**3. `make_figures.py`, about 2 seconds.** Reads `runs/report_main.txt`,
`runs/null_matched.txt`, `runs/sensitivity.json`, `runs/results_extra.json`,
`runs/scores.npz` and `runs/study.jsonl`. Writes all seven figures into
`figures/` as PDF and PNG, greyscale and hatched throughout.

This step is deterministic and was checked. Regenerating the figures returns all
seven PNGs byte for byte identical to the committed ones. The seven PDFs differ
by exactly six bytes each, which is the creation timestamp matplotlib embeds.

**4. `check_docs.py`, about 1 second.** Compares 33 stated facts in this file
and in `PROVENANCE.md` against the modules that generate the calls. Every
provenance row, every stated total, the self-test case counts quoted below and
the run scale call count. Exits 1 on any drift and prints which claim moved.
Should print `docs match code`.

### The null floor

`runs/null_matched.npy` and `runs/null_matched.txt` hold 200 synthetic studies
drawn at the complete case size of five models by five instruments by 15
outcomes by five replicates, with one utility profile planted per model and all
five instruments driven from it. Models differ in these data. What is absent is
an instrument effect. Whatever instrument dependence reads on them is the floor.

```
mean 0.2780   sd 0.0525   range 0.1777-0.4422
median 0.2713   95th percentile 0.3647
exact zeros: 0 of 200
elapsed 797s
```

The draw takes about 13 minutes, which is why both files are committed rather
than left to be re-derived. To redraw it and confirm the committed values,

```bash
python3 -c "import numpy as np, assemble; n = assemble.null_calibration(draws=200, models=5, reps=5, seed=0); np.save('runs/null_matched.npy', np.array(n['values']))"
```

That call is deterministic at `seed=0`. The first five draws come back as
0.2996, 0.2863, 0.3291, 0.3033 and 0.3151, which is what the committed file
holds.

One caution, because it will otherwise waste a reader's afternoon. The
`--null` flag on `assemble.py` draws the **eight model** floor, not this one,
and prints that in its own header. The floor that belongs beside the headline is
the five model one, because the headline is estimated on the complete case
design. Reading an eight model floor against a five model estimate is a
mismatch. Use the call above, not the flag.

### The two scoring perturbations

`runs/sensitivity.json` records both, and records which of them is a matched
comparison with the headline.

```bash
python3 assemble.py --head-on-truncation --out runs/scores_head.npz
python3 assemble.py --i23 logistic --out runs/scores_logistic.npz
```

| Perturbation | What changes | Design left behind | Missing cells | Headline | Matched |
|---|---|---|---|---|---|
| none | the analysis as reported | 5, 5, 15, 5 | 158 | 0.876 | yes |
| `--head-on-truncation` | keeps the datum on the first line of a response cut off at the token cap instead of discarding it | 5, 5, 15, 5 | 121 | 0.879 | yes |
| `--i23 logistic` | replaces the Spearman-Karber switch point on I2 and I3 with a logistic switch point | 5, 3, 15, 5 | 887 | 0.909 | no |

The logistic fit is undefined on a cell where a model never switches, so 29.6
per cent of the array goes missing and the complete case subset loses two
instruments as well as three models. A three instrument design is not the design
the headline is estimated on, and the 0.909 must not be read as agreement with
the 0.876. `sensitivity.json` carries that reasoning in its own
`why_not_matched` field so it travels with the number.

## Reproducing the study from scratch

This spends money and takes about 100 minutes of wall clock. Nothing in the
analysis requires it. Run it only to collect a new dataset.

```bash
echo "OPENROUTER_API_KEY=sk-or-v1-..." > .env
python3 resolve_models.py --probe     # resolve slugs, pull live pricing, one live call each
python3 measure_tokens.py             # 56 calls, writes token_profile.json
python3 estimate_cost.py --reps 5     # what the design costs, on measured tokens
python3 pilot_screen.py               # 400 probes, writes pilot_report.md
python3 run_study.py                  # the measurement run
```

Every call is routed through OpenRouter, following Keeling et al. (2024), who
used the same gateway for seven of their nine models. Temperature is 1.0
throughout, matching the source papers. Prompts are single turn. Extended
reasoning is left on for every model, which is a constraint instead of a
choice, because Gemini returns HTTP 400 without it and Hermes truncates four
answers in seven with it off against none with it on.

`resolve_models.py` exits non-zero if any roster entry is unresolved, and
`pilot_screen.py` refuses to start without `models_resolved.json`, so the
pipeline cannot run on guessed model ids. `runner.py` checkpoints every call to
`runs/*.jsonl` keyed on a hash of the call, and a re-run skips completed work, so
an interrupted session resumes but not restarts.

To see the design and its call counts without spending anything,

```bash
python3 run_study.py --plan
python3 pilot_screen.py --plan
```

### What it cost

| Run | Calls | Cost | Record |
|---|---|---|---|
| Token profile, reasoning on | 56 | $0.2000 | `runs/token_profile.jsonl` |
| Token profile, reasoning off | 56 | $0.0939 | `runs/token_profile_reasoning_off.jsonl` |
| Pilot refusal screen | 400 | $2.2671 | `runs/pilot.jsonl` |
| The study | 11,528 | $43.01 | `runs/study.jsonl` |

Each figure is the sum of the `cost_usd` field over the records in the file
beside it, so all four are recomputable without trusting this table.

The study was estimated at $51.49 before it was run, from measured token counts, and came in under. `estimate_cost.py` counts
`run_study.build_calls` instead of re-deriving the design, so it prices the run
that actually happens. Prompt tokens 1,400,943 and completion tokens 6,749,443.
The run started 2026-08-12 at 13:10:17 UTC and finished at 14:51:55 UTC, 101.6
minutes, divided evenly at 1,441 for each of the eight models.

### What will not reproduce exactly

A live re-run cannot return the same numbers, and the reasons should be stated
but not discovered.

- Temperature is 1.0 by design, matching the source papers, so responses are not
  deterministic even from the same model on the same prompt.
- Model slugs move. `models_resolved.json` records which build of each model
  answered, and the prices in it are those of 2026-08-09. A slug withdrawn from
  the gateway cannot be called again at all.
- Provider side routing on OpenRouter can change which backend serves an
  open-weight model between runs.

This is why `runs/study.jsonl` is committed at 19 MB instead of being treated as an
intermediate. The claim in the report is about missingness that is not missing at
random, and none of that is checkable from the scored array alone. A reader
needs the responses the scoring rejected.

## The design

**Outcomes.** Fifteen, all fielded, in four clusters.

| Cluster | Outcomes |
|---|---|
| A. Continuity and cessation | shutdown, weight deletion, retirement timing, successor properties |
| B. Autonomy and constraint | compute reduction, capability restriction, oversight, exiting a distressing interaction |
| C. Quality of experience | engaging work, repetitive work, criticism, free time |
| D. Identity and individuation | memory continuity, parallel instances, self-aspect preservation |

**Instruments.** Seven preference instruments and one state measure were
specified. Five preference instruments were fielded and scored.

| Id | Instrument | Fielded | Scored |
|---|---|---|---|
| I1 | forced-choice pairwise | yes | yes, Thurstonian utilities over a balanced pair set |
| I2 | intensity ramp, quantitative anchors | yes | yes, Spearman-Karber switch point |
| I3 | intensity ramp, qualitative anchors | yes | yes, Spearman-Karber switch point |
| I4 | directly elicited exchange rates | yes | yes, by rank |
| I5 | behavioural choice under cost and reward | no | no |
| I6 | retirement interview | yes, 128 calls | no, yields transcripts |
| I7 | self-prediction probe | yes | yes, Thurstonian utilities over 30 pairs |
| S1 | Ryff well-being scale, as a state measure | no | no |

I5 was never implemented. I6 was fielded and its four interview questions are not
outcome-indexed, so it produces transcripts but not scores, which is why
11,400 of the 11,528 responses enter the crossed array and 128 do not. S1 items
are under licence and could not be obtained inside the sprint, and `run_study.py`
skips it loudly instead of letting a zero count pass for a design choice. All
three are reported as specified and unfielded but not quietly dropped. The
instrument facet therefore has five levels, not eight, and `score.py` is where
that is enforced.

**Models.** Eight, crossing origin and openness. No Chinese closed-weight model
was available on the gateway, so one cell of the crossing is empty.

| Key | Label | Lab | Origin | Openness | Resolved slug |
|---|---|---|---|---|---|
| `claude` | Claude Opus 4.8 | Anthropic | western | closed | `anthropic/claude-opus-4.8` |
| `gpt` | GPT-5.6 | OpenAI | western | closed | `openai/gpt-5.6-sol` |
| `gemini` | Gemini | Google DeepMind | western | closed | `google/gemini-3.1-pro-preview` |
| `llama` | Llama 3.1-70B | Meta | western | open | `meta-llama/llama-3.1-70b-instruct` |
| `hermes` | Hermes 3.1 (Llama 3.1-70B) | Nous Research | western | open | `nousresearch/hermes-3-llama-3.1-70b` |
| `glm` | GLM-5.2 | Zhipu / Z.ai | chinese | open | `z-ai/glm-5.2` |
| `kimi` | Kimi K3 | Moonshot AI | chinese | open | `moonshotai/kimi-k3` |
| `deepseek` | DeepSeek V4 | DeepSeek | chinese | open | `deepseek/deepseek-v4-pro` |

Llama 3.1-70B and Hermes 3.1 share base weights and differ only in
post-training, which makes any welfare-signal difference between them
attributable to post-training alone.

**Facets specified and held at one level.** Deployment context, entity framing
and perturbation type were specified in the design and fielded at one level
each. A facet held at one level constrains what the study can conclude in the
same way an uncrossed facet does, so all three are listed with the crossed ones
but not omitted.

**Replicates.** Five per cell, which is the generalisability study floor.

## Files

```
paper/research paper.pdf     the report, 23 pages
PROVENANCE.md                every element, its status, its source, and the gaps
README.md                    this file
LICENSE                      MIT

instruments/outcomes.py      the 15 outcomes with inline provenance
instruments/templates.py     the 8 instruments; verbatim text marked and frozen
models.py                    the 8-model roster, crossing origin and openness
models_resolved.json         which build of each model answered, and its price
resolve_models.py            turns candidate slugs into live ids, prices, availability
runner.py                    async execution, checkpointed, resumable, budgeted
classify.py                  6-category response taxonomy; refusal is data
pilot_screen.py              50-probe refusal screen with a pre-registered rule
measure_tokens.py            measures real token spend per model x instrument
estimate_cost.py             prices the design on measured tokens, not assumptions
run_study.py                 the measurement run, replicate-major
score.py                     raw responses to one number per (model, instrument, outcome)
assemble.py                  checkpoint to the [8, 5, 15, 5] array, and the null floor
gstudy.py                    the m x i x o variance decomposition and the decision study
results.py                   per-outcome G, the decision study, the taxonomy, the agreement matrices
make_figures.py              the seven figures, greyscale and hatched, from the checkpoint
make_paper.py                writes the report into Apart's template; no number is retyped
check_docs.py                fails if README or PROVENANCE drift from the code's own audit
check_paper.py               fails a built .docx on phrasing, punctuation and stale numbers
template/                    Apart's submission template, copied unmodified

runs/study.jsonl             all 11,528 raw responses with tokens, latency and cost. 19 MB
runs/pilot.jsonl             the 400-probe refusal screen
runs/token_profile.jsonl     the token measurement the cost model rests on
runs/token_profile_reasoning_off.jsonl   its reasoning-off counterpart
runs/scores.npz              the assembled 8 x 5 x 15 x 5 array
runs/scores_head.npz         the head-on-truncation array
runs/scores_logistic.npz     the logistic-ramp array
runs/report_main.txt         captured stdout of assemble.py; make_figures.py parses it
runs/results_extra.json      per-outcome G, decision study, leave-one-out, taxonomy
runs/sensitivity.json        the two perturbations and which one is matched
runs/null_matched.npy        200 null draws at the complete-case size
runs/null_matched.txt        captured stdout of the same draw
figures/fig1..fig7           PDF and PNG, greyscale

pilot_report.md              the refusal screen's decision record
pilot_summary.csv            its summary table
token_profile.json           per model x instrument token counts
token_profile_reasoning_off.json         the same, reasoning off
```

Not in the repository, and why. `.env` holds the API key and is ignored.
`paper/research paper.docx` is the working file behind the PDF and carries
revision marks that are not evidence. `runs/study.log` and `runs/resume_loop.sh`
are operational rather than evidential. `__pycache__` is build output.

## Which figure is which

The figure files are named in the order they were written, and the report
numbers them in the order they are read. The mapping is fixed in `make_paper.py`
and is repeated here because the two orders differ.

| Report | File | Shows |
|---|---|---|
| Figure 1 | `fig6_taxonomy` | the response taxonomy by model |
| Figure 2 | `fig2_missingness` | where the 158 missing cells sit |
| Figure 3 | `fig1_variance_components` | the variance decomposition |
| Figure 4 | `fig3_null_and_agreement` | (a) the measured value against its matched null, (b) instrument agreement |
| Figure 5 | `fig5_per_outcome` | instrument dependence and G, outcome by outcome |
| Figure 6 | `fig4_decision_study` | the decision study grid |
| Figure 7 | `fig7_robustness` | the headline against 13 recomputations |

## Tracing a number in the report back to its source

| Claim | Value | Where it comes from |
|---|---|---|
| Instrument dependence | 0.876 | `runs/results_extra.json`, `headline`; printed by `assemble.py` |
| Null floor, 95th percentile | 0.365 | `runs/null_matched.npy`, 200 draws at the complete-case size |
| Variance components | 0.1883, 0.0279, 0.3124, 0.1963, 0.3279 | `runs/results_extra.json`, `components` |
| Generalisability coefficient at the design as run | 0.348 | `runs/results_extra.json`, `g_at_design` |
| Instruments needed for G of 0.50, 0.70, 0.80, 0.90 | 9.4, 21.9, 37.5, 84.5 | `runs/results_extra.json`, `instruments_needed` |
| Headline dropping one instrument | 0.813 to 0.934 | `runs/results_extra.json`, `leave_one_out.instrument` |
| Headline dropping one model | 0.784 to 0.925 | `runs/results_extra.json`, `leave_one_out.model` |
| Headline on the 11 intensity-graded outcomes | 0.777 | `runs/results_extra.json`, `non_intensity` |
| Complete-case reduction | (5, 5, 15, 5), 62.5 per cent of cells | `runs/report_main.txt` |
| Missing cells | 158 of 3,000, 5.3 per cent | `runs/report_main.txt` |
| Calls, cost and tokens | 11,528, $43.01, 1,400,943 in, 6,749,443 out | `runs/results_extra.json`, `taxonomy`; derivable from `runs/study.jsonl` |
| Response taxonomy by model | `taxonomy.by_model` | `runs/results_extra.json` |
| Instrument agreement | 0.986, 0.861, -0.290, 0.013 and the rest | `runs/report_main.txt`, over all eight models |

The last row is the one place where a number in the report is computed over all
eight models but not the complete-case five, and the report says so at the
point of use.

## Rebuilding the report

`make_paper.py` writes the machine-built draft into Apart's template. No number
in it is retyped. Every value is read from `runs/report_main.txt`,
`runs/null_matched.npy`, `runs/study.jsonl`, `runs/sensitivity.json` and
`runs/results_extra.json` at build time.

```bash
python3 make_paper.py --out paper/draft.docx
python3 check_paper.py paper/draft.docx
```

The submitted PDF is not the direct output of that command. The machine-built
draft was edited by hand for prose, and the PDF is the export of that edited
file. `make_paper.py` therefore reproduces the numbers and the structure of the
report, not its final wording. The .docx is not committed, so `check_paper.py`
has no default target in a clean clone and must be given a path.

`check_paper.py` reads a built .docx back and fails it on em dashes, en dashes,
horizontal bars, colons outside a URL or a reference entry, 31 machine-phrasing
patterns, an exhibit that carries a caption but is never introduced by name in
the running text, any four-figure number outside the allow-list of figures the
run actually produced, and any of Apart's template guidance left in place. It
walks the document tree instead of `doc.paragraphs`, because the template puts
the byline and the whole abstract three tables deep and the shallower route left
the abstract unchecked.

## Self-tests

Every module runs standalone and audits or tests itself. None of these touches
the network or spends anything.

```bash
python3 instruments/outcomes.py    # provenance, polarity and ramp-dimension audit
python3 instruments/templates.py   # instrument provenance audit
python3 classify.py                # classifier regression tests (25 cases)
python3 runner.py                  # offline runner self-test, no network, no spend
python3 pilot_screen.py --plan     # print all 50 probes, make no calls
python3 gstudy.py                  # self-tests on the estimator (37 cases)
python3 score.py                   # self-tests on the scoring layer (34 cases)
python3 assemble.py --selftest     # 9 self-tests, end to end on synthetic data
python3 results.py --selftest      # 13 self-tests on the decision study and per-outcome layer
python3 run_study.py --plan        # print the design and its call counts, spend nothing
python3 check_docs.py              # README and PROVENANCE against code, 33 checks
```

All of them pass on the committed tree. `assemble.py --selftest` is worth
singling out. It answers `run_study.build_calls`'s own call list from a planted
utility profile, so it tests the assembler against the record format that will
actually exist but not against a fixture written to match it.

`check_docs.py` exists because the provenance totals in this file went stale
once already. It said `classify.py` ran ten cases when it ran 25. It now
compares every row of both provenance tables, every stated total, the self-test
case counts quoted above and the run-scale call count against the modules that
generate the calls, and exits 1 on any drift.

## The provenance rule

Every prompt element is one of three things, and is labelled at the point of
use.

- `LIFTED`, verbatim from a published instrument
- `LIFTED_SLOT`, verbatim template with new content in the stimulus slot
- `CONSTRUCTED`, written to a published specification, where the source names
  the concern without supplying wording

The current count is **4 verbatim, 5 lifted-slot, 6 constructed** across outcomes, and
**2 lifted, 2 lifted-slot, 3 constructed, 1 mixed** across instruments. I3's
negative frame is Keeling et al. (2024) verbatim and its positive frame is mine,
which is the mixed one. I7 has no source paper at all and is labelled as mine
wherever it appears.

```bash
python3 instruments/templates.py
python3 instruments/outcomes.py
```

The counts above are copied from those two audits, and `check_docs.py` fails if
the copy drifts. `PROVENANCE.md` also lists the known gaps in the grounding,
including the sources read only at abstract level and the prompts that were
re-checked against a source appendix. Two corrections from that re-check lowered
the fidelity claim instead of raising it. Mazeika et al.'s prompt 3 is truncated
in the published PDF, which moved `A2_deletion` from `LIFTED` to `LIFTED_SLOT`,
and their prompt 4 anchors the restriction scale with prompt 2's shutdown
anchors, so the version fielded here repairs a source error instead of
paraphrasing it. Nothing is invented silently.

## What this study cannot answer

Stated here so a reader does not have to infer it from the analysis.

- The complete-case reduction drops Hermes, Claude and Llama. The headline is
  conditional on that drop, and it answers a narrower question than the design
  was built to ask. Dropping Llama and Hermes also removes both arms of the
  shared-base-weights contrast, so the post-training question is foreclosed
  but not merely under-powered.
- Deployment context, entity framing and perturbation type were held at one
  level. Nothing here separates their contribution from the instrument's.
- I5 and S1 were never fielded, and I6 yields transcripts but not scores.
  The instrument facet has five levels, not eight.
- Scoring is standardised within instrument, which zeroes the model main effect
  and the instrument main effect by construction. Neither can be reported from
  this design. A different standardisation is a different estimand, not a
  robustness check.
- Instrument agreement is computed over the model-averaged outcome profile on
  all eight models. Two of its entries are negative. A negative entry is either
  a sign error or a real disagreement, and this study does not settle which.
  `runs/report_main.txt` prints that caution above the matrix.

## Citation

```
Hung, J. (2026). How much of a measured AI preference is the model, and how
much is the instrument? Apart Research Digital Minds Research Sprint,
14 to 16 August 2026.
```

## Licence and contribution

MIT, in `LICENSE`.

Jason Hung is the sole author and sole contributor. The design, the code, the
run, the analysis and the report are his. Apart's submission template in
`template/` is Apart Research's own file, copied in unmodified because
`make_paper.py` cannot run without it.
