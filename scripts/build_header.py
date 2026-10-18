"""Render assets/header-{dark,light}.svg.

The signature draws itself and fills with ink, then a restoration pass sweeps across a noisy
signal and leaves it clean behind the playhead, a nod to HarmonyRestorer. The
clean waveform uses the same formula as the website's hero waveform.

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
# Writing waits 0.8s: on github.com the page's own scripts freeze the main
# thread for ~200ms shortly after load (measured 2026-10-18), and a pen that
# is already moving visibly jumps. Starting after that keeps the stroke smooth.
WRITE_START, WRITE_SECONDS = 0.8, 3.2
# The fill waits for the pen: it starts only once the whole signature,
# underline flourish included, has been written. Everything after keys off it.
WRITE_END = WRITE_START + WRITE_SECONDS
FILL_START, FILL_SECONDS = WRITE_END + 0.15, 1.5
FILL_END = FILL_START + FILL_SECONDS

INK = {"dark": "#e6edf3", "light": "#1f2328"}


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


def render(theme: str, sig: dict, strokes: list[dict]) -> str:
    box = sig["box"]
    sig_w = SIG_H * box["w"] / box["h"]
    sig_x = (W - sig_w) / 2
    ink = INK[theme]
    muted = THEMES[theme]["muted"]
    # Filled letterforms carry the same visual weight as the sequencer's solid
    # squares below, so the page reads as one system.
    # Simplified geometry (see sigpath.py). The letter contours are defined
    # once and drawn twice via <use>: as the fill and as the outline. The open
    # strokes (connectors, flourish) only ever appear in the outline.
    subs = sigpath.simplified(sig["path"])
    letters = sigpath.to_d([p for p in subs if sigpath.is_closed(p)])
    opens = sigpath.to_d([p for p in subs if not sigpath.is_closed(p)])
    # Two passes. First the outline is signed by hand: each pen stroke runs
    # along a letter's centreline (see build_strokes.py) inside a mask, so the
    # outline appears exactly where the pen has been, at a constant pen speed.
    # Then the colour fill sweeps in left to right behind a feathered edge.
    # At rest every pen stroke is complete and the fill mask covers the whole
    # signature (feather parked past the right edge).
    feather = 120
    fill_w = box["w"] + 2 * feather
    solid = (box["w"] + feather) / fill_w
    # Each pen path has pathLength=1. The dash pattern is 1 on, 2 off, and a
    # waiting stroke sits at offset 1.05, which parks the dash entirely before
    # the path starts. With the obvious encoding (dasharray 1, offset 1) a
    # zero-length dash lands exactly on the path's end, and WebKit (Safari, the
    # GitHub iOS app) still paints its round cap there: every waiting stroke
    # left a dot that showed fragments of later letters early.
    pen = []
    total = sum(st["length"] for st in strokes)
    t = WRITE_START
    for st in strokes:
        dur = WRITE_SECONDS * st["length"] / total
        pen.append(
            f'<path d="{st["d"]}" stroke-width="{st["width"]}" pathLength="1" '
            f'style="animation-delay:{t:.3f}s;animation-duration:{dur:.3f}s"/>'
        )
        t += dur

    css = f"""
.pen path{{stroke-dasharray:1 2;stroke-dashoffset:0;animation-name:write;animation-timing-function:linear;animation-fill-mode:both}}
@keyframes write{{from{{stroke-dashoffset:1.05}}to{{stroke-dashoffset:0}}}}
.ink{{animation:ink {FILL_SECONDS}s cubic-bezier(.45,0,.35,1) {FILL_START:.2f}s both}}
@keyframes ink{{from{{transform:translateX(-{fill_w:.1f}px)}}to{{transform:none}}}}
.wave{{opacity:1;animation:fade .6s ease-out {FILL_END - 0.2:.2f}s both}}
.sweep{{animation:sweep 2.6s cubic-bezier(.45,0,.25,1) {FILL_END + 0.2:.2f}s both}}
.head{{opacity:0;animation:head 2.6s cubic-bezier(.45,0,.25,1) {FILL_END + 0.2:.2f}s both}}
.cap{{opacity:1;animation:fade .8s ease-out {FILL_END + 2.6:.2f}s both}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes sweep{{from{{transform:translateX(-{W}px)}}to{{transform:none}}}}
@keyframes head{{0%{{opacity:0}}8%{{opacity:1}}88%{{opacity:1}}100%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.pen path,.ink,.wave,.sweep,.head,.cap{{animation:none}}}}
"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-labelledby="t">
<title id="t">Jacob J. Choi, signature above an audio waveform being restored from noise</title>
<style>{css}</style>
<defs>
{gradient("g", theme, 0, W)}
{gradient("gs", theme, box["x"], box["x"] + box["w"])}
<mask id="mc" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}"><rect class="sweep" x="0" y="0" width="{W}" height="{H}" fill="#fff"/></mask>
<mask id="mn" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}"><rect class="sweep" x="{W}" y="0" width="{W}" height="{H}" fill="#fff"/></mask>
</defs>
<svg x="{sig_x:.1f}" y="18" width="{sig_w:.1f}" height="{SIG_H}" viewBox="{box["x"]} {box["y"]} {box["w"]} {box["h"]}">
<defs>
<mask id="mw" maskUnits="userSpaceOnUse" x="{box["x"]}" y="{box["y"]}" width="{box["w"]}" height="{box["h"]}">
<g class="pen" fill="none" stroke="#fff" stroke-linecap="round" stroke-linejoin="round">{"".join(pen)}</g>
</mask>
<linearGradient id="pf"><stop offset="0" stop-color="#fff"/><stop offset="{solid:.4f}" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient>
<mask id="mf" maskUnits="userSpaceOnUse" x="{box["x"] - fill_w}" y="{box["y"]}" width="{2 * fill_w}" height="{box["h"]}"><rect class="ink" x="{box["x"] - feather}" y="{box["y"]}" width="{fill_w}" height="{box["h"]}" fill="url(#pf)"/></mask>
<path id="L" d="{letters}"/>
</defs>
<use href="#L" mask="url(#mf)" fill="url(#gs)"/>
<g mask="url(#mw)" fill="none" stroke="url(#gs)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><use href="#L"/><path d="{opens}"/></g>
</svg>
<g class="wave" fill="none" stroke-linecap="round" stroke-linejoin="round">
<path d="{noisy_path()}" stroke="url(#g)" stroke-width="1.1" opacity=".55" mask="url(#mn)"/>
<path d="{clean_path()}" stroke="url(#g)" stroke-width="2" mask="url(#mc)"/>
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
    pen = json.loads((ROOT / "scripts" / "data" / "signature_strokes.json").read_text())
    # The strokes are derived from one exact signature path; refuse to pair
    # them with a different one.
    assert pen["source_path_sha256"] == sig["path_sha256"], "re-run build_strokes.py"
    assert pen["tolerance"] == sigpath.TOLERANCE and pen["geometry_sha256"] == sigpath.geometry_hash(
        sigpath.simplified(sig["path"])
    ), "pens were fitted to different geometry; re-run build_strokes.py"
    for theme in THEMES:
        out = ROOT / "assets" / f"header-{theme}.svg"
        out.write_text(render(theme, sig, pen["strokes"]))
        print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
