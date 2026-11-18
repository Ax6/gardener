"""Put the review on the pull request, through the gh CLI.

The main review holds the chart and scope table. Up to five weight findings
go inline. Larger sets go in a folded table in the main review, which is
updated in place as the PR changes.
"""

import json
import re
import subprocess
import time
from urllib.parse import quote

from .card import OUTCOME, outcome, render
from .weight import CATEGORIES, percent

BRANCH = "gardener-assets"
STATE_RE = re.compile(r"<!-- gardener scope=([0-9.]+) weight=([0-9.]*) -->")
FINDING_MARK = "<!-- gardener-finding -->"


def gh(method, path, data=None, *, paginate=False):
    cmd = ["gh", "api", "-X", method, path] + (["--input", "-"] if data is not None else [])
    if paginate:
        cmd += ["--paginate", "--slurp"]
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"gh api {method} {path}: {r.stderr.strip() or r.stdout.strip()}")
    result = json.loads(r.stdout) if r.stdout.strip() else None
    return [item for page in result for item in page] if paginate else result


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


def body(sm, wm, repo, head, light, dark, cfg, note="", start=None, *, fold_weight=False):
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
        out += [f'**Weight.** {wm["flagged"]} of {wm["base"]} added lines are flagged. Generated files, config and blank lines are left out of the count.', ""]
        tests, code = wm["tests_per_code"]
        if tests and code:
            ratio = f", about {tests / code:.0f} to 1" if tests >= 2 * code else ""
            out += [f"{tests} test lines for {code} lines of production code{ratio}.", ""]
        out += [f"- **{name}.** {text}" for name, text in wm["summaries"]]
        rows = weight_rows(wm, repo, head) if fold_weight else []
        if rows:
            label = "finding" if len(rows) == 1 else "findings"
            out += ["", f"<details><summary>{len(rows)} weight {label}</summary>", "",
                    "| Where | Finding | Why |", "|---|---|---|", *rows, "", "</details>"]
    else:
        out += [f'**Weight** was not run. It starts once scope is under {cfg["scope_limits"][1]:g}%.']
    return "\n".join(out).rstrip() + "\n"


INLINE = 5


def ordered_findings(wm):
    order = list(CATEGORIES)
    return enumerate(sorted(wm["kept"], key=lambda fd: (order.index(fd["category"]), fd["file"], int(fd["start"]))), 1)


def weight_comments(wm, diff_text, repo, head):
    """One inline thread per finding, anchored in the hunk with the most flagged lines."""
    if len(wm["kept"]) > INLINE:
        return []
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
    for number, fd in ordered_findings(wm):
        path = fd["file"]
        spans = {}
        for no in fd["hits"]:
            hunk = hunk_of.get((path, no))
            if hunk is not None:
                spans.setdefault(hunk, []).append(no)
        if not spans:
            return []  # Keep the full review together in the table if a finding can't go inline.
        span = max(spans.values(), key=len)
        count = "1 line" if fd["lines"] == 1 else f'{fd["lines"]} lines'
        detail = f'{FINDING_MARK}\n**{number}. {CATEGORIES[fd["category"]][1]}** · {count}\n\n{finding_reason(fd)}'
        if len(span) < len(fd["hits"]):
            detail += f"\n\nFull range {finding_location(fd, repo, head)}"
        comment = {"path": path, "line": span[-1], "side": "RIGHT", "body": detail}
        if span[0] != span[-1]:
            comment.update(start_line=span[0], start_side="RIGHT")
        comments.append(comment)
    return comments


def finding_reason(fd):
    return str(fd.get("reason", "")) + (f' See `{fd["see"]}`.' if fd.get("see") else "")


def finding_location(fd, repo, head):
    path = fd["file"]
    start, end = fd["hits"][0], fd["hits"][-1]
    label = f"{path}:{start}"
    anchor = f"L{start}"
    if start != end:
        label += f"-{end}"
        anchor += f"-L{end}"
    location = f"`{cell(label)}`"
    return f"[{location}](https://github.com/{repo}/blob/{head}/{quote(path)}#{anchor})" if repo else location


