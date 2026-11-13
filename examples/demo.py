"""Draw the README's example cards from a made-up pull request.

    python3 examples/demo.py          redraw the charts
    python3 examples/demo.py --post   also print the post that goes with the first one

Nothing here is a real review. The pull request, its files and every finding
are invented to show what the card and the post look like: first on a pull
request that builds far more than it needs, then on the same one after the
extra pieces were cut.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from gardener import card, github, lines, scope, weight  # noqa: E402

LIMITS = {"scope_limits": (20, 30), "weight_limits": (10, 15)}


def fake_stats(files):
    """files: (path, code lines, comment lines). Line text is a placeholder."""
    out = []
    for path, code, doc in files:
        bucket = lines.bucket_of(path, "")
        kinds = ["prose"] * code if bucket == "docs" else ["doc"] * doc + ["code"] * code
        rows = [[n, kind, "…"] for n, kind in enumerate(kinds, 1)]
        counts = {k: kinds.count(k) for k in ("code", "doc", "blank", "prose")}
        out.append({"path": path, "bucket": bucket, "added": len(rows), "removed": 0, **counts, "lines": rows})
    return {"files": out}


def span(path, start, end):
    return {"file": path, "start": start, "end": end}


FIRST = fake_stats([
    ("reports/export.py", 104, 10),
    ("reports/export_attempts.py", 131, 12),
    ("reports/formats.py", 38, 4),
    ("migrations/0042_export_attempts.sql", 19, 0),
    ("tests/test_export.py", 96, 4),
    ("tests/test_export_attempts.py", 148, 6),
    ("docs/exports.md", 31, 0),
])
FIRST_SCOPE = {
    "purpose": "A user can download their monthly report as a CSV file.",
    "decisions": [
        "A failed download costs the user one more click. Is that worth a table, a background job and 316 lines to avoid?",
        "Is a second export format planned? If not, the format registry can go until there is one.",
    ],
    "pieces": [
        {"name": "Download a monthly report as CSV", "role": "core", "needs": 40,
         "needs_why": "About a quarter of its code is its own CSV writer. The repo already has one, and the invoice download uses it.",
         "ranges": [span("reports/export.py", 1, 62), span("tests/test_export.py", 1, 64)]},
        {"name": "Check that the report belongs to the caller", "role": "core", "needs": 16,
         "needs_why": "Nothing else on this route checks who owns the report, so the check stays as it is.",
         "ranges": [span("reports/export.py", 63, 78), span("tests/test_export.py", 65, 100)]},
        {"name": "Record every export attempt and retry failed ones", "role": "beyond",
         "stakes": "This is what \"guaranteed delivery\" in the title asks for. One failed download costs the user one more click, the export is free, and no other download here retries.",
         "ranges": [span("reports/export_attempts.py", 1, 143), span("migrations/0042_export_attempts.sql", 1, 19),
                    span("tests/test_export_attempts.py", 1, 154)]},
        {"name": "Keep a list of export formats", "role": "beyond",
         "stakes": "The list has one entry, CSV. Nothing adds a second format, here or in the services that call this one.",
         "ranges": [span("reports/formats.py", 1, 42)]},
        {"name": "Check again that the month is closed", "role": "beyond",
         "stakes": "The reports service already refuses an open month on the same request, and its own test shows it.",
         "ranges": [span("reports/export.py", 79, 100)]},
        {"name": "Limit the size of the file", "role": "unsure",
         "stakes": "No limit is written down anywhere. The size of the largest real report would settle it.",
         "ranges": [span("reports/export.py", 101, 114)]},
    ],
}

AFTER = fake_stats([
    ("reports/export.py", 84, 8),
    ("tests/test_export.py", 82, 4),
    ("docs/exports.md", 14, 0),
])
AFTER_SCOPE = {
    "purpose": "A user can download their monthly report as a CSV file.",
    "decisions": [],
    "pieces": [
        {"name": "Download a monthly report as CSV", "role": "core", "needs": 50,
         "needs_why": "A few lines of its own CSV writing are left. The repo's writer covers them.",
         "ranges": [span("reports/export.py", 1, 70), span("tests/test_export.py", 1, 50)]},
        {"name": "Check that the report belongs to the caller", "role": "core", "needs": 22,
         "needs_why": "Nothing else on this route checks who owns the report.",
         "ranges": [span("reports/export.py", 71, 92), span("tests/test_export.py", 51, 86)]},
    ],
}
AFTER_WEIGHT = [
    {"category": "test_unneeded", "file": "tests/test_export.py", "start": 31, "end": 44,
     "reason": "This test sends the same report as the one above it and checks the same rows.",
     "see": "tests/test_export.py:12"},
    {"category": "code_needless_check", "file": "reports/export.py", "start": 40, "end": 43,
     "reason": "The route already refuses a request with no month, so this second check can never be reached."},
    {"category": "doc_restates_code", "file": "reports/export.py", "start": 3, "end": 5,
     "reason": "The comment says what the function name and its arguments already say."},
    {"category": "docfile_drift_prone", "file": "docs/exports.md", "start": 9, "end": 10,
     "reason": "The text points at line numbers in export.py. They are wrong after the next edit to that file."},
]
AFTER_SUMMARIES = [
    ("Production code", "One check repeats what the route already does."),
    ("Tests", "One test repeats the one above it."),
    ("Comments and docs", "One comment restates the code, and the guide points at line numbers."),
]


def main():
    first = scope.model(FIRST, FIRST_SCOPE)
    after = scope.model(AFTER, AFTER_SCOPE)
    wm = weight.model(AFTER, AFTER_WEIGHT, AFTER_SUMMARIES)
    start = {"scope": first["share"], "weight": None}
    for theme in ("light", "dark"):
        with open(os.path.join(HERE, f"first-push-{theme}.svg"), "w", encoding="utf-8") as fh:
            fh.write(card.render(first, None, theme))
        with open(os.path.join(HERE, f"after-the-cut-{theme}.svg"), "w", encoding="utf-8") as fh:
            fh.write(card.render(after, wm, theme, start=start))
    if "--post" in sys.argv:  # the markdown that goes with the first chart
        print(github.body(first, None, "OWNER/REPO", "HEAD", "first-push-light.svg", "first-push-dark.svg", LIMITS))
    print(f'first push: scope {first["share"]:.0f}% ({first["has"]} lines, {first["need"]} needed)')
    print(f'after the cut: scope {after["share"]:.0f}%, weight {wm["share"]:.0f}% ({wm["flagged"]} of {wm["base"]})')


if __name__ == "__main__":
    main()
