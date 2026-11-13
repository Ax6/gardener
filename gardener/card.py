"""Draw the review as one SVG card, in a light and a dark version.

GitHub strips styles from comments, so the chart is an image. An image cannot
load fonts, so text uses whatever the reader's system has, emoji included.

Colours carry two different things and never mix:
  outcome   green ok, yellow borderline, red above the limit, grey not run
  data      what the lines are (production, tests, docs) and which are extra
"""

import math

from .lines import BUCKETS, LABEL
from .weight import percent

THEMES = {
    "light": {
        "surface": "#fcfcfb", "border": "#e1e0d9", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "track": "#eceae4", "production": "#2a78d6", "tests": "#eb6834", "docs": "#1baf7a", "config": "#eda100",
        "generated": "#c3c2b7", "extra": "#e87ba4", "keep": "#2f9e5c",
        "good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b",
        "dark_label": {"config", "generated"},
        # Filled outcome pills: (fill, text). Each pair is at least 4.8 to 1.
        "pill": {"pass": ("#0a7a0a", "#ffffff"), "warn": ("#fab219", "#0b0b0b"), "fail": ("#b92d2d", "#ffffff"), "skip": ("#6b6a66", "#ffffff")},
    },
    "dark": {
        "surface": "#1a1a19", "border": "#2c2c2a", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
        "track": "#2c2c2a", "production": "#3987e5", "tests": "#d95926", "docs": "#199e70", "config": "#c98500",
        "generated": "#52514e", "extra": "#d55181", "keep": "#3aa866",
        "good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b",
        "dark_label": set(),
        "pill": {"pass": ("#0ca30c", "#0b0b0b"), "warn": ("#fab219", "#0b0b0b"), "fail": ("#d03b3b", "#ffffff"), "skip": ("#5c5b57", "#ffffff")},
    },
}
OUTCOME = {"pass": ("🌱", "Ok"), "warn": ("⚠️", "Borderline"), "fail": ("🥀", "Above the limit"), "skip": ("💤", "Not run")}
FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif"
W, P = 800, 32
RIGHT = W - P


def text_width(s, size, bold=False):
    """Rough width of system-sans text. Only used to decide where things fit."""
    return sum(0.28 if ch in " .,:·'|il" else 0.6 for ch in str(s)) * size * (1.06 if bold else 1.0)


def wrap(s, size, width, max_lines):
    lines, cur = [], ""
    for word in str(s).split():
        t = f"{cur} {word}" if cur else word
        if text_width(t, size) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = t
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while " " in lines[-1] and text_width(lines[-1] + "…", size) > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def outcome(share, limits):
    """limits is (ok below, above the limit over). Between the two is borderline."""
    lo, hi = limits
    return "fail" if share > hi else ("warn" if share >= lo else "pass")