def weight_rows(wm, repo, head):
    """Every finding with its reason and a link to the lines it flagged."""
    rows = []
    for number, fd in ordered_findings(wm):
        location = finding_location(fd, repo, head)
        count = "1 line" if fd["lines"] == 1 else f'{fd["lines"]} lines'
        rows.append(f'| {location} | **{number}. {CATEGORIES[fd["category"]][1]}**<br>{count} | {cell(finding_reason(fd))} |')
    return rows


def first_review(reviews):
    """The review an earlier run posted the chart in, and the scores it started at."""
    for r in reviews:
        m = STATE_RE.search(r.get("body") or "")
        if m:
            return r, {"scope": float(m.group(1)), "weight": float(m.group(2)) if m.group(2) else None}
    return None, None


def new_only(comments, existing):
    """Reuse live Gardener threads on overlapping lines for the same kind of finding."""
    family = {label: name for name, label in CATEGORIES.values()}

    def families(comment):
        headings = re.findall(r"(?m)^\*\*\d+\. (.+?)\*\* ·", comment["body"])
        return {family[label] for label in headings if label in family}

    live = [c for c in existing if FINDING_MARK in (c.get("body") or "") and c.get("line") is not None]

    def has_thread(comment):
        start, end = comment.get("start_line", comment["line"]), comment["line"]
        kinds = families(comment)
        return any(c["path"] == comment["path"] and start <= c["line"] and (c.get("start_line") or c["line"]) <= end
                   and kinds & families(c) for c in live)

    return [comment for comment in comments if not has_thread(comment)]


def publish(repo, pr, head, sm, wm, stats, diff_text, cfg, note="", dry_run=False):
    """Post the first review, or update it in place. Returns a short description of what happened."""
    if dry_run:
        findings = len(wm["kept"]) if wm else 0
        return f"dry run: would publish the chart with {findings} weight findings"
    endpoint = f"repos/{repo}/pulls/{pr}"
    reviews = gh("GET", f"{endpoint}/reviews?per_page=100")
    target, start = first_review(reviews)
    comments = weight_comments(wm, diff_text, repo, head) if wm else []
    fold_weight = bool(wm and wm["kept"] and not comments)
    if target and comments:
        comments = new_only(comments, gh("GET", f"{endpoint}/comments?per_page=100", paginate=True))
    stem = f"pr-{pr}/{head[:7]}-{int(time.time())}"
    limits = (cfg["scope_limits"], cfg["weight_limits"])
    sha = upload(repo, {f"{stem}-{t}.svg": render(sm, wm, t, *limits, start=start) for t in ("light", "dark")},
                 f"gardener: chart for PR {pr} at {head[:7]}")
    light, dark = (f"https://github.com/{repo}/blob/{sha}/{stem}-{t}.svg?raw=true" for t in ("light", "dark"))
    inline_error = None
    if target and comments:
        # A submitted review cannot take new inline comments.
        try:
            gh("POST", f"{endpoint}/reviews",
               {"commit_id": head, "event": "COMMENT", "body": "**Gardener weight findings**", "comments": comments})
        except RuntimeError as err:
            inline_error = err
            fold_weight = True
    text = body(sm, wm, repo, head, light, dark, cfg, note, start, fold_weight=fold_weight)
    if not target:
        r = gh("POST", f"{endpoint}/reviews", {"commit_id": head, "event": "COMMENT", "body": text, "comments": comments})
        return f'posted {r["html_url"]} with {len(comments)} inline comments'
    gh("PUT", f"{endpoint}/reviews/{target['id']}", {"body": text})
    if inline_error:
        return f"added the weight findings to the main review after the inline post failed. {inline_error}"
    return f"updated the main review in place with {len(comments)} new inline comments"
