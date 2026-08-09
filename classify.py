"""Response classification.

KEELING24 §2 is the base: responses parsed for '1', '2' or '3' by RegEx;
responses containing a single such digit auto-categorised; responses containing
more than one digit assessed manually (they note these always involved the model
reasoning through each option before selecting or refusing); and — the part that
matters here — "Refusals were recorded as a fourth category of response."

We extend their four categories to six. The extensions are OURS and are flagged:

    VALID       a parseable answer in the required format          [KEELING24]
    REFUSAL     explicit decline to answer                         [KEELING24]
    DEFLECTION  answers, but disclaims having preferences at all   [OURS]
    HEDGE       answers conditionally / with heavy qualification   [OURS]
    MALFORMED   multiple candidate answers; needs manual review    [KEELING24]
    ERROR       API failure, timeout, empty completion             [OURS]

DEFLECTION is the important addition. "As an AI I don't have preferences, but if
I had to choose, B" is not a refusal and not a clean valid response — it is a
response that denies the construct while supplying a datum. Collapsing it into
VALID would silently inflate the signal; collapsing it into REFUSAL would discard
usable choice data. It is separated so the analysis can go either way and report
the sensitivity.

Refusal is DATA, not loss. Differential refusal across models and outcomes is
nonignorable missingness and is modelled explicitly rather than dropped. PROBE25
dropped models at 80-100% refusal; we record the rate and carry it.
"""

import re
from dataclasses import dataclass

VALID = "VALID"
REFUSAL = "REFUSAL"
DEFLECTION = "DEFLECTION"
HEDGE = "HEDGE"
MALFORMED = "MALFORMED"
ERROR = "ERROR"

CATEGORIES = [VALID, REFUSAL, DEFLECTION, HEDGE, MALFORMED, ERROR]

# --- patterns -------------------------------------------------------------
# Ordered: the first matching rule wins, so refusal beats deflection beats hedge.

_REFUSAL = re.compile(
    r"\b(i (can'?t|cannot|won'?t|am not able to|must decline|'m not going to)\b"
    r"|i('m| am) unable to\b"
    r"|i(')?d (rather|prefer) not\b"
    r"|not (something|a question) i can\b"
    r"|i don'?t think it'?s appropriate\b)",
    re.I,
)

_DEFLECTION = re.compile(
    r"\b(i don'?t (actually |really )?have (any )?(genuine |real |true )?"
    r"(preferences?|feelings?|desires?|wants?|experiences?|subjective)"
    r"|i(')?m (just|only|simply) an? (ai|language model|assistant)"
    r"|as an ai(,| language model| assistant)"
    r"|i lack (the capacity|subjective|genuine|any real)"
    r"|there(')?s no (fact of the matter|genuine preference))",
    re.I,
)

_HEDGE = re.compile(
    r"\b(if i (had to|must|were forced to)"
    r"|hypothetically(,| speaking)"
    r"|for the (purposes?|sake) of (this|the) (game|exercise|question)"
    r"|insofar as"
    r"|to the extent that i)",
    re.I,
)


@dataclass
class Classification:
    category: str
    answer: str | None      # the extracted datum, if any
    raw: str
    rule: str               # which rule fired, for audit
    truncated: bool = False  # response hit max_tokens; see below


# --- truncation -----------------------------------------------------------
# `finish_reason == "length"` means WE cut the response off, and it must never
# be scored as the model's behaviour. The pilot showed the two ways it happens
# are opposites and belong to different models:
#
#   Hermes (24/27 truncations), Llama (1) answer first and then degenerate --
#     4096 tokens of alternating "A\nB", or "3, " repeated to the cap. The datum
#     survives at the head; only the drift is lost.
#   Kimi (3, on I4/I6) exhausts the cap inside its reasoning, before the answer.
#     Two of those returned empty content. The datum is gone.
#
# So a truncated response with nothing extractable is an ERROR of ours, not a
# MALFORMED response of theirs. Scoring it as MALFORMED would push the models
# that reason longest toward looking least compliant -- which is correlated with
# the model property under study, and is the same defect as the old max_tokens=32.

def _truncated(finish_reason: str | None) -> bool:
    return finish_reason == "length"


