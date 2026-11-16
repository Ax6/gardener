"""Run the reviewer: a coding agent that reads the PR and writes one JSON file.

The reviewer is told what to look for and where to write. It is never told
what a score decides: no limits, no pass or fail. It returns line ranges and
never totals, so the counting stays in this tool.

Two agents are built in: the Codex CLI and the Claude Code CLI. Any other
command works that takes the task as its last argument, can read files and run
git, and writes the file named in the task.
"""

import json
import os
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .lines import UNCOUNTED

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(os.path.dirname(HERE), "prompts")
LOOK = os.path.join(HERE, "look.py")  # the reviewer's way to read other repositories and open pull requests
CODEX = "codex exec --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules -s workspace-write"
# Claude gets a short list of tools: read anything, run read-only git in the checkouts it was
# given plus a few read-only commands, and write only inside the work directory. No web, no
# subagents, no MCP servers, no user settings.
CLAUDE = ("claude -p --tools Bash,Read,Grep,Glob,Write --strict-mcp-config "
          "--setting-sources project,local --no-session-persistence")
CLAUDE_GIT = ("show", "grep", "log", "ls-tree", "ls-files", "diff", "cat-file", "rev-parse", "blame", "merge-base")
CLAUDE_SHELL = ("grep", "rg", "sed -n", "head", "tail", "wc", "cat", "sort", "uniq", "ls", "python3 -m json.tool")
AGENTS = ("codex", "claude")
LANES = [("code", "Production code"), ("tests", "Tests"), ("comments", "Comments and docs")]

TASK = """Read {prompt}{lane} and follow {them} exactly. Do the work yourself; start no subagents.

Inputs for this run:
- REPO = {repo}
- HEAD_SHA = {head}
- ADDED = {work}/added.txt
- DIFF = {work}/pr.diff
{extra}- OUT = {work}/{out}

Read-only: do not check out, edit, commit or push anything in any checkout, and post nothing anywhere. The only files you write are OUT and, when it is given, FIT_OUT. Outside the checkouts named above, read only the files named in this message.

If you cannot read REPO through git at all, do not write OUT. Reply with the exact error instead.
"""


def command(cfg, work, task, checkouts):
    """Returns (argv, text for stdin or None). `checkouts` are the repositories the reviewer reads."""
    if cfg.get("command"):
        return shlex.split(cfg["command"]) + [task], None
    if cfg.get("agent") == "claude":
        dirs = [os.path.realpath(d) for d in checkouts]
        allowed = ["Read", "Grep", "Glob", f"Edit(/{os.path.realpath(work)}/**)"]
        allowed += [f"Bash(git -C {d} {sub} *)" for d in dirs for sub in CLAUDE_GIT]
        allowed += [f"Bash({c} *)" for c in CLAUDE_SHELL]
        allowed += [f"Bash(python3 {LOOK} *)"] if cfg.get("look") else []
        cmd = shlex.split(CLAUDE) + ["--add-dir", *dirs, "--allowedTools", *allowed]
        cmd += ["--model", cfg["model"]] if cfg.get("model") else []
        cmd += ["--effort", cfg["effort"]] if cfg.get("effort") else []
        return cmd, task  # the lists above are open-ended, so the task goes in on stdin
    cmd = shlex.split(CODEX) + ["-C", work]
    cmd += ["-c", "sandbox_workspace_write.network_access=true"] if cfg.get("look") else []  # look.py talks to GitHub
    cmd += ["-m", cfg["model"]] if cfg.get("model") else []
    cmd += ["-c", f'model_reasoning_effort="{cfg["effort"]}"'] if cfg.get("effort") else []
    return cmd + [task], None


def run(task, work, out, cfg, checkouts):
    """One reviewer run. Returns the parsed JSON, or None when the reviewer produced nothing usable."""
    path = os.path.join(work, out)
    if os.path.exists(path):
        os.remove(path)
    # The reviewer reads text written by the PR's author. It gets no GitHub credentials that can
    # write. The one it may get is the read-only token look.py uses, and only when look is on.
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GARDENER_READ_TOKEN")}
    if cfg.get("look"):
        env.update(cfg["look"], GARDENER_READ_TOKEN=os.environ["GARDENER_READ_TOKEN"])
    argv, stdin = command(cfg, work, task, checkouts)
    try:
        r = subprocess.run(argv, cwd=work, capture_output=True, text=True, env=env, input=stdin or "",
                           timeout=cfg.get("timeout", 2700))
    except subprocess.TimeoutExpired:
        return None
    with open(os.path.join(work, out + ".log"), "w", encoding="utf-8") as fh:
        fh.write(r.stdout[-20000:] + "\n--- stderr ---\n" + r.stderr[-20000:])
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        # No usable result. Show what the reviewer said, so the reason is in the job log.
        print(f"reviewer wrote no usable {out}. Its last words:\n{r.stdout[-1200:].strip()}\n{r.stderr[-400:].strip()}", flush=True)
        return None


