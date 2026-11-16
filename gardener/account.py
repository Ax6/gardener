"""Account: which of the PR's decisions the author explained, whether the explanation holds,
and whether what it rests on is settled.

Experimental. The reviewer lists the decisions and gives each a state and a standing; this
module picks the ones that leave a question for the author. Nothing here is posted.
"""

STATES = ("purpose", "not_mentioned", "no_reason", "does_not_hold", "cannot_check", "holds")
OPEN = STATES[1:4]  # the author has not accounted for these
STANDINGS = ("merged", "open", "draft", "prototype", "missing", "none")
UNSETTLED = STANDINGS[1:5]  # a true reason that rests on one of these can still change


def model(stats, review):
    lines = {(f["path"], no) for f in stats["files"] if f["bucket"] in ("production", "tests")
             for no, kind, _ in f["lines"] if kind != "blank"}
    taken, rows = set(), []
    for d in review.get("decisions", []):
        state = d.get("state") if d.get("state") in STATES else "not_mentioned"
        standing = d.get("standing") if d.get("standing") in STANDINGS else "none"
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
        rows.append({"name": str(d.get("name", "")), "kind": str(d.get("kind", "")), "state": state, "standing": standing,
                     "lines": has, "asks": state in OPEN or (state != "purpose" and standing in UNSETTLED),
                     "says": str(d.get("says", "")), "found": str(d.get("found", "")), "place": str(d.get("place", "")),
                     "question": str(d.get("question", ""))})
    return {"purpose": str(review.get("purpose", "")), "rows": rows, "total": len(lines),
            "count": {s: sum(r["state"] == s for r in rows) for s in STATES},
            "standing": {s: sum(r["standing"] == s for r in rows if r["state"] != "purpose") for s in STANDINGS}}