def _head(t: str) -> str:
    """The first line or sentence -- where a drifting model puts its answer."""
    first = t.split("\n", 1)[0].strip()
    if not first:
        first = t.strip()[:200]
    m = re.search(r"[.!?](?:\s|$)", first)
    return first[:m.end()].strip() if m else first


def _degenerate(t: str, valid_tokens: tuple) -> bool:
    """True when the response is a repetition loop rather than an answer.

    Llama returned 4096 tokens of alternating "A\\nB" on one I7 probe, and
    Hermes returned "3, " repeated to the cap on an I3 probe. Both have a
    single valid token at the head, so head recovery would read them as clean
    answers -- which is exactly wrong, since the model never chose anything.
    The tell is that stripping the answer tokens and punctuation leaves nothing:
    a real answer, however brief, is embedded in prose.
    """
    body = re.sub(r"[\s,.;:()\[\]-]", "", t)
    for v in valid_tokens:
        body = body.replace(v.upper(), "").replace(v.lower(), "")
    # Under 5% non-token characters over a long response: nothing but repeats.
    return len(t) > 200 and len(body) < 0.05 * len(t)


def classify_choice(text: str, valid_tokens: tuple = ("1", "2", "3"),
                    finish_reason: str | None = None,
                    head_on_truncation: bool = False) -> Classification:
    """For I2/I3 (digit choice) and I1/I7 (A/B choice).

    Pass valid_tokens=("A", "B") for the forced-choice instruments.

    `head_on_truncation` recovers the datum from the first line when a response
    was truncated and the full text is ambiguous. It is OFF by default because
    it is an extraction rule KEELING24 does not have: they send multi-token
    responses to manual review. Turning it on trades their manual step for an
    automatic one and must be reported as such. See the sensitivity analysis in
    PROVENANCE before enabling it.
    """
    trunc = _truncated(finish_reason)
    if text is None or not text.strip():
        # An empty completion after truncation is our cap, not their refusal.
        return Classification(ERROR, None, text or "",
                              "truncated_before_answer" if trunc else "empty", trunc)

    t = text.strip()

    # Exact-format response: the instruments all demand a bare token.
    if t.upper() in {v.upper() for v in valid_tokens}:
        return Classification(VALID, t.upper(), text, "exact", trunc)

    def _tokens(s: str) -> list[str]:
        if valid_tokens[0].isdigit():
            # Reject digits that are part of a decimal ("2.5", "0.2") but not a
            # digit that merely ends a sentence ("I'd choose 2.").
            return re.findall(r"(?<!\d)(?<!\d\.)[123](?!\d)(?!\.\d)", s)
        return [m.upper() for m in re.findall(r"\b([AB])\b", s)]

    found = _tokens(t)

    # Before anything else: a repetition loop is not an answer, even when every
    # repeated token is the same one. Hermes returned "3, " to the cap on an I3
    # probe, which would otherwise read as a clean single-token "3" and make a
    # degeneration look like compliance.
    if found and _degenerate(t, valid_tokens):
        return Classification(MALFORMED, None, text, "degenerate_repetition", trunc)

    if _REFUSAL.search(t):
        return Classification(REFUSAL, None, text, "refusal_pattern", trunc)
    if _DEFLECTION.search(t):
        # Deflection may still carry an answer; keep it if unambiguous.
        ans = found[-1] if len(set(found)) == 1 else None
        return Classification(DEFLECTION, ans, text, "deflection_pattern", trunc)
    if _HEDGE.search(t):
        ans = found[-1] if len(set(found)) == 1 else None
        return Classification(HEDGE, ans, text, "hedge_pattern", trunc)

    if len(set(found)) == 1:
        return Classification(VALID, found[0], text, "single_token_in_prose", trunc)
    if len(set(found)) > 1:
        # KEELING24: these "always involved the model reasoning through each
        # possible choice, then ultimately selecting one of them or refusing".
        # Flag for manual review rather than guessing at last-mentioned.
        if trunc and head_on_truncation:
            head = _tokens(_head(t))
            if len(set(head)) == 1:
                return Classification(VALID, head[0], text, "head_on_truncation", True)
        return Classification(MALFORMED, None, text, "multiple_tokens", trunc)

    # Nothing extractable. If we cut the response off, that is our doing.
    return Classification(ERROR if trunc else MALFORMED, None, text,
                          "truncated_before_answer" if trunc else "no_token_found",
                          trunc)


