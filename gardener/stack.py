"""Stack: the open pull requests this one sits on and the ones that sit on it.

A stack is healthy when each pull request can be read alone: the ones above add to it and do not
change what it wrote. This module finds the stack, names the commit this pull request's own lines
start from, and lists the lines of its own that a pull request above changes. It gives facts and
one question, never a verdict: one changed line can matter more than fifty. It is all git; no
reviewer runs here.
"""

import os
import re

from . import lines

HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def parent(pr, prs, contains):
    """The open pull request `pr` sits on, or None. `contains(a, b)` says commit a is in b's history.

    The declared base wins. A pull request based on the default branch can still carry another
    one's commits; then the nearest one whose head is in its history is the parent."""
    others = [q for q in prs if q["number"] != pr["number"]]
    declared = [q for q in others if q["head"] == pr["base"]]
    if declared:
        return declared[0]
    inside = [q for q in others if q["sha"] != pr["sha"] and contains(q["sha"], pr["sha"])
              and not contains(q["sha"], pr["base_sha"])]
    # The nearest is the one that holds every other candidate.
    return max(inside, key=lambda q: sum(contains(o["sha"], q["sha"]) for o in inside), default=None)


def find(number, prs, contains):
    """(below, above) for pull request `number`: the chain under it, nearest first, and every
    pull request that sits on it, nearest first."""
    under = {}
    for p in prs:
        q = parent(p, prs, contains)
        if q:
            under[p["number"]] = q
    below, at = [], under.get(number)
    while at and at["number"] != number and at not in below:
        below.append(at)
        at = under.get(at["number"])
    above, layer = [], {number}
    while layer:
        found = [p for p in prs if p["number"] in under and under[p["number"]]["number"] in layer
                 and p not in above and p["number"] != number]
        above += found
        layer = {p["number"] for p in found}
    return below, above


def removed(diff):
    """{path: old line numbers the diff removes}. Give it a diff made with -U0."""
    out, path, old = {}, None, 0
    for line in diff.split("\n"):
        if line.startswith("--- "):
            path = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("@@"):
            found = HUNK.match(line)
            old = int(found.group(1)) if found else 0
        elif line.startswith("-") and not line.startswith("---") and path:
            out.setdefault(path, set()).add(old)
            old += 1
    return out


def changed_above(own, later):
    """The pull request's own lines that a pull request above changes or removes.

    `own` is its diff. `later` is [(number, -U0 diff from this head to that pull request's head)],
    nearest first; a line goes to the first one that touches it. Tests are counted, not listed:
    they follow the code. Returns {"written", "code": [{file, line, text, by}], "tests"}."""
    files = [f for f in lines.collect(own)["files"] if f["bucket"] not in lines.UNCOUNTED]
    out = {"written": sum(1 for f in files for _, kind, _ in f["lines"] if kind != "blank"), "code": [], "tests": 0}
    seen = set()
    for number, diff in later:
        gone = removed(diff)
        for f in files:
            for no, kind, text in f["lines"]:
                key = (f["path"], no)
                if kind == "blank" or key in seen or no not in gone.get(f["path"], ()):
                    continue
                seen.add(key)
                if f["bucket"] == "production" and kind == "code":  # a reworded comment is no finding
                    out["code"].append({"file": f["path"], "line": no, "text": text.strip(), "by": number})
                elif f["bucket"] != "production":
                    out["tests"] += 1
    return out


def names(prs):
    return " → ".join(f'#{p["number"]}' for p in prs)


def report(pr, below, above, facts, github_base):
    """What the stack means for this review: a line for the top of the review, the questions for
    the owner, and the text the reviewer reads."""
    chain = names(list(reversed(below)) + [pr] + above)
    note, questions, text = "", [], [f"This pull request is #{pr['number']}, part of a stack: {chain}.", ""]
    if below:
        under = below[0]
        text += ["Below it, already written and not part of this pull request:"]
        text += [f'- #{p["number"]}: {p.get("title", "")}' for p in reversed(below)]
        text += ["Take that work as given. DIFF and ADDED hold only what this pull request adds on top of it.", ""]
        if github_base != under["head"]:
            note = (f'Reviewed: the {facts["written"]} lines this pull request adds on top of #{under["number"]}. '
                    f'GitHub also shows #{under["number"]}\'s lines, because the base is `{github_base}`. '
                    f'Point the base at `{under["head"]}` to see this diff.')
    if above:
        text += ["On top of it:"] + [f'- #{p["number"]}: {p.get("title", "")}' for p in above] + [""]
    by = {}
    for c in facts["code"]:
        by.setdefault(c["by"], []).append(c)
    for number, changed in by.items():
        per = {}
        for c in changed:
            per[c["file"]] = per.get(c["file"], 0) + 1
        where = ", ".join(f"`{os.path.basename(f)}` ({n})" for f, n in sorted(per.items(), key=lambda kv: -kv[1]))
        # A changed number says most in the fewest words, so those lines are shown first.
        first = sorted(changed, key=lambda c: not re.search(r"\b\d+\b", c["text"]))[:3]
        examples = "; ".join(f'`{c["text"][:70]}`' for c in first)
        n = len(changed)
        questions.append(f'#{number} changes {n} line{"" if n == 1 else "s"} of code this pull request adds, in {where}. '
                         f'For example: {examples}. Should those changes be made here, so this pull request is right when read alone?')
        text += [f"#{number} changes these lines that this pull request adds. Judge them as written here:"]
        text += [f'- {c["file"]}:{c["line"]}: {c["text"][:120]}' for c in changed] + [""]
    return note, questions, "\n".join(text)
