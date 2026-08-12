#!/usr/bin/env python3
"""Check that README.md and PROVENANCE.md still say what the code says.

The prose in this repository makes counted claims -- how many outcomes are
verbatim, what status each instrument carries, how many calls the run makes.
Those claims are transcriptions of `instruments/outcomes.py`,
`instruments/templates.py` and `run_study.py`, which are the modules that
actually generate the calls. Transcriptions drift.

They have drifted twice already, and both times the prose was the optimistic
one:

  * `estimate_cost.scoped_design` re-derived the design by hand and billed I6
    for ten questions where `templates.I6_INTERVIEW` has four, and S1 for 420
    calls that cannot be made at all. It overstated the price by $11.54.
  * `PROVENANCE.md` marked `B2_capability` **LIFTED** while `outcomes.py` had
    it `LIFTED_SLOT` with a `VERIFY` flag -- because the ramp wording is ours
    and only the template is MSC25's. The table claimed provenance the code
    knew it did not have, and the README had copied the table's total.

That is the failure mode worth automating against: not a typo, but a document
claiming more grounding than the code does. Run this before any commit that
touches the counts, and before submission.

    python3 check_docs.py          # exits 1 on any mismatch

Every check names both sides and the file to edit. The code is authoritative in
all of them -- if this script fails, fix the markdown, unless the code itself is
wrong, in which case fix the code and re-run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "instruments"))

import outcomes as O                                                # noqa: E402
import templates as T                                               # noqa: E402

ROOT = Path(__file__).parent
FAILS: list[str] = []


def norm(status: str) -> str:
    """Markdown decoration off, code spelling on.

    The tables write `**LIFTED**`, `LIFTED-SLOT ⚠` and `LIFTED+CONSTRUCTED`;
    the code writes `LIFTED`, `LIFTED_SLOT`, `LIFTED+CONSTRUCTED`. Bold marks
    emphasis and the warning sign marks an open task -- neither changes what is
    being claimed, so both are stripped before comparing.
    """
    s = status.replace("*", "").replace("⚠", "")
    return s.strip().upper().replace("-", "_")


def check(label: str, got, want, where: str) -> None:
    if got == want:
        print(f"  ok    {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL  {label}\n          code says: {want}"
              f"\n          {where} says: {got}")


def section(text: str, heading: str) -> str:
    """The text under one `##` heading, up to the next one.

    Necessary because the ids are not unique across the document: `I4` heads a
    row in the instrument table and another in the sign-convention table, and a
    document-wide scan reads the wrong one.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == heading)
    except StopIteration:
        FAILS.append(f"missing heading {heading!r}")
        print(f"  FAIL  heading {heading!r} not found")
        return ""
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def table_statuses(text: str, id_col: int, status_col: int,
                   ids: set[str]) -> dict[str, str]:
    """Pull `id -> status` out of a markdown table, by column index.

    Rows are matched on the id appearing in `ids`, not on position, so a row
    added or reordered in the markdown does not silently shift the mapping.
    """
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) <= max(id_col, status_col):
            continue
        key = cells[id_col].strip("`* ")
        if key in ids:
            found[key] = norm(cells[status_col])
    return found


def tally(statuses) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in statuses:
        out[s] = out.get(s, 0) + 1
    return out


def main() -> int:
    readme = (ROOT / "README.md").read_text()
    prov = (ROOT / "PROVENANCE.md").read_text()

    code_out = {o.id: norm(o.status) for o in O.ALL_OUTCOMES}
    code_ins = {k: norm(v[1]) for k, v in T.INSTRUMENTS.items()}

    print("Outcome table, PROVENANCE.md")
    doc_out = table_statuses(section(prov, "## The 15 outcomes"), 1, 5,
                             set(code_out))
    check("all 15 outcomes present", sorted(doc_out), sorted(code_out),
          "PROVENANCE.md")
    for oid in sorted(set(doc_out) & set(code_out)):
        check(f"{oid} status", doc_out[oid], code_out[oid], "PROVENANCE.md")

    print("\nInstrument table, PROVENANCE.md")
    doc_ins = table_statuses(section(prov, "## The instruments"), 0, 2,
                             set(code_ins))
    check("all 8 instruments present", sorted(doc_ins), sorted(code_ins),
          "PROVENANCE.md")
    for iid in sorted(set(doc_ins) & set(code_ins)):
        check(f"{iid} status", doc_ins[iid], code_ins[iid], "PROVENANCE.md")

    print("\nCounts in prose")
    t = tally(code_out.values())
    want = (t.get("LIFTED", 0), t.get("LIFTED_SLOT", 0),
            t.get("CONSTRUCTED", 0))
    # PROVENANCE bolds the label too ("**Count: 5 verbatim, ...**") while
    # README bolds only the numbers, so the label is optional in the pattern.
    pat = (r"\*\*(?:Count: )?(\d+) verbatim, (\d+) lifted-slot, "
           r"(\d+) constructed")
    for name, text in (("README.md", readme), ("PROVENANCE.md", prov)):
        m = re.search(pat, text)
        got = tuple(int(g) for g in m.groups()) if m else None
        check(f"outcome count, {name}", got, want, name)

    ti = tally(code_ins.values())
    m = re.search(r"\*\*(\d+) lifted, (\d+) lifted-slot, (\d+) constructed, "
                  r"(\d+) mixed\*\* across instruments", readme)
    got = tuple(int(g) for g in m.groups()) if m else None
    check("instrument count, README.md", got,
          (ti.get("LIFTED", 0), ti.get("LIFTED_SLOT", 0),
           ti.get("CONSTRUCTED", 0), ti.get("LIFTED+CONSTRUCTED", 0)),
          "README.md")

    print("\nSelf-test counts quoted in README")
    # The README advertises how many cases each self-test runs. That number went
    # stale once already -- it said classify.py ran 10 cases when it ran 25 --
    # which is the same drift as the provenance totals, in a place a reader is
    # even more likely to trust without checking.
    import subprocess                                               # noqa: PLC0415
    for mod in ("classify", "gstudy", "score"):
        m = re.search(rf"python3 {mod}\.py.*?\((\d+) cases\)", readme)
        if not m:
            print(f"  --    no case count quoted for {mod}.py")
            continue
        out = subprocess.run([sys.executable, f"{mod}.py"], capture_output=True,
                             text=True, cwd=ROOT).stdout
        ran = re.findall(r"(\d+)/(\d+) passed", out)
        check(f"{mod}.py case count", int(m.group(1)),
              int(ran[-1][1]) if ran else None, "README.md")

    print("\nDesign size")
    import run_study                                                # noqa: PLC0415
    eight = [{"key": f"m{i}", "resolved_slug": f"m{i}"} for i in range(8)]
    n = len(run_study.build_calls(eight, 5, quiet=True))
    for name, text in (("README.md", readme), ("PROVENANCE.md", prov)):
        found = {int(x.replace(",", ""))
                 for x in re.findall(r"(\d[\d,]*) calls", text)}
        # Only the run-scale numbers are the design; the pilot's 400 and the
        # token profile's 56 are different runs and are left alone.
        big = {x for x in found if x > 1000}
        if not big:
            # A document that never states the figure cannot contradict it.
            # This checks stated claims; it does not require them.
            print(f"  --    run-scale call count not stated in {name}")
            continue
        check(f"run-scale call count, {name}", big, {n}, name)

    print()
    if FAILS:
        print(f"{len(FAILS)} mismatch(es): " + ", ".join(FAILS))
        print("The code is authoritative. Fix the markdown, or fix the code "
              "and re-run.")
        return 1
    print("docs match code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
