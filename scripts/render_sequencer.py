"""Render the contribution calendar as a step sequencer.

Same grid as GitHub's graph (weeks as columns, Sunday-first rows), recoloured
in the site's sweep. A playhead loops across the weeks and every active day
flashes as it passes, like a step being triggered.

All input comes through contributions.py, which validates it first. The SVG
is built only from those validated integers and dates plus fixed strings, and
text nodes are XML-escaped anyway, so a later change cannot quietly turn this
into an injection point. Every animation is CSS; each element's resting style
is the static picture, so reduced motion or a renderer without animation still
shows the full calendar.

Usage: GITHUB_TOKEN=... python3 scripts/render_sequencer.py OUT_DIR
"""

import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from brand import MONO, THEMES, gradient
from contributions import ACCOUNTS, fetch, merge, parse_calendar, write_atomic

CELL, GAP = 14, 4
STEP = CELL + GAP
LEFT, TOP = 36, 30
WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")  # row order, Sunday first
LOOP = 9.0  # seconds per pass of the playhead

EMPTY = {"dark": "#161b22", "light": "#eff2f5"}
# The passing step brightens a cell in both themes. A dark flash on white
# read as a shadow rather than a note being struck.
FLASH = {"dark": "#ffffff", "light": "#ffffff"}
# Dark mode: a thin white line. Light mode: a wider translucent white beam
# that lifts the colour of every square it passes, so the step reads as
# light hitting the grid rather than a dark bar crossing it.
PLAYHEAD = {"dark": (2, "#ffffff", 0.7), "light": (8, "#ffffff", 0.75)}
# Light mode outlines every square and sets all text in near-black (GitHub's
# own text colour) so the grid stays crisp on white. Dark mode needs neither.
OUTLINE = {"dark": None, "light": "#1f2328"}
TEXT = {"dark": THEMES["dark"]["muted"], "light": "#1f2328"}
LEVEL_OPACITY = (0, 0.32, 0.55, 0.78, 1.0)


def levels(counts: list[int]) -> list[int]:
    """Quartiles of the non-zero days, the way GitHub buckets its graph."""
    nz = sorted(c for c in counts if c)
    if not nz:
        return [0] * len(counts)
    q = [nz[int(len(nz) * f)] for f in (0.25, 0.5, 0.75)]
    return [0 if c == 0 else 1 + sum(c > t for t in q) for c in counts]


def render(days, theme: str) -> str:
    pal = THEMES[theme]
    offset = (days[0][0].weekday() + 1) % 7  # Sunday = row 0
    cols = (len(days) + offset + 6) // 7
    grid_w = cols * STEP - GAP
    W = LEFT + grid_w
    H = TOP + 7 * STEP - GAP + 34
    lv = levels([c for _, c in days])

    cells, flashes, col_month = [], [], []
    for i, ((d, c), level) in enumerate(zip(days, lv)):
        col, row = divmod(i + offset, 7)
        x, y = LEFT + col * STEP, TOP + row * STEP
        if level:
            cells.append(
                f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" fill="url(#g)" fill-opacity="{LEVEL_OPACITY[level]}"/>'
            )
            ring = '<rect class="r" x="{0}" y="{1}" width="{2}" height="{2}" rx="3"/>'.format(x, y, CELL) if level >= 3 else ""
            flashes.append(
                f'<g class="k{col}"><rect class="f" x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3"/>{ring}</g>'
            )
        else:
            cells.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" fill="{EMPTY[theme]}"/>')
        if row == 0 or i == 0:
            col_month.append((col, x, d))

    # Label each column where the month changes, including the partial month the
    # year starts in. A three-letter label needs two columns (36 units at
    # 11px); only when two labels are a single column apart is the earlier
    # one dropped, since the later month owns more of the grid.
    marks = []
    for col, x, d in col_month:
        if marks and (marks[-1][2].year, marks[-1][2].month) == (d.year, d.month):
            continue
        if marks and col - marks[-1][0] < 2:
            marks.pop()
        marks.append((col, x, d))
    months = [f'<text x="{x}" y="{TOP - 10}">{escape(d.strftime("%b"))}</text>' for _, x, d in marks]

    delays = "".join(f".k{c} *{{animation-delay:{c / cols * LOOP:.3f}s}}" for c in range(cols))
    css = f"""
.f{{fill:{FLASH[theme]};opacity:0;animation:flash {LOOP}s linear infinite}}
.r{{fill:none;stroke:url(#g);stroke-width:1.5;opacity:0;transform-box:fill-box;transform-origin:center;animation:ring {LOOP}s ease-out infinite}}
.ph{{opacity:0;animation:ph {LOOP}s linear infinite}}
@keyframes flash{{0%{{opacity:.85}}7%{{opacity:0}}100%{{opacity:0}}}}
@keyframes ring{{0%{{opacity:.9;transform:scale(1)}}9%{{opacity:0;transform:scale(2.1)}}100%{{opacity:0;transform:scale(2.1)}}}}
@keyframes ph{{from{{opacity:1;transform:translateX(0)}}to{{opacity:1;transform:translateX({grid_w}px)}}}}
@media (prefers-reduced-motion:reduce){{.f,.r,.ph{{animation:none}}}}
{delays}
"""
    legend_x = W - 136  # "Less" + five swatches + "More"
    legend = "".join(
        f'<rect x="{legend_x + 32 + k * 14}" y="{H - 16}" width="10" height="10" rx="2" '
        + (f'fill="{EMPTY[theme]}"' if k == 0 else f'fill="url(#g)" fill-opacity="{LEVEL_OPACITY[k]}"')
        + "/>"
        for k in range(5)
    )
    start, end = days[0][0], days[-1][0]
    edge = f' stroke="{OUTLINE[theme]}" stroke-width="1"' if OUTLINE[theme] else ""
    ph_w, ph_fill, ph_op = PLAYHEAD[theme]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-labelledby="t">
<title id="t">{escape(f"Contribution calendar, {start:%b %Y} to {end:%b %Y}, drawn as a step sequencer")}</title>
<style>{css}</style>
<defs>{gradient("g", theme, LEFT, W)}</defs>
<g font-family="{MONO}" font-size="11" fill="{TEXT[theme]}">
{"".join(months)}
{"".join(f'<text x="0" y="{TOP + r * STEP + 11}">{name}</text>' for r, name in enumerate(WEEKDAYS))}
<text x="{LEFT}" y="{H - 6}">{escape(f"{start:%b %Y} – {end:%b %Y} · Personal + Work Accounts")}</text>
<text x="{legend_x}" y="{H - 6}">Less</text><text x="{W}" y="{H - 6}" text-anchor="end">More</text>
</g>
<g{edge}>{"".join(cells)}{legend}</g>
<g class="ph"><rect x="{LEFT - 2 - ph_w / 2}" y="{TOP - 4}" width="{ph_w}" height="{7 * STEP - GAP + 8}" rx="{ph_w / 2}" fill="{ph_fill}" opacity="{ph_op}"/></g>
{"".join(flashes)}
</svg>
"""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 2
    calendars = [parse_calendar(fetch(login, token), login) for login in ACCOUNTS]
    # Per-account totals are public on each profile page. Logging them shows
    # whether this token can see each account's calendar, so a merge that
    # silently drops one account is visible in the run log.
    for login, cal in zip(ACCOUNTS, calendars):
        print(f"{login}: {sum(cal.values()):,} contributions")
    days = merge(calendars)
    rendered = {theme: render(days, theme) for theme in THEMES}
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for theme, svg in rendered.items():
        write_atomic(out / f"sequencer-{theme}.svg", svg)
    print(f"{len(days)} days rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
