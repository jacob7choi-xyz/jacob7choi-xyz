"""Run: python3 -m unittest discover -s scripts"""

import json
import math
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import build_header

import sigpath

ROOT = Path(__file__).resolve().parent.parent
SIG = json.loads((ROOT / "scripts" / "data" / "signature.json").read_text())


def css(svg: str) -> str:
    return svg.split("<style>")[1].split("</style>")[0]


def resting_transforms(svg: str) -> list[str]:
    """CSS lines outside @keyframes that set a transform. The finished picture
    must come from geometry alone, so a renderer that skips animation, or
    reduced motion, still shows it; this should always be empty."""
    return [l for l in css(svg).splitlines() if not l.startswith("@keyframes") and "transform:" in l]


class Header(unittest.TestCase):
    def setUp(self):
        self.svg = {t: build_header.render(t, SIG) for t in ("dark", "light")}

    def test_wellformed_and_static_at_rest(self):
        for svg in self.svg.values():
            ET.fromstring(svg)
            self.assertEqual(resting_transforms(svg), [])

    def test_waiting_outline_pieces_paint_nothing(self):
        # Regression: WebKit paints a round cap even for a zero-length dash, so
        # a waiting stroke must not have ANY dash touching [0, pathLength=1].
        c = css(self.svg["dark"])
        d, g = map(float, re.search(r"\.outline path\{stroke-dasharray:([\d.]+) ([\d.]+)", c).groups())
        o = float(re.search(r"@keyframes write\{from\{stroke-dashoffset:([\d.]+)\}", c).group(1))
        period = d + g
        for k in range(-3, 4):
            start, end = k * period - o, k * period - o + d
            touches = start <= 1 and end >= 0
            self.assertFalse(touches, f"dash [{start}, {end}] touches the path")
        # ...and at rest the first dash covers the whole path.
        self.assertGreaterEqual(d, 1)

    def test_fill_waits_for_the_pen(self):
        c = css(self.svg["dark"])
        ends = [float(a) + float(b) for a, b in re.findall(r"animation-delay:([\d.]+)s;animation-duration:([\d.]+)s", self.svg["dark"])]
        fill = float(re.search(r"\.fill\{animation:fill [\d.]+s \S+ ([\d.]+)s", c).group(1))
        self.assertLess(max(ends), fill)

    def test_two_steps_and_one_mask(self):
        # Step 1: one outline piece per subpath, nothing else animated per
        # piece. Step 2: one fill. The only mask is the fill's feathered edge;
        # masks with animated content were what made the live page janky.
        svg = self.svg["dark"]
        pieces = re.findall(r"animation-delay:", svg)
        self.assertEqual(len(pieces), len(sigpath.simplified(SIG["path"])))
        self.assertEqual(svg.count("<mask"), 1)
        self.assertEqual(svg.count('class="fill"'), 1)

    def test_flourish_ends_without_a_hook(self):
        # The source flourish doubled back after crossing the J (x turned
        # around) through a 54 degree corner. The redrawn one must keep
        # moving left and never turn sharply between samples.
        f = build_header.flourish()
        self.assertTrue(all(b[0] <= a[0] for a, b in zip(f, f[1:])))
        for a, b, c in zip(f, f[1:], f[2:]):
            u, v = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
            turn = abs(math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])))
            self.assertLess(turn, 25)

    def test_flourish_replaces_the_source_one(self):
        subs = build_header.with_flourish(sigpath.simplified(SIG["path"]), build_header.flourish())
        self.assertEqual(len(subs), len(sigpath.simplified(SIG["path"])))
        self.assertIn(build_header.flourish(), subs)
        self.assertEqual(subs[-1], build_header.flourish())  # still written last

    def test_big_letters_start_where_they_are_written_from(self):
        # The font starts the J's and the C mid-stroke at the bottom of the
        # bowl; each is reopened at its starting tip instead, and drawn in one
        # pass that ends back there.
        subs = build_header.with_starts(sigpath.simplified(SIG["path"]))
        for start, _ in build_header.STARTS:
            contour = min((p for p in subs if sigpath.is_closed(p)), key=lambda p: math.dist(p[0], start))
            self.assertLess(math.dist(contour[0], start), 2)
            self.assertEqual(contour[0], contour[-1])
        before = sigpath.simplified(SIG["path"])
        self.assertEqual(sorted(len(p) for p in subs), sorted(len(p) for p in before))  # same points, reordered

    def test_letters_start_where_the_stroke_leading_in_ends(self):
        # The "J." and the C each start exactly where the thin stroke leading
        # into them arrives, so the pen does not jump.
        subs = build_header.with_starts(sigpath.simplified(SIG["path"]))
        for connector, letter in ((7, 8), (12, 13)):
            self.assertLess(math.dist(subs[connector][-1], subs[letter][0]), 5)

    def test_c_climbs_its_back_into_the_loop_first(self):
        subs = build_header.with_starts(sigpath.simplified(SIG["path"]))
        c = subs[13]
        loop_top = min((k for k in range(len(c)) if c[k][0] > 940), key=lambda k: c[k][1])  # top of the loop
        bottom = max(range(len(c)), key=lambda k: c[k][1])  # bottom of the C
        self.assertLess(loop_top, bottom)

    def test_holes_are_drawn_with_their_letter(self):
        # The inside of each o and of the C's loop is drawn as the outer edge
        # goes round it, not on its own after the letter.
        subs = sigpath.simplified(SIG["path"])
        inner = build_header.holes(subs)
        self.assertEqual(sum(map(len, inner.values())), 5)  # two o's, the C, two J's
        for host, hs in inner.items():
            for h in hs:
                _, t0, t1, _ = build_header.alongside(subs[h], subs[host])
                self.assertLess(t0, t1)
                self.assertLessEqual(t1, 1.0)
                self.assertLess(t0, 0.8)  # starts well before its letter ends

    def test_holes_run_the_same_way_as_their_letter(self):
        # A hole run the wrong way round would have to wait at almost every
        # point, so its pace collapses to a straight sweep.
        subs = build_header.with_starts(sigpath.simplified(SIG["path"]))
        for host, hs in build_header.holes(subs).items():
            for h in hs:
                path, t0, t1, keys = build_header.alongside(subs[h], subs[host])
                ts = [build_header.passing(q, subs[host]) for q in path[:-1]]
                ts[0] = t0
                lag, top = 0.0, 0.0
                for x in ts:
                    top = max(top, x)
                    lag += top - x
                self.assertLess(lag / len(ts), 0.05, h)

    def test_reduced_motion_stops_every_outline_piece(self):
        # Hole pieces name their keyframes inline, which outranks the
        # stylesheet; the reduced-motion rule must still win.
        self.assertIn(".outline path,.fill,.wave,.sweep,.head,.cap{animation:none!important}", css(self.svg["dark"]))

    def test_committed_header_matches_the_build(self):
        # CI only runs the tests, so a stale committed SVG would otherwise go
        # unnoticed.
        for theme, svg in self.svg.items():
            self.assertEqual((ROOT / "assets" / f"header-{theme}.svg").read_text(), svg, theme)

    def test_outline_keeps_its_lead_in(self):
        delays = [float(a) for a in re.findall(r"animation-delay:([\d.]+)s", self.svg["dark"])]
        self.assertGreaterEqual(min(delays), 0.8)


if __name__ == "__main__":
    unittest.main()
