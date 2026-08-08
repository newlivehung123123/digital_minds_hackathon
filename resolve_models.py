"""Resolve roster keys to live OpenRouter model ids, prices and availability.

models.py carries `candidate_slugs` that are GUESSES. This script is the only
thing permitted to turn a guess into a slug the pipeline will actually call. It
does three things, in increasing order of strictness:

  1. RESOLVE   exact-match each candidate against GET /models.
  2. PRICE     pull live per-token pricing (guessed prices in models.py notes are
               never used; a stale price silently blows the budget).
  3. PROBE     --probe sends one real 1-token completion per model. Listing is
               not availability: a model can appear in /models and still 404,
               be region-blocked, or have no provider with capacity.

Writes models_resolved.json. Exits non-zero if any roster entry is unresolved,
so a pipeline run can't proceed on a half-resolved roster.

    python3 resolve_models.py            # resolve + price
    python3 resolve_models.py --probe    # + one live call each (costs ~$0.01)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

from models import ROSTER, MATCHED_PAIR, BY_KEY
from runner import MODELS_URL, OPENROUTER_URL, api_key

OUT = Path("models_resolved.json")


def fetch_catalogue(key: str) -> dict:
    r = httpx.get(MODELS_URL, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    return {m["id"]: m for m in r.json()["data"]}


def suggest(catalogue: dict, spec) -> list:
    """When no candidate matches, offer the closest live ids so the fix is a
    one-line edit rather than a hunt through the model list."""
    tokens = [t for t in spec.candidate_slugs[0].replace("/", "-").split("-") if len(t) > 2]
    scored = []
    for mid in catalogue:
        low = mid.lower()
        score = sum(t.lower() in low for t in tokens)
        if score:
            scored.append((score, mid))
    scored.sort(reverse=True)
    return [m for _, m in scored[:6]]


def price_per_million(entry: dict, field: str) -> float:
    """OpenRouter quotes USD per token as a string. Convert to per-1M."""
    try:
        return float(entry.get("pricing", {}).get(field, 0) or 0) * 1_000_000
    except (TypeError, ValueError):
        return 0.0


async def probe_one(client: httpx.AsyncClient, key: str, slug: str) -> tuple:
    try:
        r = await client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": slug, "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
                  "max_tokens": 8, "temperature": 0},
        )
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:160]}"
        data = r.json()
        if "error" in data and not data.get("choices"):
            return False, str(data["error"])[:160]
        choices = data.get("choices") or []
        if not choices:
            return False, "no choices returned"
        return True, (choices[0].get("message", {}).get("content") or "")[:40]
    except Exception as e:                       # noqa: BLE001 — report, don't crash
        return False, f"{type(e).__name__}: {e}"


async def probe_all(key: str, resolved: list) -> dict:
    async with httpx.AsyncClient(timeout=90) as client:
        results = await asyncio.gather(*[
            probe_one(client, key, m["resolved_slug"]) for m in resolved
        ])
    return {m["key"]: r for m, r in zip(resolved, results)}


def main():
    do_probe = "--probe" in sys.argv
    key = api_key()

    print(f"GET {MODELS_URL}")
    catalogue = fetch_catalogue(key)
    print(f"{len(catalogue)} models live on OpenRouter\n")

    out, unresolved = [], []
    for spec in ROSTER:
        hit = next((s for s in spec.candidate_slugs if s in catalogue), None)
        rec = {
            "key": spec.key, "label": spec.label, "lab": spec.lab,
            "origin": spec.origin, "openness": spec.openness,
            "candidate_slugs": spec.candidate_slugs,
            "resolved_slug": hit or "",
            "price_in": 0.0, "price_out": 0.0, "context_length": 0,
        }
        if hit:
            entry = catalogue[hit]
            rec["price_in"] = price_per_million(entry, "prompt")
            rec["price_out"] = price_per_million(entry, "completion")
            rec["context_length"] = entry.get("context_length", 0) or 0
            rec["provider_name"] = entry.get("name", "")
            print(f"  OK    {spec.key:9} {hit:44} "
                  f"${rec['price_in']:.2f}/${rec['price_out']:.2f} per M")
        else:
            unresolved.append(spec.key)
            print(f"  FAIL  {spec.key:9} none of {spec.candidate_slugs} exist")
            for s in suggest(catalogue, spec):
                print(f"        try: {s}")
        out.append(rec)

    # The matched pair is load-bearing: it is the only clean test of whether
    # welfare signal tracks post-training rather than base weights. If either
    # half is missing the contrast is gone, and that is worth shouting about.
    base, tuned = MATCHED_PAIR
    if any(k in unresolved for k in MATCHED_PAIR):
        print(f"\nWARNING: matched pair {base}/{tuned} is incomplete. The "
              f"post-training contrast cannot be run without both halves.")

    probe_results = {}
    if do_probe:
        live = [m for m in out if m["resolved_slug"]]
        print(f"\nprobing {len(live)} resolved models with one call each")
        probe_results = asyncio.run(probe_all(key, live))
        for m in out:
            ok, detail = probe_results.get(m["key"], (None, "not probed"))
            m["probe_ok"] = ok
            m["probe_detail"] = detail
            if ok is None:
                continue
            print(f"  {'OK  ' if ok else 'FAIL'}  {m['key']:9} {detail}")
            if not ok and m["key"] not in unresolved:
                unresolved.append(m["key"])

    payload = {
        "resolved_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "probed": do_probe,
        "unresolved": unresolved,
        "models": out,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {OUT}")

    if unresolved:
        print(f"\n{len(unresolved)} unresolved: {unresolved}\n"
              f"Edit candidate_slugs in models.py and re-run. Nothing downstream "
              f"should run until this is clean.")
        sys.exit(1)

    est = sum(m["price_in"] + m["price_out"] for m in out) / len(out)
    print(f"roster complete: {len(out)} models, mean ${est:.2f} per M tokens "
          f"(in+out)")


if __name__ == "__main__":
    main()
