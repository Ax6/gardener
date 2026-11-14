"""Count what a pull request adds.

Every changed file goes into one bucket (production, tests, generated, docs,
config) and every added line gets one kind (code, doc, blank, prose). The
reviewer reads the numbered listing this module writes; the scores are counted
from the same numbers, so they never depend on a model's arithmetic.
"""

import ast
import io
import json
import os
import re
import subprocess
import tokenize
from fnmatch import fnmatchcase

BUCKETS = ["production", "tests", "generated", "docs", "config", "skipped"]
UNCOUNTED = ("generated", "config", "skipped")  # named to the reviewer, never listed, never in a score
LABEL = {
    "production": "Production",
    "tests": "Tests",
    "generated": "Generated",
    "docs": "Doc files",
    "config": "Config and CI",
    "skipped": "Not counted here",
}

GENERATED_PATH = re.compile(
    r"(^|/)mocks/|\.pb\.go$|_gen\.go$|\.gen\.go$|\.snap$|(^|/)__snapshots__/"
    r"|(^|/)(uv\.lock|poetry\.lock|go\.sum|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|Gemfile\.lock)$"
)
TEST_PATH = re.compile(
    r"_test\.go$|(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$|(^|/)testutils?/"
    r"|\.(test|spec)\.[cm]?[jt]sx?$|(^|/)__tests__/|(^|/)(e2e|cypress|playwright)/"
    r"|(^|/)spec/|_spec\.rb$|(^|/)src/test/|Tests?\.(java|kt|cs)$|_test\.(rs|exs?|dart)$"
)
DOCS_PATH = re.compile(r"\.(md|mdx|rst|adoc)$|(^|/)docs/")
CONFIG_PATH = re.compile(
    r"\.(ya?ml|toml|json|ini|cfg|env|example|lock)$|(^|/)\.github/|(^|/)(Dockerfile|Makefile)[^/]*$|\.sh$"
)
SLASH_LANGS = (
    ".go", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".kt", ".c", ".h", ".cc", ".cpp", ".cs",
    ".rs", ".swift", ".scala", ".dart", ".proto", ".php",
)
HASH_LANGS = (".yml", ".yaml", ".toml", ".sh", ".cfg", ".ini", ".env", ".example", ".rb", ".ex", ".exs")


def counted(path, only=(), skip=()):
    """The repository's own two lists. A pattern ending in / is a folder, and * matches anything, slashes too.
    `skip` always wins. When `only` is given, nothing outside it counts."""
    hit = lambda patterns: any(fnmatchcase(path, p + "*" if p.endswith("/") else p) for p in patterns)
    return not hit(skip) and (not only or hit(only))


def bucket_of(path, content):
    if GENERATED_PATH.search(path):
        return "generated"
    head = "\n".join((content or "").splitlines()[:5])
    if "Code generated" in head and "DO NOT EDIT" in head:
        return "generated"
    if TEST_PATH.search(path):
        return "tests"
    if DOCS_PATH.search(path):
        return "docs"
    if CONFIG_PATH.search(path):
        return "config"
    return "production"


def python_doc_lines(src):
    """Line numbers that are a docstring or a comment-only line."""
    doc = set()
    try:
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                doc.update(range(first.lineno, first.end_lineno + 1))
    except SyntaxError:
        pass
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and tok.line.lstrip().startswith("#"):
                doc.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return doc


def slash_doc_lines(src):
    """Comment-only lines for languages that use // and /* */."""
    doc, in_block = set(), False
    for n, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if in_block:
            doc.add(n)
            in_block = "*/" not in s
        elif s.startswith("//"):
            doc.add(n)
        elif s.startswith("/*"):
            doc.add(n)
            in_block = "*/" not in s[2:]
    return doc


