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

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(os.path.dirname(HERE), "prompts")
CODEX = "codex exec --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules -s workspace-write"
# Claude gets a short list of tools: read anything, run git and a few read-only commands,
# write only inside the work directory. No web, no subagents, no MCP servers, no user settings.
CLAUDE = ("claude -p --tools Bash,Read,Grep,Glob,Write --permission-mode acceptEdits --strict-mcp-config "
          "--setting-sources project,local --no-session-persistence --allowedTools Read Grep Glob")
CLAUDE_SHELL = ("git", "grep", "rg", "sed -n", "head", "tail", "wc", "cat", "sort", "uniq", "ls", "python3 -m json.tool")
AGENTS = ("codex", "claude")
LANES = [("code", "Production code"), ("tests", "Tests"), ("comments", "Comments and docs")]

TASK = """Read {prompt}{lane} and follow {them} exactly. Do the work yourself; start no subagents.

Inputs for this run:
- REPO = {repo}
- HEAD_SHA = {head}
- ADDED = {work}/added.txt
- DIFF = {work}/pr.diff
{extra}- OUT = {work}/{out}

Read-only: do not check out, edit, commit or push anything in any checkout, and post nothing anywhere. The only file you write is OUT. Outside the checkouts named above, read only the files named in this message.
"""


def command(cfg, work, task):
    """Returns (argv, text for stdin or None)."""
    if cfg.get("command"):
        return shlex.split(cfg["command"]) + [task], None
    if cfg.get("agent") == "claude":
        cmd = shlex.split(CLAUDE) + [f"Bash({c} *)" for c in CLAUDE_SHELL]
        cmd += ["--model", cfg["model"]] if cfg.get("model") else []
        cmd += ["--effort", cfg["effort"]] if cfg.get("effort") else []
        return cmd, task  # the list of allowed tools is open-ended, so the task goes in on stdin
    cmd = shlex.split(CODEX) + ["-C", work]
    cmd += ["-m", cfg["model"]] if cfg.get("model") else []
    cmd += ["-c", f'model_reasoning_effort="{cfg["effort"]}"'] if cfg.get("effort") else []
    return cmd + [task], None


def run(task, work, out, cfg):
    """One reviewer run. Returns the parsed JSON, or None when the reviewer produced nothing usable."""
    path = os.path.join(work, out)
    if os.path.exists(path):
        os.remove(path)
    # The reviewer reads text written by the PR's author. It gets no GitHub credentials.
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN")}
    argv, stdin = command(cfg, work, task)
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
        return None


def scope(repo, head, work, cfg, tag=""):
    others = "".join(f"  - {p} at `{ref}`" + (f": {note}" if note else "") + "\n" for p, ref, note in cfg.get("others", []))
    extra = f"- DESC = {work}/desc.md\n" + (f"- OTHERS =\n{others}" if others else "- OTHERS = none\n")
    task = TASK.format(prompt=os.path.join(PROMPTS, "scope.md"), lane="", them="it", repo=repo, head=head, work=work,
                       extra=extra, out=f"scope{tag}.json")
    return run(task, work, f"scope{tag}.json", cfg)


def weight(repo, head, work, stats, cfg):
    """Three narrow runs. Code and comments run together; tests waits for code, because a test
    whose only job is to reach a check the code run called needless goes with that check."""
    has = {
        "code": any(f["bucket"] == "production" and f["code"] for f in stats["files"]),
        "tests": any(f["bucket"] == "tests" and f["added"] for f in stats["files"]),
        "comments": any(f["doc"] or f["prose"] for f in stats["files"] if f["bucket"] not in ("generated", "config")),
    }

    def lane(name, extra=""):
        if not has[name]:
            return {"findings": [], "summary": ""}
        task = TASK.format(prompt=os.path.join(PROMPTS, "weight.md"), lane=f", then {os.path.join(PROMPTS, f'weight-{name}.md')},",
                           them="them", repo=repo, head=head, work=work, extra=extra, out=f"weight-{name}.json")
        return run(task, work, f"weight-{name}.json", cfg)

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
