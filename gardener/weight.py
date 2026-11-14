"""Weight: added lines that are a repeat, a dead check or an unneeded test.

The reviewer returns line ranges with one category each. This module counts
the added lines of the right kind inside those ranges. A range may be loose;
only lines the PR added, of the kind the category applies to, are counted,
and a line is counted once however many findings cover it.
"""

from .lines import UNCOUNTED, totals

# category -> (family, label). The family decides which added lines a finding may count.
CATEGORIES = {
    "doc_restates_code": ("doc", "Restates the code"),
    "doc_repeats_doc": ("doc", "Repeats another comment"),
    "doc_drift_prone": ("doc", "Likely to drift"),
    "code_duplicate": ("code", "Duplicates existing code"),
    "code_needless_check": ("code", "Needless check"),
    "code_copied_rule": ("code", "Rule copied from elsewhere"),
    "test_unneeded": ("test", "Unneeded edge case"),
    "test_mergeable": ("test", "Test could be merged"),
    "docfile_drift_prone": ("docfile", "Likely to drift"),
    "docfile_repeats": ("docfile", "Repeats another doc"),
}


def apply_findings(stats, findings):
    """Returns (line sets per category, findings that counted, findings that matched nothing)."""
    by_path = {f["path"]: f for f in stats["files"]}
    flagged = {c: set() for c in CATEGORIES}
    taken = {"doc": set(), "code": set(), "test": set(), "docfile": set()}
    kept, dropped = [], []
    for fd in findings:
        cat, f = fd.get("category"), by_path.get(fd.get("file"))
        if cat not in CATEGORIES or f is None or f["bucket"] in UNCOUNTED:
            dropped.append(fd)
            continue
        family = CATEGORIES[cat][0]
        try:
            lo, hi = int(fd["start"]), int(fd["end"])
        except (KeyError, TypeError, ValueError):
            dropped.append(fd)
            continue
        hits = set()
        for no, kind, _ in f["lines"]:
            if not lo <= no <= hi or kind == "blank":
                continue
            if family == "doc" and kind != "doc":
                continue
            if family == "code" and (kind != "code" or f["bucket"] != "production"):
                continue
            if family == "test" and f["bucket"] != "tests":
                continue
            if family == "docfile" and (f["bucket"] != "docs" or kind != "prose"):
                continue
            key = (f["path"], no)
            if key not in taken[family]:
                hits.add(key)
        if not hits:
            dropped.append(fd)
            continue
        taken[family] |= hits
        flagged[cat] |= hits
        kept.append({**fd, "lines": len(hits), "hits": sorted(no for _, no in hits)})
    return flagged, kept, dropped


def model(stats, findings, summaries=()):
    """Every number the weight step shows, in one place."""
    t = totals(stats)
    flagged, kept, dropped = apply_findings(stats, findings)
    n = lambda cat: len(flagged[cat])
    prod_code = t["production"]["code"]
    doc_total = t["production"]["doc"] + t["tests"]["doc"]
    test_lines = t["tests"]["code"] + t["tests"]["doc"]
    doc_files = t["docs"]["prose"]
    union = set().union(*flagged.values())
    base = prod_code + t["production"]["doc"] + test_lines + doc_files
    panels = [
        ("Production code", prod_code, ("code_duplicate", "code_needless_check", "code_copied_rule")),
        ("Comments and docstrings", doc_total, ("doc_restates_code", "doc_repeats_doc", "doc_drift_prone")),
        ("Tests", test_lines, ("test_unneeded", "test_mergeable")),
        ("Doc files", doc_files, ("docfile_drift_prone", "docfile_repeats")),
    ]
    return {
        "t": t,
        "added": sum(b["added"] for b in t.values()),
        "removed": sum(b["removed"] for b in t.values()),
        "nfiles": len(stats["files"]),
        "panels": [
            {"title": title, "total": total, "flagged": len(set().union(*(flagged[c] for c in cats))),
             "rows": [(CATEGORIES[c][1], n(c)) for c in cats]}
            for title, total, cats in panels
        ],
        "flagged": len(union),
        "base": base,
        "share": 100 * len(union) / base if base else 0.0,
        "kept": kept,
        "dropped": dropped,
        "summaries": [(name, text) for name, text in summaries if text],
        "tests_per_code": (test_lines, prod_code),
    }


def percent(share):
    return "<1" if 0 < share < 1 else f"{share:.0f}"
