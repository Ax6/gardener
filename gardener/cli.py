"""Command line.

  python -m gardener run     review one pull request end to end and post the result
  python -m gardener collect count the added lines and write the reviewer's listing
  python -m gardener card    draw the chart from results already on disk
"""

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from . import card, github, lines, reviewer, scope, weight


def limits(text):
    lo, hi = (float(x) for x in text.split(","))
    if lo > hi:
        raise argparse.ArgumentTypeError("write the lower mark first, for example 20,30")
    return lo, hi


def other(text):
    """PATH[@REF][=WHAT IT IS] -> (path, ref, note)."""
    text, _, note = text.partition("=")
    path, _, ref = text.partition("@")
    return path, ref or "HEAD", note.strip()


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def look(args, work):
    """What look.py needs to read other repositories and open pull requests, or None when it has no token."""
    org = args.org or args.github_repo.partition("/")[0]
    if not org:
        origin = subprocess.run(["git", "-C", args.repo, "remote", "get-url", "origin"], capture_output=True, text=True).stdout
        found = re.search(r"[:/]([^/:]+)/[^/]+?(?:\.git)?\s*$", origin)
        org = found.group(1) if found else ""
    if not (org and os.environ.get("GARDENER_READ_TOKEN")):
        return None
    head = sh("git", "-C", args.repo, "rev-parse", args.head).strip()
    return {"GARDENER_ORG": org, "GARDENER_LOOK_DIR": os.path.join(work, "look"), "GARDENER_HEAD_SHA": head}


def near(share, marks, margin):
    return any(abs(share - m) <= margin for m in marks)


