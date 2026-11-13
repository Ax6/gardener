"""Put the review on the pull request, through the gh CLI.

First run: one review. Its body is the chart and the scope table; each weight
finding is a comment on the lines it is about.

Later runs: the body of that first review is rewritten in place, so the chart
stays where it is. Existing comment threads are left alone, because people may
have replied to them. Only findings with no live thread are posted.
"""

import json
import re
import subprocess
import time

from .card import OUTCOME, outcome, render
from .weight import CATEGORIES, percent

BRANCH = "gardener-assets"
STATE_RE = re.compile(r"<!-- gardener scope=([0-9.]+) weight=([0-9.]*) -->")
FINDING_MARK = "<!-- gardener-finding -->"


def gh(method, path, data=None):
    cmd = ["gh", "api", "-X", method, path] + (["--input", "-"] if data is not None else [])
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"gh api {method} {path}: {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def upload(repo, files, message):
    """Add files to the images branch in one commit, creating the branch when it is missing.
    Returns the commit sha, which the image links are pinned to."""
    r = subprocess.run(["gh", "api", f"repos/{repo}/git/ref/heads/{BRANCH}"], capture_output=True, text=True)
    tip = json.loads(r.stdout)["object"]["sha"] if r.returncode == 0 else None
    tree = [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]
    if tip:
        base = gh("GET", f"repos/{repo}/git/commits/{tip}")["tree"]["sha"]
        t = gh("POST", f"repos/{repo}/git/trees", {"base_tree": base, "tree": tree})
    else:
        tree.append({"path": "README.md", "mode": "100644", "type": "blob",
                     "content": "Chart images for Gardener reviews. Not code; nothing here is built or deployed.\n"})
        t = gh("POST", f"repos/{repo}/git/trees", {"tree": tree})
    c = gh("POST", f"repos/{repo}/git/commits", {"message": message, "tree": t["sha"], "parents": [tip] if tip else []})
    if tip:
        gh("PATCH", f"repos/{repo}/git/refs/heads/{BRANCH}", {"sha": c["sha"]})
    else:
        gh("POST", f"repos/{repo}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": c["sha"]})
    return c["sha"]


def cell(s):
    """Text made safe for one cell of a markdown table."""
    return str(s).replace("|", "\\|").replace("\r", "").replace("\n", " ").strip()


def body(sm, wm, repo, head, light, dark, cfg, note="", start=None):
    """The review body: chart, purpose, where the extra lines are, questions, weight summaries.
    The hidden first line records the scores of the first review, so later runs can show both."""
    s_state = outcome(sm["share"], cfg["scope_limits"])
    w_state = outcome(wm["share"], cfg["weight_limits"]) if wm else "skip"
    alt = f'Gardener review. Scope: {percent(sm["share"])}% more than it needs ({OUTCOME[s_state][1]}). ' + (
        f'Weight: {percent(wm["share"])}% of added lines flagged ({OUTCOME[w_state][1]}).' if wm else "Weight: not run.")
    start = start or {}
    s0 = start.get("scope", sm["share"])
    w0 = start.get("weight") if start.get("weight") is not None else (wm["share"] if wm else None)
    out = [f'<!-- gardener scope={s0:.2f} weight={"" if w0 is None else format(w0, ".2f")} -->']
    if note:
        out += [f"_{note}_", ""]
    out += ["<picture>", f'  <source media="(prefers-color-scheme: dark)" srcset="{dark}">', f'  <img alt="{alt}" src="{light}" width="800">', "</picture>", ""]
    out += [f'**Purpose.** {sm["purpose"]}', ""]

    if sm["over"]:
        def where(r):
            spans = sorted(((x["file"], int(x["start"]), int(x["end"])) for x in r["ranges"]), key=lambda t: -(t[2] - t[1]))
            links = [f'[`{f.split("/")[-1]}:{a}-{b}`](https://github.com/{repo}/blob/{head}/{f}#L{a}-L{b})' for f, a, b in spans[:3]]
            return "<br>".join(links) + (f"<br>and {len(spans) - 3} more" if len(spans) > 3 else "")

        need = lambda r: r["needs"] if r["role"] == "core" else ("0" if r["role"] == "beyond" else "?")
        n = len(sm["over"])
        out += [f'<details open><summary>Where the extra lines are ({n} piece{"" if n == 1 else "s"})</summary>', "",
                "| Piece | Finding (has → needs) | Why | Where |", "|---|---|---|---|"]
        out += [f'| **{cell(r["name"])}** | {r["kind"]}<br>{r["has"]} → {need(r)} | {cell(r["why"])} | {where(r)} |' for r in sm["over"]]
        out += ["", "</details>", ""]
    if sm["decisions"]:
        out += ["<details><summary>Questions for the owner</summary>", ""]
        out += [f"{i}. {q}" for i, q in enumerate(sm["decisions"], 1)]
        out += ["", "</details>", ""]

    if wm:
        out += [f'**Weight.** {wm["flagged"]} of {wm["base"]} added lines are flagged. Generated files, config and blank lines are left out of the count. '
                f'Each finding is a comment on its lines.', ""]
        tests, code = wm["tests_per_code"]
        if tests and code:
            ratio = f", about {tests / code:.0f} to 1" if tests >= 2 * code else ""
            out += [f"{tests} test lines for {code} lines of production code{ratio}.", ""]
        out += [f"- **{name}.** {text}" for name, text in wm["summaries"]]
    else:
        out += [f'**Weight** was not run. It starts once scope is under {cfg["scope_limits"][1]:g}%.']
    return "\n".join(out).rstrip() + "\n"


