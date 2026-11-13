"""Scope: how many lines the PR has against how many it needs.

The reviewer sorts everything the PR adds into pieces: a function, a module,
a column, a background task, each with the tests that exist only for it. For
each piece it says whether the purpose needs it, and if so how many lines it
would take done the way the repository already does that kind of thing.

This module counts the lines each piece really has and adds up the rest:

  not needed   the piece needs 0 lines
  oversized    the piece is needed, and has more lines than it needs
  unsure       the reviewer could not settle it; counted as needed

The reviewer sizes a piece in lines of production code only. Its tests and
comments follow the piece:

  tests      go when the piece is not needed, and stay in full when it is kept.
             Whether a kept piece has more tests than it should is the weight
             step's question, and trimming a line of code rarely removes a test.
  comments   are kept in the same share as the code they sit in.

Doc files and blank lines are not part of this count.
"""


def model(stats, review):
    lines = {}
    for f in stats["files"]:
        if f["bucket"] in ("production", "tests"):
            for no, kind, _ in f["lines"]:
                if kind != "blank":
                    lines[(f["path"], no)] = "test" if f["bucket"] == "tests" else kind  # test, code or doc

    taken, rows = set(), []
    for p in review.get("pieces", []):
        role = p.get("role") if p.get("role") in ("core", "beyond", "unsure") else "unsure"
        has = code = tests = 0
        for r in p.get("ranges", []):
            try:
                lo, hi = int(r["start"]), int(r["end"])
            except (KeyError, TypeError, ValueError):
                continue
            for no in range(lo, hi + 1):
                key = (r.get("file"), no)
                # A line claimed by two pieces counts for the first.
                if key in lines and key not in taken:
                    taken.add(key)
                    has += 1
                    code += lines[key] == "code"
                    tests += lines[key] == "test"
        if role == "beyond":
            needs = 0
        elif role == "unsure" or p.get("needs") is None:
            needs = has
        else:
            try:
                kept = min(code, max(0, int(p["needs"])))
                needs = kept + round((has - code - tests) * kept / code) + tests if code else has
            except (TypeError, ValueError):
                needs = has
        rows.append({
            "name": str(p.get("name", "")), "role": role, "has": has, "needs": needs,
            "kind": {"beyond": "Not needed", "unsure": "Unsure", "core": "Oversized"}[role],
            "why": str(p.get("needs_why") if role == "core" else p.get("stakes", "") or ""),
            "ranges": p.get("ranges", []),
        })

    has = sum(r["has"] for r in rows)
    unsure = sum(r["has"] for r in rows if r["role"] == "unsure")
    need = sum(r["needs"] for r in rows if r["role"] != "unsure")
    extra = has - need - unsure
    return {
        "purpose": str(review.get("purpose", "")),
        "decisions": [str(q) for q in review.get("decisions", [])],
        "rows": rows,
        "has": has,
        "need": need,
        "unsure": unsure,
        "extra": extra,
        "share": 100 * extra / has if has else 0.0,
        # Pieces worth showing: the ones that carry extra lines, largest first.
        "over": sorted((r for r in rows if r["has"] > r["needs"] or r["role"] == "unsure"),
                       key=lambda r: -(r["has"] - r["needs"])),
        "unplaced": len(lines) - len(taken),
    }