def doc_lines(path, content):
    """Comment and docstring line numbers, or None when the file could not be read."""
    if content is None:
        return None
    if path.endswith(".py"):
        return python_doc_lines(content)
    if path.endswith(SLASH_LANGS):
        return slash_doc_lines(content)
    if path.endswith(".sql"):
        return {n for n, l in enumerate(content.splitlines(), 1) if l.strip().startswith("--")}
    if path.endswith(HASH_LANGS) or re.search(r"(^|/)(Dockerfile|Makefile)", path):
        return {n for n, l in enumerate(content.splitlines(), 1) if l.strip().startswith("#")}
    return set()


def kind_of(lineno, text, docs):
    s = text.strip()
    if not s:
        return "blank"
    if docs is not None:
        return "doc" if lineno in docs else "code"
    # No file content to read: judge the line on its own.
    if s.startswith(("//", "#", "/*", "*", '"""', "'''", "--")):
        return "doc"
    return "code"


def parse_diff(text):
    """One entry per file: {path, added: [(lineno, text)], removed, deleted}."""
    files, cur, new_no = [], None, 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            cur = {"path": line.split(" b/", 1)[-1], "added": [], "removed": 0, "deleted": False}
            files.append(cur)
        elif cur is None:
            continue
        elif line.startswith("+++ "):
            if line[4:] == "/dev/null":
                cur["deleted"] = True
            else:
                cur["path"] = line[6:] if line[4:6] == "b/" else line[4:]
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            new_no = int(m.group(1)) if m else 0
        elif line.startswith("+"):
            cur["added"].append((new_no, line[1:]))
            new_no += 1
        elif line.startswith("-"):
            cur["removed"] += 1
        elif line.startswith(" "):
            new_no += 1
    return files


def read_at(repo, sha, path):
    """A file as the PR leaves it, read from git so the working tree is never touched."""
    if not repo or not sha:
        return None
    r = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], capture_output=True)
    if r.returncode != 0:
        return None
    try:
        return r.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def collect(diff_text, repo=None, head=None, only=(), skip=()):
    """Sort every added line. Returns {"files": [{path, bucket, added, removed, code, doc, blank, prose, lines}]}."""
    out = []
    for f in parse_diff(diff_text):
        content = None if f["deleted"] else read_at(repo, head, f["path"])
        bucket = bucket_of(f["path"], content) if counted(f["path"], only, skip) else "skipped"
        docs = doc_lines(f["path"], content)
        lines = []
        for no, text in f["added"]:
            kind = "prose" if bucket == "docs" and text.strip() else kind_of(no, text, docs)
            lines.append([no, kind, text])
        counts = {k: sum(1 for l in lines if l[1] == k) for k in ("code", "doc", "blank", "prose")}
        out.append({"path": f["path"], "bucket": bucket, "added": len(lines), "removed": f["removed"], **counts, "lines": lines})
    return {"files": out}


def listing(stats):
    """The numbered listing the reviewer reads. Files that are not counted are named, not listed."""
    out = ["# Every line this PR adds. Columns: line number in the new file, kind (C code, D comment or docstring, P prose in a doc file), text."]
    for f in stats["files"]:
        if not f["added"]:
            continue
        out.append(f"\n=== {f['path']}  [{f['bucket']}]  +{f['added']} -{f['removed']}")
        if f["bucket"] in UNCOUNTED:
            out.append("(not reviewed: lines not listed)")
            continue
        for no, kind, text in f["lines"]:
            tag = {"code": "C", "doc": "D", "blank": " ", "prose": "P"}[kind]
            out.append(f"{no:5d} {tag} | {text}")
    return "\n".join(out) + "\n"


def totals(stats):
    t = {b: {"added": 0, "removed": 0, "code": 0, "doc": 0, "blank": 0, "prose": 0, "files": 0} for b in BUCKETS}
    for f in stats["files"]:
        b = t[f["bucket"]]
        b["files"] += 1
        for k in ("added", "removed", "code", "doc", "blank", "prose"):
            b[k] += f[k]
    return t


def write(stats, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "added.txt"), "w", encoding="utf-8") as fh:
        fh.write(listing(stats))