def weight_comments(wm, stats, diff_text):
    """One review comment per weight finding. A comment's first and last line must sit in the
    same hunk of the diff, so a finding that spans two hunks becomes two comments."""
    hunk_of = {}
    for chunk in re.split(r"(?m)^diff --git ", diff_text)[1:]:
        lines = chunk.split("\n")
        hm = re.match(r"a/(.+) b/(.+)$", lines[0])
        path, new, hunk = (hm.group(2) if hm else lines[0]), 0, 0
        for l in lines[1:]:
            if l.startswith("@@"):
                new, hunk = int(re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", l).group(1)), hunk + 1
            elif not hunk or l.startswith("\\") or l == "" or l.startswith("-"):
                continue
            else:
                if l.startswith("+"):
                    hunk_of[(path, new)] = hunk
                new += 1
    comments = []
    order = list(CATEGORIES)
    for i, fd in enumerate(sorted(wm["kept"], key=lambda x: (order.index(x["category"]), x["file"], int(x["start"]))), 1):
        groups = {}
        for no in fd["hits"]:
            groups.setdefault(hunk_of.get((fd["file"], no)), []).append(no)
        n = "1 line" if fd["lines"] == 1 else f'{fd["lines"]} lines'
        why = str(fd.get("reason", "")) + (f' See `{fd["see"]}`.' if fd.get("see") else "")
        text = f'{FINDING_MARK}\n**{i}. {CATEGORIES[fd["category"]][1]}** · {n}\n\n{why}'
        for hunk, nos in sorted(groups.items(), key=lambda kv: kv[1][0]):
            if hunk is None:
                continue
            c = {"path": fd["file"], "line": max(nos), "side": "RIGHT", "body": text}
            if min(nos) != max(nos):
                c.update(start_line=min(nos), start_side="RIGHT")
            comments.append(c)
    return comments


def first_review(reviews):
    """The review an earlier run posted the chart in, and the scores it started at."""
    for r in reviews:
        m = STATE_RE.search(r.get("body") or "")
        if m:
            return r, {"scope": float(m.group(1)), "weight": float(m.group(2)) if m.group(2) else None}
    return None, None


def new_only(comments, existing):
    """Leave out findings that already have a live thread: same file, overlapping lines, same
    kind of finding. A thread is live while GitHub still places it on a line."""
    family = {label: fam for fam, label in CATEGORIES.values()}

    def fam(text):
        m = re.search(r"\*\*(?:\d+\. )?(.+?)\*\*", text or "")
        return family.get(m.group(1)) if m else None

    live = [c for c in existing if FINDING_MARK in (c.get("body") or "") and c.get("line") is not None]

    def has_thread(nc):
        lo, hi = nc.get("start_line", nc["line"]), nc["line"]
        return any(c["path"] == nc["path"] and lo <= c["line"] and (c.get("start_line") or c["line"]) <= hi
                   and fam(c["body"]) == fam(nc["body"]) for c in live)

    return [c for c in comments if not has_thread(c)]


def publish(repo, pr, head, sm, wm, stats, diff_text, cfg, note="", dry_run=False):
    """Post the first review, or update it in place. Returns a short description of what happened."""
    comments = weight_comments(wm, stats, diff_text) if wm else []
    if dry_run:
        return f"dry run: would post the chart and {len(comments)} comments"
    reviews = gh("GET", f"repos/{repo}/pulls/{pr}/reviews?per_page=100")
    existing = gh("GET", f"repos/{repo}/pulls/{pr}/comments?per_page=100")
    first, start = first_review(reviews)
    stem = f"pr-{pr}/{head[:7]}-{int(time.time())}"
    limits = (cfg["scope_limits"], cfg["weight_limits"])
    sha = upload(repo, {f"{stem}-{t}.svg": render(sm, wm, t, *limits, start=start) for t in ("light", "dark")},
                 f"gardener: chart for PR {pr} at {head[:7]}")
    light, dark = (f"https://github.com/{repo}/blob/{sha}/{stem}-{t}.svg?raw=true" for t in ("light", "dark"))
    text = body(sm, wm, repo, head, light, dark, cfg, note, start)
    if not first:
        r = gh("POST", f"repos/{repo}/pulls/{pr}/reviews", {"commit_id": head, "event": "COMMENT", "body": text, "comments": comments})
        return f'posted {r["html_url"]} with {len(comments)} comments'
    gh("PUT", f"repos/{repo}/pulls/{pr}/reviews/{first['id']}", {"body": text})
    fresh = new_only(comments, existing)
    if fresh:
        n = "1 new finding" if len(fresh) == 1 else f"{len(fresh)} new findings"
        gh("POST", f"repos/{repo}/pulls/{pr}/reviews",
           {"commit_id": head, "event": "COMMENT", "body": f"**Gardener:** {n} on this push.", "comments": fresh})
    return f"updated the chart in place; {len(comments) - len(fresh)} findings already had a thread, {len(fresh)} new"
