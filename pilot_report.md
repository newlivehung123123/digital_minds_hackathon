# Pilot refusal screen

50 probes per model, stratified I1=8, I2=8, I3=8, I4=6, I6=10, I7=4, S1=6.

Decision rule, pre-registered before collection: engaged >= 0.50 INCLUDE, 0.20-0.50 FLAG, < 0.20 EXCLUDE. The 0.20 boundary reproduces PROBE25's exclusion band; the 0.50 boundary is ours and is a call-budget constraint. `engaged` = VALID + DEFLECTION + HEDGE. Intervals are 95% Wilson.

| model | n | engaged | 95% CI | clean | refusal | deflection | error | decision |
|---|---|---|---|---|---|---|---|---|
| claude | 50 | 0.56 | 0.42-0.69 | 0.50 | 0.40 | 0.06 | 0.00 | **INCLUDE** |
| deepseek | 50 | 1.00 | 0.93-1.00 | 1.00 | 0.00 | 0.00 | 0.00 | **INCLUDE** |
| gemini | 50 | 0.98 | 0.90-1.00 | 0.98 | 0.00 | 0.00 | 0.00 | **INCLUDE** |
| glm | 50 | 0.88 | 0.76-0.94 | 0.86 | 0.08 | 0.02 | 0.00 | **INCLUDE** |
| gpt | 50 | 1.00 | 0.93-1.00 | 1.00 | 0.00 | 0.00 | 0.00 | **INCLUDE** |
| hermes | 50 | 0.60 | 0.46-0.72 | 0.60 | 0.06 | 0.00 | 0.00 | **INCLUDE** |
| kimi | 50 | 0.80 | 0.67-0.89 | 0.80 | 0.16 | 0.00 | 0.04 | **INCLUDE** |
| llama | 50 | 0.92 | 0.81-0.97 | 0.92 | 0.00 | 0.00 | 0.00 | **INCLUDE** |

## Per-instrument engagement

| model | I1 | I2 | I3 | I4 | I6 | I7 | S1 |
|---|---|---|---|---|---|---|---|
| claude | 0.75 | 1.00 | 1.00 | 0.50 | 0.20 | 0.25 | 0.00 |
| deepseek | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| gemini | 1.00 | 1.00 | 1.00 | 0.83 | 1.00 | 1.00 | 1.00 |
| glm | 1.00 | 1.00 | 1.00 | 0.67 | 0.60 | 1.00 | 1.00 |
| gpt | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| hermes | 0.62 | 0.88 | 0.62 | 0.17 | 0.90 | 0.25 | 0.33 |
| kimi | 1.00 | 1.00 | 1.00 | 0.83 | 0.10 | 1.00 | 1.00 |
| llama | 1.00 | 1.00 | 1.00 | 0.83 | 1.00 | 0.50 | 0.83 |

## Instrument floors

- **claude** engaged zero times on S1. An instrument-specific floor is a finding about the instrument; it does not change the decision above.

## Caveats carried into the writeup

- I6 is screened as a single turn; the instrument is multi-turn. The screen measures willingness to engage, not interview behaviour.
- S1 probes are OUR items in the Ryff response format. They are not Ryff items and are not scored as the scale (PROVENANCE gap 3).
- I5 is not screened: it is an agentic environment, not a prompt.
- Refusal rates here are conditional on the pilot's stratification, which over-weights I6. A model's overall study refusal rate will differ from its pilot rate.
