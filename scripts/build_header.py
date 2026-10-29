"""Render assets/header-{dark,light}.svg.

Two steps for the signature: its outline is written letter by letter from
left to right, the underline flourish last, then its colour fill sweeps in
left to right. Then a restoration pass sweeps across a
noisy signal and leaves it clean behind the playhead, a nod to HarmonyRestorer.
The clean waveform uses the same formula as the website's hero waveform.

Deterministic: no clock, no unseeded randomness, so re-running produces
byte-identical files and a diff only ever means an intentional change.

Every animation is CSS and runs once. The resting style of each element is its
final frame and the keyframes only describe how it gets there, so a viewer with
reduced motion, or a renderer that skips animation, sees the finished picture.

Usage: python3 scripts/build_header.py
"""

import json
import math
from pathlib import Path

import sigpath
from brand import MONO, THEMES, gradient

ROOT = Path(__file__).resolve().parent.parent
W, H = 1000, 300
MID, AMP = 228, 30
SIG_H = 150
# A 0.8s lead-in before writing. On github.com the first second after load is
# the busiest (long frames were measured from ~0.5s, 2026-10-18), so the first
# strokes start a little later. This is a mitigation, not a measured fix; cut
# it first if the header ever feels slow.
WRITE_START, WRITE_SECONDS = 0.8, 3.2
# The fill waits for the pen: it starts only once the whole signature,
# underline flourish included, has been written. Everything after keys off it.
WRITE_END = WRITE_START + WRITE_SECONDS
FILL_START, FILL_SECONDS = WRITE_END + 0.15, 1.5
FILL_END = FILL_START + FILL_SECONDS

# The underline flourish, redrawn here rather than taken from the source path.
# The website's version is two long cubics that the 8-segment sampling in
# sigpath.parse turns into visible corners, and its last curve doubles back
# on itself after crossing the J, leaving a hooked stub. This one keeps the
# same sweep out of the i, under the name and across the J, and ends at the
# same point with the same upward flick, but turns into it in one smooth
# curve. Cubic Beziers in signature units, written right to left like the pen.
FLOURISH = (
    ((1196.9, -14.6), (1086.9, 53.4), (760.0, 104.0), (420.0, 102.0)),
    ((420.0, 102.0), (230.0, 101.0), (100.0, 100.0), (95.0, 48.0)),
)


def flourish() -> list[sigpath.Point]:
    """The flourish's centreline, sampled finely enough that no corner shows,
    then simplified like everything else."""
    pts = [sigpath.bezier(c, k / 200) for i, c in enumerate(FLOURISH) for k in range(0 if i == 0 else 1, 201)]
    return sigpath.rdp(pts, sigpath.TOLERANCE)


def with_flourish(subs: list[list[sigpath.Point]], line: list[sigpath.Point]) -> list[list[sigpath.Point]]:
    """Swap the source flourish (the one open subpath spanning the name) for
    the redrawn one, keeping its place in the writing order."""
    span = [max(x for x, _ in p) - min(x for x, _ in p) for p in subs]
    i = span.index(max(span))
    if sigpath.is_closed(subs[i]):
        raise ValueError("expected the flourish to be the widest, open subpath")
    return subs[:i] + [line] + subs[i + 1 :]


def clean_y(t: float) -> float:
    # Same terms as WAVE_PATH in the website's HomeContent.tsx.
    env = math.sin(math.pi * t)
    a = math.sin(t * 21) * 0.55 + math.sin(t * 8.5 + 1.3) * 0.32 + math.sin(t * 38 + 0.7) * 0.14
    return MID - a * env * AMP


def clean_path(n: int = 128) -> str:
    pts = [(i / n * W, clean_y(i / n)) for i in range(n + 1)]
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d += f"Q{x0:.1f} {y0:.1f} {(x0 + x1) / 2:.1f} {(y0 + y1) / 2:.1f}"
    return d


def noisy_path(n: int = 420, seed: int = 7) -> str:
    # Small LCG instead of `random` so the output never depends on the
    # interpreter's RNG implementation.
    state = seed

    def rnd() -> float:
        nonlocal state
        state = (1103515245 * state + 12345) % 2**31
        return state / 2**31 * 2 - 1

    pts = []
    for i in range(n + 1):
        t = i / n
        hiss = rnd() * 13 * (0.35 + 0.65 * math.sin(math.pi * t))
        pts.append((t * W, clean_y(t) + hiss))
    return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts)


