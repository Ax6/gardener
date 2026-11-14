"""Look things up on GitHub for the reviewer: other repositories and open pull requests.

  look.py search TEXT [--repo NAME]            code search across the organisation, default branches
  look.py prs NAME [--grep TEXT]               open pull requests; with --grep, the lines they add that contain TEXT
  look.py grep NAME PATTERN [--pr N] [PATH..]  search one repository, or one open pull request's version of it
  look.py show NAME [PATH] [--pr N] [--lines A-B]   print a file, or list a directory

The reviewer decides what to look up; nothing is fetched before it asks. This
file can only read: every request is a GET, and git only fetches. The token it
uses should be a read-only one, because the reviewer runs in the same
environment and reads text written by the pull request's author.
"""

import argparse
import base64
import fcntl
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
ORG = os.environ.get("GARDENER_ORG", "")
TOKEN = os.environ.get("GARDENER_READ_TOKEN", "")
DIR = os.environ.get("GARDENER_LOOK_DIR", ".gardener-look")
UNDER_REVIEW = os.environ.get("GARDENER_HEAD_SHA", "")  # its own pull request is not a reader of itself
MAX = 200  # lines printed per answer


class Refused(Exception):
    pass


def certificates():
    ctx = ssl.create_default_context()
    # Some Python installs ship without a certificate list. The system's own is the usual fallback.
    if not ctx.cert_store_stats()["x509_ca"] and os.path.exists("/etc/ssl/cert.pem"):
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


def get(path, accept="application/vnd.github+json", retry=True):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "gardener"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=certificates()) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        wait = e.headers.get("Retry-After")
        if not wait and e.headers.get("X-RateLimit-Remaining") == "0":
            wait = int(e.headers.get("X-RateLimit-Reset", 0)) - time.time()
        if retry and e.code in (403, 429) and wait and float(wait) <= 70:  # code search allows few requests a minute
            time.sleep(max(1, float(wait)) + 1)
            return get(path, accept, False)
        raise Refused(f"GitHub answered {e.code} for {path}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise Refused(f"could not reach GitHub: {e.reason}")


def repo(name):
    name = name.split("/")[-1]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in (".", ".."):
        raise Refused(f"not a repository name: {name!r}")
    return name


def added(diff, text):
    """(path, line) for every added line of a unified diff that contains text."""
    path, out = "", []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and text in line:
            out.append((path, line[1:].strip()[:200]))
    return out


def cmd_search(a):
    q = f"{a.text} repo:{ORG}/{repo(a.repo)}" if a.repo else f"{a.text} org:{ORG}"
    data = json.loads(get("/search/code?per_page=30&q=" + urllib.parse.quote(q), "application/vnd.github.text-match+json"))
    print(f'{data["total_count"]} files match. Default branches only: use `prs NAME --grep` for open pull requests.')
    for item in data["items"]:
        print(f'{item["repository"]["name"]}  {item["path"]}')
        for match in item.get("text_matches", [])[:2]:
            for line in [x.strip() for x in match["fragment"].splitlines() if x.strip()][:3]:
                print("    " + line[:160])


def cmd_prs(a):
    name = repo(a.repo)
    found, page = [], 1
    while True:
        batch = json.loads(get(f"/repos/{ORG}/{name}/pulls?state=open&per_page=100&page={page}"))
        found += [p for p in batch if p["head"]["sha"] != UNDER_REVIEW]
        if len(batch) < 100:
            break
        page += 1
    shown = 0
    for p in found:
        head = f'#{p["number"]}  {p["title"].strip()}' + ("  (draft)" if p.get("draft") else "")
        if not a.grep:
            print(head)
            continue
        try:
            hits = added(get(f'/repos/{ORG}/{name}/pulls/{p["number"]}', "application/vnd.github.diff"), a.grep)
        except Refused:
            print(f'{head}\n    too large to search here: use `grep {name} PATTERN --pr {p["number"]}`')
            continue
        if hits:
            shown += 1
            print(head)
            for path, line in hits[:20]:
                print(f"    {path}: {line}")
            if len(hits) > 20:
                print(f"    ... and {len(hits) - 20} more lines")
    if not found:
        print(f"{name} has no other open pull request")
    elif a.grep and not shown:
        print(f"none of the {len(found)} open pull requests in {name} adds a line containing {a.grep!r}")


def copy(name, pr):
    """A shallow copy of one branch of one repository, fetched the first time it is asked for."""
    path = os.path.join(DIR, name + ".git")
    ref, source = (f"refs/look/pr-{pr}", f"refs/pull/{pr}/head") if pr else ("refs/look/default", "HEAD")
    os.makedirs(DIR, exist_ok=True)
    with open(path + ".lock", "w") as lock:  # two reviewer runs can share this directory
        fcntl.flock(lock, fcntl.LOCK_EX)
        if subprocess.run(["git", "-C", path, "rev-parse", "-q", "--verify", ref], capture_output=True).returncode:
            subprocess.run(["git", "init", "-q", "--bare", path], check=True, capture_output=True)
            auth = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
            env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
                   "GIT_CONFIG_KEY_0": "http.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth}"}
            r = subprocess.run(["git", "-C", path, "fetch", "-q", "--depth", "1", f"{SERVER}/{ORG}/{name}.git", f"+{source}:{ref}"],
                               env=env, capture_output=True, text=True)
            if r.returncode:
                raise Refused(f"could not fetch {name}" + (f" pull request {pr}" if pr else "") + f": {r.stderr.strip()[-300:]}")
    return path, ref