def review_scope(args, cfg, stats, work):
    """One run. When the score lands near a mark, two more, and the middle one counts."""
    first = reviewer.scope(args.repo, args.head, work, cfg)
    if first is None:
        return None
    runs = [first]
    if near(scope.model(stats, first)["share"], cfg["scope_limits"], args.rerun_margin):
        with ThreadPoolExecutor(max_workers=2) as pool:
            more = pool.map(lambda tag: reviewer.scope(args.repo, args.head, work, cfg, tag), ("-2", "-3"))
        runs += [r for r in more if r is not None]
    models = sorted((scope.model(stats, r) for r in runs), key=lambda m: m["share"])
    return models[(len(models) - 1) // 2]


def cmd_run(args):
    cfg = {
        "scope_limits": args.scope_limits, "weight_limits": args.weight_limits, "command": args.reviewer, "agent": args.agent,
        "model": args.model, "effort": args.effort, "timeout": args.timeout,
        "others": [other(o) for o in args.other or []],
    }
    work = os.path.realpath(args.work)
    # The reviewer is given these paths word for word, and may only run git in them.
    args.repo = os.path.realpath(args.repo)
    cfg["others"] = [(os.path.realpath(path), ref, note) for path, ref, note in cfg["others"]]
    os.makedirs(work, exist_ok=True)
    cfg["look"] = look(args, work)
    diff = sh("git", "-C", args.repo, "diff", f"{args.base}...{args.head}")
    stats = lines.collect(diff, args.repo, args.head, args.only or (), args.skip or ())
    lines.write(stats, work)
    with open(os.path.join(work, "pr.diff"), "w", encoding="utf-8") as fh:
        fh.write(diff)
    with open(os.path.join(work, "desc.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# {args.title}\n\n{args.description_text()}\n")

    written = sum(f["code"] + f["doc"] + f["prose"] for f in stats["files"] if f["bucket"] not in lines.UNCOUNTED)
    if written < args.min_lines:
        print(f"skipped: {written} written lines, under the floor of {args.min_lines}")
        return 0

    sm = review_scope(args, cfg, stats, work)
    if sm is None:
        print("the reviewer produced no scope result; nothing posted")
        return 0 if args.mode == "report" else 2
    s_state = card.outcome(sm["share"], cfg["scope_limits"])
    wm = None
    if s_state != "fail" and not args.scope_only:
        result = reviewer.weight(args.repo, args.head, work, stats, cfg)
        if result is None:
            print("the reviewer produced no weight result; posting scope only")
        else:
            wm = weight.model(stats, *result)
    w_state = card.outcome(wm["share"], cfg["weight_limits"]) if wm else "skip"

    for theme in ("light", "dark"):
        with open(os.path.join(work, f"card-{theme}.svg"), "w", encoding="utf-8") as fh:
            fh.write(card.render(sm, wm, theme, cfg["scope_limits"], cfg["weight_limits"]))
    print(f'scope {sm["share"]:.0f}% ({card.OUTCOME[s_state][1]})' + (f', weight {wm["share"]:.0f}% ({card.OUTCOME[w_state][1]})' if wm else ", weight not run")
          + (f', {sm["skipped"]} lines not counted' if sm["skipped"] else ""))
    if args.pr:
        print(github.publish(args.github_repo, args.pr, args.head, sm, wm, stats, diff, cfg, args.note, args.dry_run))
    above = "fail" in (s_state, w_state)
    with open(os.path.join(work, "outcome.json"), "w", encoding="utf-8") as fh:
        json.dump({"scope": sm["share"], "scope_outcome": s_state, "weight": wm["share"] if wm else None,
                   "weight_outcome": w_state, "above_the_limit": above}, fh)
    return 1 if (above and args.mode == "enforce") else 0


def cmd_collect(args):
    with open(args.diff, encoding="utf-8", errors="replace") as fh:
        stats = lines.collect(fh.read(), args.repo, args.head)
    lines.write(stats, args.out)
    print(json.dumps(lines.totals(stats), indent=1))
    return 0


def cmd_card(args):
    with open(args.stats, encoding="utf-8") as fh:
        stats = json.load(fh)
    with open(args.scope, encoding="utf-8") as fh:
        sm = scope.model(stats, json.load(fh))
    wm = None
    if args.weight:
        findings, summaries = [], []
        for path in args.weight:
            with open(path, encoding="utf-8") as fh:
                j = json.load(fh)
            findings += j.get("findings", [])
            summaries.append((os.path.basename(path), str(j.get("summary", ""))))
        wm = weight.model(stats, findings, summaries)
    for theme in ("light", "dark"):
        with open(f"{args.out}-{theme}.svg", "w", encoding="utf-8") as fh:
            fh.write(card.render(sm, wm, theme, args.scope_limits, args.weight_limits))
    print(f'scope {sm["share"]:.1f}%' + (f', weight {wm["share"]:.1f}%' if wm else ""))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="gardener", description="Review a pull request for scope and weight.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def marks(q):
        q.add_argument("--scope-limits", type=limits, default=(20, 30), metavar="OK,ABOVE", help="scope marks in percent (default 20,30)")
        q.add_argument("--weight-limits", type=limits, default=(10, 15), metavar="OK,ABOVE", help="weight marks in percent (default 10,15)")

    r = sub.add_parser("run", help="review one pull request end to end")
    r.add_argument("--repo", default=".", help="checkout of the repository under review")
    r.add_argument("--base", required=True, help="base commit or branch of the pull request")
    r.add_argument("--head", required=True, help="head commit of the pull request")
    r.add_argument("--title", default="", help="pull request title")
    r.add_argument("--description", default="", help="pull request description, or @FILE to read it from a file")
    r.add_argument("--other", action="append", metavar="PATH[@REF][=NOTE]",
                   help="checkout of a service this code talks to, the ref to read and a few words on what it is; repeatable")
    r.add_argument("--skip", action="append", metavar="PATTERN",
                   help="paths that are not part of the running application and are left out of both scores, "
                        "for example lab/ or *.ipynb; repeatable")
    r.add_argument("--only", action="append", metavar="PATTERN", help="when given, only these paths are counted; repeatable")
    r.add_argument("--org", help="organisation whose other repositories and open pull requests the reviewer may read, "
                   "with the read-only token in GARDENER_READ_TOKEN (default: the owner of the repository under review)")
    r.add_argument("--work", default=".gardener", help="directory for inputs, reviewer output and charts")
    r.add_argument("--pr", type=int, help="pull request number; without it nothing is posted")
    r.add_argument("--github-repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="OWNER/NAME")
    r.add_argument("--mode", choices=("report", "enforce"), default="report", help="enforce exits 1 when a step is above its limit")
    r.add_argument("--scope-only", action="store_true", help="stop after the scope step")
    r.add_argument("--min-lines", type=int, default=30, help="skip pull requests with fewer written lines than this")
    r.add_argument("--rerun-margin", type=float, default=5, help="rerun scope twice when the score is this close to a mark")
    r.add_argument("--agent", choices=reviewer.AGENTS, default="codex", help="which coding agent reviews (default codex)")
    r.add_argument("--reviewer", help="a reviewer command of your own, in place of --agent; the task is its last argument")
    r.add_argument("--model", help="model for the reviewer")
    r.add_argument("--effort", help="reasoning effort for the reviewer")
    r.add_argument("--timeout", type=int, default=2700, help="seconds allowed per reviewer run")
    r.add_argument("--note", default="", help="a line shown above the chart")
    r.add_argument("--dry-run", action="store_true", help="do everything except post")
    marks(r)
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("collect", help="count the added lines of a diff")
    c.add_argument("--diff", required=True)
    c.add_argument("--repo")
    c.add_argument("--head")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=cmd_collect)

    k = sub.add_parser("card", help="draw the chart from results on disk")
    k.add_argument("--stats", required=True)
    k.add_argument("--scope", required=True)
    k.add_argument("--weight", nargs="*", help="weight result files, one per run")
    k.add_argument("--out", required=True, help="path prefix; writes PREFIX-light.svg and PREFIX-dark.svg")
    marks(k)
    k.set_defaults(fn=cmd_card)

    args = p.parse_args(argv)
    if args.cmd == "run":
        d = args.description
        args.description_text = lambda: open(d[1:], encoding="utf-8").read() if d.startswith("@") else d
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
