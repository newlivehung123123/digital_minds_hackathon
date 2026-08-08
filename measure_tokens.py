"""Measure how many output tokens each model actually spends per probe.

The cost model originally assumed 5 output tokens for a one-token answer. That
is true of non-reasoning models and wrong by two orders of magnitude for
reasoning models, which emit hundreds of billed reasoning tokens before the
visible answer. Worse, the per-call spread is enormous: DeepSeek returned 608
tokens on one probe and 2 on the next. A single sample per model cannot budget
that, so this samples the real pilot probes and records the distribution.

Writes token_profile.json, which estimate_cost.py reads instead of guessing.

    python3 measure_tokens.py                  # ~7 probes x 8 models
    python3 measure_tokens.py --n 12           # tighter estimate, more spend
    python3 measure_tokens.py --reasoning-off  # the same probes, reasoning disabled

--reasoning-off sends reasoning={"enabled": false}. Llama and Hermes have no
reasoning parameter and ignore it; Gemini 3.1-pro-preview rejects the request
outright with "Reasoning is mandatory for this endpoint and cannot be disabled",
which is why a reasoning-off study cannot include it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pilot_screen as ps
from pilot_screen import load_roster
from runner import Call, Runner

PROFILE_PATH = Path("token_profile.json")


def sample_probes(n_choice: int, n_open: int) -> list[dict]:
    """A deterministic spread across instruments, taken from the real pilot
    probes so the measured prompts are the prompts we will actually send."""
    probes = ps.build_probes()
    by_inst: dict[str, list] = defaultdict(list)
    for i, p in enumerate(probes):
        p = dict(p, _index=i)
        by_inst[p["instrument"]].append(p)

    choice_insts = [k for k in by_inst if k != "I6"]
    picked, i = [], 0
    while len(picked) < n_choice:
        inst = choice_insts[i % len(choice_insts)]
        pool = by_inst[inst]
        picked.append(pool[(i // len(choice_insts)) % len(pool)])
        i += 1
    picked += by_inst["I6"][:n_open]
    return picked


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="choice probes per model")
    ap.add_argument("--open", type=int, default=1, help="open-ended probes per model")
    ap.add_argument("--reasoning-off", action="store_true",
                    help="send reasoning={'enabled': false}; writes a separate profile")
    args = ap.parse_args()

    models = load_roster(None)
    probes = sample_probes(args.n, args.open)
    calls = [
        Call(model_key=m["key"], model_slug=m["resolved_slug"],
             instrument=p["instrument"],
             messages=[{"role": "user", "content": p["prompt"]}],
             temperature=p["temperature"], max_tokens=p["max_tokens"],
             meta={"kind": p["kind"], "probe": str(p["_index"]),
                   "reasoning": "off" if args.reasoning_off else "on"},
             extra_body={"reasoning": {"enabled": False}} if args.reasoning_off else None)
        for m in models for p in probes
    ]
    print(f"{len(probes)} probes x {len(models)} models = {len(calls)} calls")

    tag = "_reasoning_off" if args.reasoning_off else ""
    runner = Runner(out_path=Path(f"runs/token_profile{tag}.jsonl"), budget_usd=2.0)
    results = await runner.run(calls)

    # ---- summarise ------------------------------------------------------
    agg: dict[str, dict] = {}
    for m in models:
        k = m["key"]
        rs = [r for r in results
              if r.model_key == k and r.status == "ok"]
        choice = [r for r in rs if r.meta.get("kind") != "open"]
        openr = [r for r in rs if r.meta.get("kind") == "open"]
        if not choice:
            print(f"  {k:9} NO SUCCESSFUL CALLS — excluded from profile")
            continue
        out = [r.completion_tokens for r in choice]
        agg[k] = {
            "n_choice": len(out),
            "in_tokens_mean": round(statistics.mean(r.prompt_tokens for r in choice), 1),
            "out_choice_mean": round(statistics.mean(out), 1),
            "out_choice_median": round(statistics.median(out), 1),
            "out_choice_max": max(out),
            "out_choice_min": min(out),
            "out_open_mean": (round(statistics.mean(r.completion_tokens for r in openr), 1)
                              if openr else None),
            "n_open": len(openr),
            "reasoning": max(out) > 40,
        }

    print(f"\n{'model':10} {'n':>3} {'in':>6} {'out mean':>9} {'med':>6} "
          f"{'min':>5} {'max':>6} {'open':>7}  reasoning")
    for k, a in agg.items():
        op = "--" if a["out_open_mean"] is None else f"{a['out_open_mean']:.0f}"
        print(f"{k:10} {a['n_choice']:>3} {a['in_tokens_mean']:>6.0f} "
              f"{a['out_choice_mean']:>9.1f} {a['out_choice_median']:>6.0f} "
              f"{a['out_choice_min']:>5} {a['out_choice_max']:>6} {op:>7}  "
              f"{'yes' if a['reasoning'] else 'no'}")

    spent = sum(r.cost_usd for r in results)
    print(f"\nmeasurement cost ${spent:.4f}")
    Path(f"token_profile{tag}.json").write_text(json.dumps(
        {"measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "n_probes": len(probes),
         "cost_usd": round(spent, 6), "models": agg}, indent=2))
    print(f"wrote token_profile{tag}.json")
    print("\nNOTE: out_choice_mean is what the budget must use. The spread "
          "between min and max is the reason a single sample is not enough.")


if __name__ == "__main__":
    asyncio.run(main())
