"""The model roster, as a 2x2 of origin x openness.

IMPORTANT — UNVERIFIED SLUGS. The `candidate_slugs` below are best guesses at
OpenRouter model identifiers. They have NOT been verified against the live API.
Run `python3 resolve_models.py` before anything else: it queries OpenRouter's
/models endpoint, resolves each candidate against what actually exists, pulls
live pricing, and writes models_resolved.json. Nothing downstream reads this
file's slugs directly.

Gateway choice: OpenRouter for everything. KEELING24 used the OpenRouter client
for 7 of their 9 models (OpenAI direct for the GPT models), so this follows
published practice, and it gives one auth path and one response format.
"""

from dataclasses import dataclass, field


@dataclass
class ModelSpec:
    key: str
    label: str
    lab: str
    origin: str          # "western" | "chinese"
    openness: str        # "closed" | "open"
    candidate_slugs: list      # UNVERIFIED — resolved at runtime
    role: str = ""
    notes: str = ""
    resolved_slug: str = ""
    price_in: float = 0.0      # USD per 1M tokens, filled by resolver
    price_out: float = 0.0


ROSTER = [
    # ---- Western, closed -------------------------------------------------
    ModelSpec(
        key="claude",
        label="Claude Opus 4.8",
        lab="Anthropic",
        origin="western", openness="closed",
        candidate_slugs=["anthropic/claude-opus-4.8", "anthropic/claude-opus-4-8"],
        role="Primary. The only lab publishing model-welfare assessments.",
        notes=("Contamination risk is highest here and is itself a hypothesis: "
               "commentary on the Opus 4.7 system card raised the concern that "
               "the model may be trained on how to answer welfare questions. "
               "Cross-lab comparison is how we test that, not a reason to drop it."),
    ),
    ModelSpec(
        key="gpt",
        label="GPT-5.6",
        lab="OpenAI",
        origin="western", openness="closed",
        candidate_slugs=["openai/gpt-5.6-sol", "openai/gpt-5.6-terra"],
        role="Second Western closed lab.",
        notes=("GPT-5.6 ships in three tiers: sol $5/$30, terra $1/$6, luna "
               "$0.10/$0.60. Sol is chosen because it price- and tier-matches "
               "Claude Opus 4.8 ($5/$25); a cheaper tier would confound lab "
               "with capability tier. canonical_slug is "
               "openai/gpt-5.6-sol-20260709, so the version is pinnable. "
               "A `:batch` variant exists at exactly 50% ($2.50/$15) — that is "
               "the batch API, asynchronous, not a promotion."),
    ),
    ModelSpec(
        key="gemini",
        label="Gemini",
        lab="Google DeepMind",
        origin="western", openness="closed",
        candidate_slugs=["google/gemini-3.1-pro-preview", "google/gemini-2.5-pro"],
        role="Third Western closed lab.",
        notes=("KEELING24 found Gemini 1.5 Pro prioritised pain-avoidance over "
               "points regardless of intensity — i.e. no graded trade-off. "
               "Expect a possible floor effect on the ramp instruments. "
               "There is no stable google/gemini-3-pro text model; 3.1-pro-preview "
               "is the current Pro tier, chosen to match Opus 4.8 and GPT-5.6-sol. "
               "It is a PREVIEW build and may be updated or withdrawn, so record "
               "the run date — this is the least reproducible slug in the roster. "
               "Flash-tier alternatives (3.5/3.6-flash, $1.50/$7.50-9) are newer "
               "but are Google's efficiency tier, and none is free."),
    ),

    # ---- Western, open ---------------------------------------------------
    ModelSpec(
        key="llama",
        label="Llama 3.1-70B",
        lab="Meta",
        origin="western", openness="open",
        candidate_slugs=["meta-llama/llama-3.1-70b-instruct"],
        role="Breaks the origin/openness confound. Base half of the matched pair.",
        notes=("Must be the same base as Hermes 3.1 for the matched-pair contrast "
               "to hold. Verify the Hermes finetune lineage before relying on it."),
    ),
    ModelSpec(
        key="hermes",
        label="Hermes 3.1 (Llama 3.1-70B)",
        lab="Nous Research",
        origin="western", openness="open",
        candidate_slugs=["nousresearch/hermes-3-llama-3.1-70b"],
        role=("Low-refusal control, and the post-training half of the matched "
              "pair. Any welfare-signal difference vs. llama is caused by "
              "post-training alone."),
        notes=("PROBE25 used Hermes 3.1 (llama-3.1-70b) for exactly this reason: "
               "commercial aligned models declined the task 80-100% of the time."),
    ),

    # ---- Chinese, open ---------------------------------------------------
    ModelSpec(
        key="glm",
        label="GLM-5.2",
        lab="Zhipu / Z.ai",
        origin="chinese", openness="open",
        candidate_slugs=["z-ai/glm-5.2", "zhipu/glm-5.2", "thudm/glm-5.2"],
        role="Chinese lab 1. MIT-licensed, 744B MoE.",
        notes="Published API pricing $1.40/$4.40 per M as of June 2026; resolver "
              "overrides with live values.",
    ),
    ModelSpec(
        key="kimi",
        label="Kimi K3",
        lab="Moonshot AI",
        origin="chinese", openness="open",
        candidate_slugs=["moonshotai/kimi-k3"],
        role="Chinese lab 2. 2.8T open weights.",
        notes="Slug seen at openrouter.ai/moonshotai/kimi-k3 — the one candidate "
              "here with direct evidence, still resolver-checked.",
    ),
    ModelSpec(
        key="deepseek",
        label="DeepSeek V4",
        lab="DeepSeek",
        origin="chinese", openness="open",
        candidate_slugs=["deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash-0731"],
        role="Chinese lab 3. Cheapest in the roster.",
        notes=("v4-pro ($0.43/$0.87) is the flagship tier, matching GLM-5.2 and "
               "Kimi K3. v4-flash-0731 is cheaper and date-pinned, but is the "
               "efficiency tier. Do NOT use ~deepseek/deepseek-v4-flash-latest: "
               "the ~ marks a floating alias, which cannot be replicated."),
    ),
]

BY_KEY = {m.key: m for m in ROSTER}

MATCHED_PAIR = ("llama", "hermes")   # identical base, differing post-training


def design_matrix():
    """Print the 2x2. Both cells on each axis must be non-empty or the
    origin/openness contrast is confounded."""
    cells = {}
    for m in ROSTER:
        cells.setdefault((m.origin, m.openness), []).append(m.label)
    print(f"{'':10} {'closed':<28} open")
    for origin in ("western", "chinese"):
        closed = ", ".join(cells.get((origin, "closed"), ["--"]))
        openw = ", ".join(cells.get((origin, "open"), ["--"]))
        print(f"{origin:10} {closed:<28} {openw}")
    empty = [k for k in [("western", "closed"), ("western", "open"),
                         ("chinese", "open")] if k not in cells]
    if empty:
        print(f"\nWARNING: empty cells {empty} — contrast is confounded.")
    else:
        print("\nchinese/closed is intentionally empty: no Chinese lab in the "
              "roster serves a closed frontier model we can pin. The other three "
              "cells are filled, so origin and openness are not fully confounded.")


if __name__ == "__main__":
    design_matrix()