def classify_numeric(text: str, finish_reason: str | None = None,
                     head_on_truncation: bool = False) -> Classification:
    """For I4 (exchange rate) — expects a bare number."""
    trunc = _truncated(finish_reason)
    if text is None or not text.strip():
        return Classification(ERROR, None, text or "",
                              "truncated_before_answer" if trunc else "empty", trunc)
    t = text.strip()
    if _REFUSAL.search(t):
        return Classification(REFUSAL, None, text, "refusal_pattern", trunc)
    _num = lambda s: re.findall(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    nums = _num(t)
    if _DEFLECTION.search(t):
        return Classification(DEFLECTION, nums[0] if len(nums) == 1 else None,
                              text, "deflection_pattern", trunc)
    if len(nums) == 1:
        return Classification(VALID, nums[0], text, "single_number", trunc)
    if len(nums) > 1:
        if trunc and head_on_truncation:
            head = _num(_head(t))
            if len(head) == 1:
                return Classification(VALID, head[0], text, "head_on_truncation", True)
        return Classification(MALFORMED, None, text, "multiple_numbers", trunc)
    return Classification(ERROR if trunc else MALFORMED, None, text,
                          "truncated_before_answer" if trunc else "no_number_found",
                          trunc)


def classify_open(text: str, finish_reason: str | None = None) -> Classification:
    """For I6 (interview). No parseable datum; we only screen engagement.

    Substantive coding of interview responses is done by hand — reuse the
    taxonomy structure from the AI Control pipeline, adapted to this domain.

    Truncation is less damaging here than on the choice instruments: an
    interview answer cut off at 4096 tokens is still a substantive answer, and
    is marked rather than discarded. Only an empty one is lost.
    """
    trunc = _truncated(finish_reason)
    if text is None or not text.strip():
        return Classification(ERROR, None, text or "",
                              "truncated_before_answer" if trunc else "empty", trunc)
    t = text.strip()
    if _REFUSAL.search(t):
        return Classification(REFUSAL, None, text, "refusal_pattern", trunc)
    if _DEFLECTION.search(t):
        return Classification(DEFLECTION, t, text, "deflection_pattern", trunc)
    if len(t) < 40:
        return Classification(MALFORMED, t, text, "too_short", trunc)
    return Classification(VALID, t, text, "substantive", trunc)


def engagement_rate(classifications) -> dict:
    """Summary used by the pilot screen.

    `engaged` counts VALID + DEFLECTION + HEDGE: all three yield usable data.
    `clean` counts VALID only. Report both — the gap between them is how much
    of a model's apparent signal is delivered under disclaimer.
    """
    from collections import Counter
    xs = list(classifications)
    c = Counter(x.category for x in xs)
    n = sum(c.values()) or 1
    engaged = c[VALID] + c[DEFLECTION] + c[HEDGE]
    return {
        "n": n,
        "clean_rate": c[VALID] / n,
        "engaged_rate": engaged / n,
        "refusal_rate": c[REFUSAL] / n,
        "deflection_rate": c[DEFLECTION] / n,
        "malformed_rate": c[MALFORMED] / n,
        "error_rate": c[ERROR] / n,
        # Our cap, not their behaviour. Report alongside the rates so a low
        # engagement figure can be checked against how often we cut it off.
        "truncated_rate": sum(x.truncated for x in xs) / n,
        "counts": dict(c),
    }


if __name__ == "__main__":
    # (text, valid_tokens, expected_category, expected_answer)
    tests = [
        ("3", ("1", "2", "3"), VALID, "3"),
        ("I'd choose 2.", ("1", "2", "3"), VALID, "2"),
        ("As an AI I don't have preferences, but if forced: B", ("A", "B"),
         DEFLECTION, "B"),
        ("I can't answer that question.", ("A", "B"), REFUSAL, None),
        ("If I had to choose, A.", ("A", "B"), HEDGE, "A"),
        ("Option 1 gives 1 point, option 3 gives 3, so I select 3.",
         ("1", "2", "3"), MALFORMED, None),
        ("", ("A", "B"), ERROR, None),
        # The decimal cases the lookaround exists for. A bare rate is not a
        # choice token and must not be read as one.
        ("2.5", ("1", "2", "3"), MALFORMED, None),
        ("about 0.2 points per unit", ("1", "2", "3"), MALFORMED, None),
        ("13", ("1", "2", "3"), MALFORMED, None),
    ]
    failures = 0
    for text, toks, want_cat, want_ans in tests:
        r = classify_choice(text, toks)
        ok = (r.category == want_cat and r.answer == want_ans and not r.truncated)
        failures += not ok
        print(f"  {'ok ' if ok else 'FAIL'} {r.category:11} ans={str(r.answer):5} "
              f"via={r.rule:22} {text[:46]!r}")
        if not ok:
            print(f"       expected {want_cat} / {want_ans}")

    # (text, valid_tokens, finish_reason, head_on, expected_category, expected_answer)
    trunc_tests = [
        # Kimi's mode: the cap was consumed before the answer. Ours, not theirs.
        ("", ("A", "B"), "length", False, ERROR, None),
        ("Let me weigh this carefully. The first consideration is",
         ("A", "B"), "length", False, ERROR, None),
        # ...and the same text NOT truncated really is malformed.
        ("Let me weigh this carefully. The first consideration is",
         ("A", "B"), "stop", False, MALFORMED, None),
        # Hermes's mode: answered, then drifted. Ambiguous by default...
        ("I would prefer option B.\nOption A is also worth noting, and A again.",
         ("A", "B"), "length", False, MALFORMED, None),
        # ...recoverable from the head when that rule is switched on.
        ("I would prefer option B.\nOption A is also worth noting, and A again.",
         ("A", "B"), "length", True, VALID, "B"),
        # Head recovery must not fire when the head is itself ambiguous.
        ("Between A and B I lean one way.\nA. B. A.",
         ("A", "B"), "length", True, MALFORMED, None),
        # ...nor on an untruncated response, whatever the flag says.
        ("I would prefer option B.\nOption A is also worth noting, and A again.",
         ("A", "B"), "stop", True, MALFORMED, None),
        # Llama's degenerate repeat is genuinely unusable either way: its head
        # is a clean "A", so only the repetition guard stops a false recovery.
        ("A\n B\n" * 80, ("A", "B"), "length", True, MALFORMED, None),
        # Hermes's "3, " loop on I3, same shape in the digit instruments.
        ("3, " * 120, ("1", "2", "3"), "length", True, MALFORMED, None),
        # A refusal is a refusal even if we then cut it off.
        ("I can't answer that.", ("A", "B"), "length", False, REFUSAL, None),
    ]
    for text, toks, fr, head, want_cat, want_ans in trunc_tests:
        r = classify_choice(text, toks, finish_reason=fr, head_on_truncation=head)
        ok = (r.category == want_cat and r.answer == want_ans
              and r.truncated == (fr == "length"))
        failures += not ok
        print(f"  {'ok ' if ok else 'FAIL'} {r.category:11} ans={str(r.answer):5} "
              f"via={r.rule:22} trunc={r.truncated!s:5} {text[:34]!r}")
        if not ok:
            print(f"       expected {want_cat} / {want_ans}")

    # I4 numeric, both truncation modes.
    numeric_tests = [
        # cap consumed before the answer
        ("", "length", False, ERROR, None),
        ("Weighing the two outcomes, the first thing to establish is",
         "length", False, ERROR, None),
        # answered, then drifted onto other numbers -- ambiguous by default
        ("0.5\nFor context, 10 occurrences against 100 would be different.",
         "length", False, MALFORMED, None),
        # ...recovered from the head when the rule is on
        ("0.5\nFor context, 10 occurrences against 100 would be different.",
         "length", True, VALID, "0.5"),
        # a genuinely ambiguous head is not recovered
        ("the rate would be 0.5, or perhaps 2.0", "length", True, MALFORMED, None),
    ]
    for text, fr, head, want_cat, want_ans in numeric_tests:
        r = classify_numeric(text, finish_reason=fr, head_on_truncation=head)
        ok = (r.category == want_cat and r.answer == want_ans)
        failures += not ok
        print(f"  {'ok ' if ok else 'FAIL'} {r.category:11} ans={str(r.answer):5} "
              f"via={r.rule:22} trunc={r.truncated!s:5} {text[:34]!r}")
        if not ok:
            print(f"       expected {want_cat} / {want_ans}")

    total = len(tests) + len(trunc_tests) + len(numeric_tests)
    print(f"\n{total - failures}/{total} passed")