class Canvas:
    def __init__(self, theme):
        self.c = THEMES[theme]
        self.o = []

    @staticmethod
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def text(self, x, y, s, size=13, fill=None, weight=400, anchor="start"):
        self.o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
                      f'fill="{fill or self.c["ink"]}" text-anchor="{anchor}">{self.esc(s)}</text>')

    def lead(self, x, y, bold, rest, size=13):
        """A bold lead-in followed by quieter text, on one line."""
        self.o.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{self.c["ink2"]}">'
                      f'<tspan font-weight="600" fill="{self.c["ink"]}">{self.esc(bold)}</tspan>{self.esc(rest)}</text>')

    def rect(self, x, y, w, h, fill, r=0, opacity=None, stroke=None):
        extra = (f' fill-opacity="{opacity}"' if opacity is not None else "") + (f' stroke="{stroke}"' if stroke else "")
        self.o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h}" rx="{r}" fill="{fill}"{extra}/>')

    def line(self, x1, y1, x2, y2, stroke=None, width=1, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.o.append(f'<line x1="{x1:.1f}" y1="{y1}" x2="{x2:.1f}" y2="{y2}" stroke="{stroke or self.c["border"]}" '
                      f'stroke-width="{width}" stroke-linecap="round"{d}/>')

    def rule(self, y):
        self.line(P, y, RIGHT, y)

    def pill(self, xr, cy, state):
        """An outcome, right-aligned at xr: filled with its colour, the emoji on its own disc."""
        emoji, word = OUTCOME[state]
        fill, ink = self.c["pill"][state]
        h, size = 28, 12.5
        w = h + text_width(word, size, True) + 20
        self.rect(xr - w, cy - h / 2, w, h, fill, h / 2)
        self.o.append(f'<circle cx="{xr - w + h / 2:.1f}" cy="{cy:.1f}" r="{h / 2 - 3}" fill="{self.c["surface"]}"/>')
        self.text(xr - w + h / 2, cy + 4.6, emoji, 13, anchor="middle")
        self.text(xr - w + h + 6, cy + size * 0.36, word, size, ink, 700)

    def split_bar(self, x, y, width, height, parts, radius=4):
        """Parts of one whole, with a 2px gap. Returns the x where each part ends."""
        parts = [(k, v) for k, v in parts if v > 0]
        if not parts:
            return []
        room = width - 2 * (len(parts) - 1)
        total = sum(v for _, v in parts)
        widths = [max(6.0, room * v / total) for _, v in parts]
        widths[max(range(len(widths)), key=lambda i: widths[i])] -= sum(widths) - room
        ends = []
        for (colour, v), w in zip(parts, widths):
            self.rect(x, y, w, height, colour, radius)
            ends.append((x, w, v))
            x += w + 2
        return ends


X_RESULT, X_METER, METER_W = 178, 452, 150


def _step(cv, y, badge, name, state, pct, phrase, share, limits, scale, note="", start=None):
    """One row: badge, name, result in words, meter, outcome. The meter's track and marks are
    neutral; only its fill takes the outcome colour. `start` is the score of the first review of
    this pull request; when it differs, a thin labelled bar above the meter shows where the PR began."""
    c, ran = cv.c, state != "skip"
    tones = {"pass": c["good"], "warn": c["warning"], "fail": c["critical"], "skip": c["muted"]}
    tone = tones[state]
    moved = ran and start is not None and percent(start) != pct
    cv.o.append(f'<circle cx="{P + 12}" cy="{y}" r="12" fill="none" stroke="{c["border"]}" stroke-width="1.5"/>')
    cv.text(P + 12, y + 5, badge, 13, anchor="middle")
    cv.text(P + 36, y + 5.5, name, 16, c["ink"] if ran else c["muted"], 600)
    if ran:
        cv.text(X_RESULT, y + 10, f"{pct}%", 28, weight=600)
        x_phrase = X_RESULT + text_width(f"{pct}%", 28, True) + 10
        cv.text(x_phrase, y + 6, phrase, 13, c["ink2"])
    else:
        cv.text(X_RESULT, y + 5, note, 13, c["muted"])
    cv.rect(X_METER, y - 5, METER_W, 10, c["muted"], 5, opacity=0.2)
    if ran:
        xs = [X_METER + METER_W * v / scale for v in limits]
        cv.rect(xs[0], y - 5, xs[1] - xs[0], 10, c["muted"], 0, opacity=0.32)  # the borderline zone
        if share > 0:
            cv.rect(X_METER, y - 5, max(10, METER_W * min(share, scale) / scale), 10, tone, 5)
        if moved:
            # Two labelled bars: a thin one for the first review, the main one for now.
            cv.rect(X_METER, y - 16, max(6, METER_W * min(start, scale) / scale), 4, tones[outcome(start, limits)], 2, opacity=0.6)
            cv.text(X_METER - 8, y - 10.5, f"start {percent(start)}%", 10.5, c["muted"], anchor="end")
            cv.text(X_METER - 8, y + 3.5, "now", 10.5, c["muted"], anchor="end")
        for lx in xs:
            cv.line(lx, y - (18 if moved else 9), lx, y + 9, c["ink"], 1.5)
        if xs[1] - xs[0] < 34:
            cv.text((xs[0] + xs[1]) / 2, y + 24, f"{limits[0]:g} to {limits[1]:g}%", 11, c["muted"], anchor="middle")
        else:
            for lx, v in zip(xs, limits):
                cv.text(lx, y + 24, f"{v:g}%", 11, c["muted"], anchor="middle")
    cv.pill(RIGHT, y, state)


def _scope_detail(cv, sm, y, max_pieces):
    """Purpose, one bar split into needed and extra, then the pieces that carry the extra."""
    c = cv.c
    for i, line in enumerate(wrap("Purpose. " + sm["purpose"], 13, RIGHT - P, 2)):
        if i == 0:
            cv.lead(P, y, "Purpose.", line[len("Purpose."):])
        else:
            cv.text(P, y + 19 * i, line, 13, c["ink2"])
        last = y + 19 * i
    y = last + 26
    ends = cv.split_bar(P, y, RIGHT - P, 18, [(c["keep"], sm["need"]), (c["extra"], sm["extra"]), (c["generated"], sm["unsure"])])
    if sm["extra"] and sm["need"]:
        cut = ends[0][0] + ends[0][1] + 1
        cv.line(cut, y - 7, cut, y + 25, c["ink"], 1.5, dash="3 3")  # where the shears go
        cv.text(cut, y - 10, "✂️", 13, anchor="middle")
    y += 35
    cv.lead(P, y, f'{sm["need"]:,}', " lines needed", 12)
    if sm["extra"]:
        label = f'{sm["extra"]:,} more than it needs'
        cv.o.append(f'<text x="{RIGHT}" y="{y}" font-size="12" fill="{c["ink2"]}" text-anchor="end">'
                    f'<tspan font-weight="600" fill="{c["ink"]}">{sm["extra"]:,}</tspan> more than it needs</text>')
    for r in sm["over"][:max_pieces]:
        y += 22
        name = r["name"] if len(r["name"]) <= 62 else r["name"][:61].rstrip() + "…"
        tail = f'has {r["has"]}, needs {r["needs"]}' if r["role"] == "core" else f'{r["has"]} lines'
        cv.lead(P, y, f'{r["kind"]}:', f" {name}, {tail}")
    if len(sm["over"]) > max_pieces:
        y += 22
        cv.text(P, y, f'and {len(sm["over"]) - max_pieces} more', 13, c["muted"])
    return y


def _weight_detail(cv, wm, y):
    """What the PR adds, split by kind of file, then four tiles: how much of each was flagged."""
    c = cv.c
    cv.text(P, y, "What this PR adds", 13, weight=600)
    cv.text(RIGHT, y, f'{wm["added"]} added  ·  {wm["removed"]} removed  ·  {wm["nfiles"]} files', 12, c["ink2"], anchor="end")
    parts = [(b, wm["t"][b]["added"]) for b in BUCKETS if wm["t"][b]["added"] > 0]
    ends = cv.split_bar(P, y + 14, RIGHT - P, 28, [(c[b], v) for b, v in parts])
    inside = set()
    for (b, v), (x, w, _) in zip(parts, ends):
        if w >= text_width(v, 13, True) + 22:
            inside.add(b)
            cv.text(x + 10, y + 33, v, 13, "#0b0b0b" if b in c["dark_label"] else "#ffffff", 600)
    x = P
    for b, v in parts:
        cv.rect(x, y + 59, 10, 10, c[b], 2)
        cv.text(x + 16, y + 69, LABEL[b], 13, c["ink2"])
        x += 16 + text_width(LABEL[b], 13)
        if b not in inside:
            cv.text(x + 6, y + 69, v, 13, weight=600)
            x += 6 + text_width(v, 13, True)
        x += 24
    cv.rule(y + 94)
    colw = (RIGHT - P - 40) / 2
    top = y + 128
    for i, p in enumerate(wm["panels"]):
        x, y0 = P + (i % 2) * (colw + 40), top + (i // 2) * 132
        cv.text(x, y0, p["title"], 13, weight=600)
        cv.text(x, y0 + 40, p["total"], 28, weight=600)
        cv.text(x + text_width(p["total"], 28, True) + 8, y0 + 40, "lines", 13, c["ink2"])
        cv.rect(x, y0 + 54, 132, 8, c["track"], 4)
        if p["flagged"] and p["total"]:
            cv.rect(x, y0 + 54, max(8, 132 * p["flagged"] / p["total"]), 8, c["extra"], 4)
        share = f' ({100 * p["flagged"] / p["total"]:.0f}%)' if p["flagged"] and p["total"] else ""
        cv.text(x, y0 + 82, f'{p["flagged"]} flagged{share}', 12, c["ink2"])
        for j, (label, v) in enumerate(p["rows"]):
            cv.text(x + 164, y0 + 34 + j * 24, label, 13, c["ink2"] if v else c["muted"])
            cv.text(x + colw, y0 + 34 + j * 24, v, 13, c["ink"] if v else c["muted"], 600 if v else 400, "end")
    return top + 132 + 82


def render(sm, wm, theme, scope_limits=(20, 30), weight_limits=(10, 15), start=None):
    """sm: scope model. wm: weight model, or None when the weight step did not run.
    start: {"scope": share, "weight": share or None} from the first review, on later runs."""
    start = start or {}
    cv = Canvas(theme)
    c = cv.c
    s_state = outcome(sm["share"], scope_limits)
    w_state = outcome(wm["share"], weight_limits) if wm else "skip"
    cv.text(P, 52, "🪴 Gardener review", 17, weight=600)
    # Each meter has its own scale: wide enough for its score now and at the start, never under 40%.
    scale = lambda *shares: max(40, 10 * math.ceil(max(v or 0 for v in shares) / 10))

    y1 = 98
    _step(cv, y1, "✂️", "Scope", s_state, percent(sm["share"]), "more than it needs", sm["share"], scope_limits,
          scale(sm["share"], start.get("scope")), start=start.get("scope"))
    y = _scope_detail(cv, sm, y1 + 56, 3 if wm else 6)
    cv.rule(y + 24)
    y2 = y + 64
    if wm:
        _step(cv, y2, "🌿", "Weight", w_state, percent(wm["share"]), "of added lines flagged", wm["share"], weight_limits,
              scale(wm["share"], start.get("weight")), start=start.get("weight"))
        height = _weight_detail(cv, wm, y2 + 68) + 32
    else:
        _step(cv, y2, "🌿", "Weight", "skip", "", "", 0, weight_limits, 40, note=f"Runs once scope is under {scope_limits[1]:g}%")
        height = y2 + 44
    title = f'Gardener review. Scope: {percent(sm["share"])}% more than it needs, {OUTCOME[s_state][1]}. ' + (
        f'Weight: {percent(wm["share"])}% of added lines flagged, {OUTCOME[w_state][1]}.' if wm else "Weight: not run.")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" viewBox="0 0 {W} {height:.0f}" role="img" '
            f'font-family="{FONT}"><title>{cv.esc(title)}</title>'
            f'<rect x="0.5" y="0.5" width="{W - 1}" height="{height - 1:.0f}" rx="14" fill="{c["surface"]}" stroke="{c["border"]}"/>'
            + "".join(cv.o) + "</svg>\n")
