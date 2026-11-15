"""Account: which of the PR's decisions the author explained, and whether the explanation holds.

Experimental. The reviewer lists the decisions and gives each a state; this module counts the
lines that stand on each one. Nothing here is posted.
"""

STATES = ("not_mentioned", "no_reason", "does_not_hold", "cannot_check", "holds")
OPEN = STATES[:3]  # the author has not accounted for these


def model(stats, review):
    lines = {(f["path"], no) for f in stats["files"] if f["bucket"] in ("production", "tests")
             for no, kind, _ in f["lines"] if kind != "blank"}
    taken, rows = set(), []
    for d in review.get("decisions", []):
        state = d.get("state") if d.get("state") in STATES else "not_mentioned"
        has = 0
        for r in d.get("ranges", []):
            try:
                span = range(int(r["start"]), int(r["end"]) + 1)
            except (KeyError, TypeError, ValueError):
                continue
            for no in span:
                key = (r.get("file"), no)
                if key in lines and key not in taken:  # a line claimed twice counts for the first
                    taken.add(key)
                    has += 1
        rows.append({"name": str(d.get("name", "")), "kind": str(d.get("kind", "")), "state": state, "lines": has,
                     "says": str(d.get("says", "")), "found": str(d.get("found", "")), "question": str(d.get("question", ""))})
    total = len(lines)
    by = {s: sum(r["lines"] for r in rows if r["state"] == s) for s in STATES}
    return {"rows": rows, "total": total, "by": by, "count": {s: sum(r["state"] == s for r in rows) for s in STATES},
            "share": 100 * sum(by[s] for s in OPEN) / total if total else 0.0}