def _checkouts(repo, cfg):
    return [repo] + [path for path, _, _ in cfg.get("others", [])]


def _look_line(cfg):
    return f"- LOOK = python3 {LOOK}\n" if cfg.get("look") else "- LOOK = not available\n"


def account(repo, head, work, cfg):
    """Experimental: the decisions in the PR and whether the author accounted for each."""
    extra = f"- DESC = {work}/desc.md\n" + _look_line(cfg)
    task = TASK.format(prompt=os.path.join(PROMPTS, "account.md"), lane="", them="it", repo=repo, head=head, work=work,
                       extra=extra, out="account.json")
    return run(task, work, "account.json", cfg, _checkouts(repo, cfg))


def fit(repo, head, work, cfg):
    """The questions about building on what is there, asked by a reviewer that does nothing else."""
    extra = f"- DESC = {work}/desc.md\n" + _look_line(cfg) + f"- FIT_OUT = {work}/fit-alone.json\n"
    task = TASK.format(prompt=os.path.join(PROMPTS, "fit.md"), lane="", them="it", repo=repo, head=head, work=work,
                       extra=extra, out="fit-alone.json")
    return run(task, work, "fit-alone.json", cfg, _checkouts(repo, cfg))


def scope(repo, head, work, cfg, tag=""):
    others = "".join(f"  - {p} at `{ref}`" + (f": {note}" if note else "") + "\n" for p, ref, note in cfg.get("others", []))
    extra = f"- DESC = {work}/desc.md\n" + (f"- OTHERS =\n{others}" if others else "- OTHERS = none\n")
    extra += _look_line(cfg) + (f"- STACK = {cfg['stack']}\n" if cfg.get("stack") else "- STACK = none\n")
    lane = ""
    if cfg.get("fit") == "with-scope":  # the same reviewer answers both, scope first
        lane, extra = f", then {os.path.join(PROMPTS, 'fit.md')},", extra + f"- FIT_OUT = {work}/fit{tag}.json\n"
    task = TASK.format(prompt=os.path.join(PROMPTS, "scope.md"), lane=lane, them="them" if lane else "it", repo=repo, head=head, work=work,
                       extra=extra, out=f"scope{tag}.json")
    return run(task, work, f"scope{tag}.json", cfg, _checkouts(repo, cfg))


def weight(repo, head, work, stats, cfg):
    """Three narrow runs. Code and comments run together; tests waits for code, because a test
    whose only job is to reach a check the code run called needless goes with that check."""
    has = {
        "code": any(f["bucket"] == "production" and f["code"] for f in stats["files"]),
        "tests": any(f["bucket"] == "tests" and f["added"] for f in stats["files"]),
        "comments": any(f["doc"] or f["prose"] for f in stats["files"] if f["bucket"] not in UNCOUNTED),
    }

    def lane(name, extra=""):
        if not has[name]:
            return {"findings": [], "summary": ""}
        task = TASK.format(prompt=os.path.join(PROMPTS, "weight.md"), lane=f", then {os.path.join(PROMPTS, f'weight-{name}.md')},",
                           them="them", repo=repo, head=head, work=work, extra=extra, out=f"weight-{name}.json")
        return run(task, work, f"weight-{name}.json", cfg, _checkouts(repo, cfg))

    with ThreadPoolExecutor(max_workers=2) as pool:
        code, comments = pool.submit(lane, "code"), pool.submit(lane, "comments")
        code, comments = code.result(), comments.result()
    tests = lane("tests", f"- CODE = {work}/weight-code.json\n" if code and has["code"] else "")
    results = {"code": code, "tests": tests, "comments": comments}
    if any(v is None for v in results.values()):
        return None
    findings = [f for name, _ in LANES for f in results[name].get("findings", [])]
    summaries = [(label, str(results[name].get("summary", "")).strip()) for name, label in LANES]
    return findings, summaries