def cmd_grep(a):
    path, ref = copy(repo(a.repo), a.pr)
    r = subprocess.run(["git", "-C", path, "grep", "-n", "-I", "-e", a.pattern, ref, "--", *a.paths], capture_output=True, text=True)
    if r.returncode > 1:
        raise Refused(r.stderr.strip())
    lines = [line[len(ref) + 1:] for line in r.stdout.splitlines()]
    print("\n".join(lines[:MAX]) or "no match")
    if len(lines) > MAX:
        print(f"... and {len(lines) - MAX} more lines: narrow the pattern or give a path")


def cmd_show(a):
    path, ref = copy(repo(a.repo), a.pr)
    r = subprocess.run(["git", "-C", path, "show", f"{ref}:{a.path.strip('/')}"], capture_output=True, text=True, errors="replace")
    if r.returncode:
        raise Refused(r.stderr.strip())
    lines = r.stdout.splitlines()
    first, _, last = (a.lines or f"1-{2 * MAX}").partition("-")
    first, last = int(first), int(last or first)
    print("\n".join(f"{n}\t{text}" for n, text in enumerate(lines[first - 1:last], first)))
    if not a.lines and len(lines) > last:
        print(f"... {len(lines)} lines in all: ask for more with --lines A-B")


def main(argv=None):
    p = argparse.ArgumentParser(prog="look", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("search")
    q.add_argument("text")
    q.add_argument("--repo")
    q.set_defaults(fn=cmd_search)
    q = sub.add_parser("prs")
    q.add_argument("repo")
    q.add_argument("--grep")
    q.set_defaults(fn=cmd_prs)
    q = sub.add_parser("grep")
    q.add_argument("repo")
    q.add_argument("pattern")
    q.add_argument("paths", nargs="*")
    q.add_argument("--pr", type=int)
    q.set_defaults(fn=cmd_grep)
    q = sub.add_parser("show")
    q.add_argument("repo")
    q.add_argument("path", nargs="?", default="")
    q.add_argument("--pr", type=int)
    q.add_argument("--lines", metavar="A-B")
    q.set_defaults(fn=cmd_show)
    a = p.parse_args(argv)
    if not (ORG and TOKEN):
        sys.exit("look is not set up: it needs GARDENER_ORG and GARDENER_READ_TOKEN")
    try:
        a.fn(a)
    except Refused as e:
        sys.exit(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