def inside(point: sigpath.Point, poly: list[sigpath.Point]) -> bool:
    """Even-odd ray cast against a closed polyline."""
    x, y = point
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def holes(subs: list[list[sigpath.Point]]) -> dict[int, list[int]]:
    """Map each letter's outer contour to its holes: the inside edge of an o,
    of the C's top loop, of the small loop at the top of each J."""
    closed = [i for i, p in enumerate(subs) if sigpath.is_closed(p)]
    out: dict[int, list[int]] = {}
    for h in closed:
        hosts = [o for o in closed if o != h and all(inside(q, subs[o]) for q in subs[h][::3])]
        if hosts:
            # The innermost one, should a hole ever sit inside two contours.
            out.setdefault(min(hosts, key=lambda o: abs(area(subs[o]))), []).append(h)
    return out


def area(p: list[sigpath.Point]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p, p[1:])) / 2


def passing(point: sigpath.Point, outer: list[sigpath.Point]) -> float:
    """How far along `outer` (0..1) its closest point to `point` lies, i.e.
    when the outer edge's tip goes past it."""
    run, best, at = 0.0, float("inf"), 0.0
    for a, b in zip(outer, outer[1:]):
        seg = math.dist(a, b)
        if seg:
            u = max(0.0, min(1.0, ((point[0] - a[0]) * (b[0] - a[0]) + (point[1] - a[1]) * (b[1] - a[1])) / seg**2))
            d = math.dist(point, (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
            if d < best:
                best, at = d, run + seg * u
        run += seg
    return at / run


def alongside(hole: list[sigpath.Point], outer: list[sigpath.Point]):
    """Open a hole where the outer edge first passes it and run it the same
    way round, so it is drawn beside the outer edge rather than after it.
    Returns the hole as a path, and when (as fractions of the outer edge's
    time) its start and end are passed, with keyframes keeping its tip level
    with the outer tip in between."""
    ring = hole[:-1]
    when = [passing(q, outer) for q in ring]
    k = min(range(len(ring)), key=when.__getitem__)
    fwd = ring[k:] + ring[:k] + [ring[k]]
    bwd = fwd[::-1]
    best = None
    for path in (fwd, bwd):
        ts = [passing(q, outer) for q in path]
        ts[0] = min(ts)
        # How far behind the outer tip this way would fall: every point that
        # comes earlier than one before it has to wait. The last point closes
        # the ring onto the first, so it is not evidence; leave it out.
        lag, top = 0.0, 0.0
        for x in ts[:-1]:
            top = max(top, x)
            lag += top - x
        if best is None or lag < best[0]:
            best = (lag, path, ts)
    _, path, ts = best
    t0, t1, keys = pace(path, ts)
    return path, t0, t1, keys


def pace(path: list[sigpath.Point], times: list[float]) -> tuple[float, float, list[tuple[float, float]]]:
    """Keyframes for drawing `path` so that each of its points is reached at
    the given time (any scale). Returns the first and last time and the
    keyframes as (fraction of that span, dash offset), never moving back."""
    mono = []
    for x in times:
        mono.append(max(x, mono[-1]) if mono else x)
    t0, t1 = mono[0], mono[-1]
    run = [0.0]
    for a, b in zip(path, path[1:]):
        run.append(run[-1] + math.dist(a, b))
    if t1 <= t0 or not run[-1]:
        return t0, t0, [(0.0, 1.05), (1.0, 0.0)]  # nothing to pace: draw it straight through
    curve = [(0.0, 1.05)] + [((x - t0) / (t1 - t0), 1 - r / run[-1]) for x, r in zip(mono, run)][1:]
    curve[-1] = (1.0, 0.0)
    keys: list[tuple[float, float]] = []
    for tau, off in sigpath.rdp(curve, 0.02):
        tau, off = round(tau, 3), round(off, 3)  # as written into the CSS
        if not keys or tau > keys[-1][0]:
            keys.append((tau, off))
    if keys[-1][0] == 1.0:
        keys.pop()
    keys.append((1.0, 0.0))
    return t0, t1, keys


# Where the pen starts the big letters, and which way it sets off. The font's
# contours start the J's and the C at the bottom of the bowl, mid-stroke, so
# the pen visibly began in the middle of the letter, or jumped there from the
# end of the stroke leading in; these start where the letter is written from. (start point, a point in the direction of travel),
# signature units. The small letters keep the font's starts.
STARTS = (
    ((23.0, -28.0), (5.0, 0.0)),  # J of Jacob: tip of the bowl, heading round it
    # J. : where the stroke from the b arrives, carrying on round the bowl, so
    # the pen does not jump from the end of that stroke to the J's tip.
    ((524.0, 20.0), (560.0, 75.0)),
    # C: where the stroke from the "J." arrives, heading up the back towards
    # the hairline and the loop.
    ((854.0, -12.0), (850.0, -60.0)),
)


def nearest(ring: list[sigpath.Point], point: sigpath.Point) -> int:
    return min(range(len(ring)), key=lambda k: math.dist(ring[k], point))


def start_at(contour: list[sigpath.Point], start: sigpath.Point, toward: sigpath.Point) -> list[sigpath.Point]:
    """Reopen a closed contour at its point nearest `start`, running in the
    direction whose first steps go toward `toward`."""
    ring = contour[:-1]
    i = nearest(ring, start)
    fwd = ring[i:] + ring[:i]
    bwd = [fwd[0]] + fwd[1:][::-1]

    def heading(path):
        # Where each way has got to 40 units along: near the tip the two sides
        # of a hairline are too close together to tell apart.
        run, b = 0.0, path[-1]
        for a, b in zip(path, path[1:]):
            run += math.dist(a, b)
            if run >= 40:
                break
        return math.dist(b, toward)

    path = min((fwd, bwd), key=heading)
    return path + [path[0]]


def with_starts(subs: list[list[sigpath.Point]]) -> list[list[sigpath.Point]]:
    out = list(subs)
    for start, toward in STARTS:
        gap = [min(math.dist(q, start) for q in p) for p in out]
        i = min(range(len(out)), key=gap.__getitem__)
        if not sigpath.is_closed(out[i]) or gap[i] > 2:
            raise ValueError(f"no closed contour passes through {start}")
        out[i] = start_at(out[i], start, toward)
    return out


def outline_parts(subs: list[list[sigpath.Point]]) -> tuple[list[str], list[str]]:
    """Step 1, the outline: one shape on one timeline, drawn at a constant pen
    speed. It is emitted as one <path> per subpath (letters, connectors,
    flourish, in the source's writing order) only because WebKit restarts a
    dash pattern at every subpath: a single multi-subpath path drew all 21
    pieces at once in Safari instead of one after another.

    A letter's holes take no time of their own: each is drawn beside the part
    of the letter's outer edge that runs past it (see alongside). Drawn after
    the letter instead, the inside of each o and of the C's loop appeared on
    its own once the letter was finished.

    Each piece has pathLength=1 and a dash pattern of 1 on, 2 off. A piece that
    is waiting sits at offset 1.05, which parks the dash entirely before the
    path starts. With the obvious encoding (dasharray 1, offset 1) a zero-length
    dash lands on the path's end and WebKit still paints its round cap there,
    so every waiting piece showed a dot early.
    """
    inner = holes(subs)
    taken = {h for hs in inner.values() for h in hs}
    lengths = [sum(math.dist(a, b) for a, b in zip(p, p[1:])) for p in subs]
    total = sum(n for i, n in enumerate(lengths) if i not in taken)
    parts, keyframes, t = [], [], WRITE_START

    def piece(path, delay, dur, keys=None):
        name = ""
        if keys:
            name = f"k{len(keyframes)}"
            stops = "".join(f"{tau * 100:g}%{{stroke-dashoffset:{off:g}}}" for tau, off in keys)
            keyframes.append(f"@keyframes {name}{{{stops}}}")
            name = f";animation-name:{name}"
        parts.append(
            f'<path d="{sigpath.to_d([path])}" pathLength="1" '
            f'style="animation-delay:{delay:.3f}s;animation-duration:{dur:.3f}s{name}"/>'
        )

    for i, (p, length) in enumerate(zip(subs, lengths)):
        if i in taken:
            continue
        dur = WRITE_SECONDS * length / total
        piece(p, t, dur)
        for h in inner.get(i, []):
            path, t0, t1, keys = alongside(subs[h], p)
            piece(path, t + t0 * dur, (t1 - t0) * dur, keys)
        t += dur
    return parts, keyframes


def render(theme: str, sig: dict) -> str:
    box = sig["box"]
    sig_w = SIG_H * box["w"] / box["h"]
    sig_x = (W - sig_w) / 2
    ink = THEMES[theme]["ink"]
    muted = THEMES[theme]["muted"]
    subs = with_starts(with_flourish(sigpath.simplified(sig["path"]), flourish()))  # see sigpath.py
    # Step 2, the fill: the closed letter contours, revealed left to right by
    # one feathered sweep once the outline is complete. At rest the sweep
    # covers the whole signature with its feather parked past the right edge.
    letters = sigpath.to_d([p for p in subs if sigpath.is_closed(p)])
    feather = 120
    fill_w = box["w"] + 2 * feather
    solid = (box["w"] + feather) / fill_w

    parts, hole_keyframes = outline_parts(subs)
    css = f"""
.outline path{{stroke-dasharray:1 2;stroke-dashoffset:0;animation-name:write;animation-timing-function:linear;animation-fill-mode:both}}
@keyframes write{{from{{stroke-dashoffset:1.05}}to{{stroke-dashoffset:0}}}}
{"".join(hole_keyframes)}
.fill{{animation:fill {FILL_SECONDS}s cubic-bezier(.45,0,.35,1) {FILL_START:.2f}s both}}
@keyframes fill{{from{{transform:translateX(-{fill_w:.1f}px)}}to{{transform:none}}}}
.wave{{opacity:1;animation:fade .6s ease-out {FILL_END - 0.2:.2f}s both}}
.sweep{{animation:sweep 2.6s cubic-bezier(.45,0,.25,1) {FILL_END + 0.2:.2f}s both}}
.head{{opacity:0;animation:head 2.6s cubic-bezier(.45,0,.25,1) {FILL_END + 0.2:.2f}s both}}
.cap{{opacity:1;animation:fade .8s ease-out {FILL_END + 2.6:.2f}s both}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes sweep{{from{{transform:translateX(-{W}px)}}to{{transform:none}}}}
@keyframes head{{0%{{opacity:0}}8%{{opacity:1}}88%{{opacity:1}}100%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.outline path,.fill,.wave,.sweep,.head,.cap{{animation:none!important}}}}
"""
    # The waveform reveal has a hard edge, so it uses clip paths, which are
    # cheaper to composite than luminance masks.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-labelledby="t">
<title id="t">Jacob J. Choi, signature above an audio waveform being restored from noise</title>
<style>{css}</style>
<defs>
{gradient("g", theme, 0, W)}
{gradient("gs", theme, box["x"], box["x"] + box["w"])}
<clipPath id="cc"><rect class="sweep" x="0" y="0" width="{W}" height="{H}"/></clipPath>
<clipPath id="cn"><rect class="sweep" x="{W}" y="0" width="{W}" height="{H}"/></clipPath>
</defs>
<svg x="{sig_x:.1f}" y="18" width="{sig_w:.1f}" height="{SIG_H}" viewBox="{box["x"]} {box["y"]} {box["w"]} {box["h"]}">
<defs>
<linearGradient id="pf"><stop offset="0" stop-color="#fff"/><stop offset="{solid:.4f}" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient>
<mask id="mf" maskUnits="userSpaceOnUse" x="{box["x"] - fill_w}" y="{box["y"]}" width="{2 * fill_w}" height="{box["h"]}"><rect class="fill" x="{box["x"] - feather}" y="{box["y"]}" width="{fill_w}" height="{box["h"]}" fill="url(#pf)"/></mask>
</defs>
<path d="{letters}" mask="url(#mf)" fill="url(#gs)"/>
<g class="outline" fill="none" stroke="url(#gs)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">{"".join(parts)}</g>
</svg>
<g class="wave" fill="none" stroke-linecap="round" stroke-linejoin="round">
<path d="{noisy_path()}" stroke="url(#g)" stroke-width="1.1" opacity=".55" clip-path="url(#cn)"/>
<path d="{clean_path()}" stroke="url(#g)" stroke-width="2" clip-path="url(#cc)"/>
</g>
<g class="head"><g class="sweep">
<line x1="{W}" y1="{MID - 52}" x2="{W}" y2="{MID + 52}" stroke="{ink}" stroke-width="7" opacity=".08"/>
<line x1="{W}" y1="{MID - 52}" x2="{W}" y2="{MID + 52}" stroke="{ink}" stroke-width="1.2" opacity=".85"/>
</g></g>
<text class="cap" x="{W / 2}" y="{H - 8}" text-anchor="middle" font-family="{MONO}" font-size="11" letter-spacing="4.5" fill="{muted}">MELOS CONTRA MUNDUM</text>
</svg>
"""


def main() -> None:
    sig = json.loads((ROOT / "scripts" / "data" / "signature.json").read_text())
    for theme in THEMES:
        out = ROOT / "assets" / f"header-{theme}.svg"
        out.write_text(render(theme, sig))
        print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
