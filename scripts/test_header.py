"""Run: python3 -m unittest discover -s scripts"""

import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import build_header

import sigpath

SIG = json.loads((Path(__file__).parent / "data" / "signature.json").read_text())


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

    def test_outline_keeps_its_lead_in(self):
        delays = [float(a) for a in re.findall(r"animation-delay:([\d.]+)s", self.svg["dark"])]
        self.assertGreaterEqual(min(delays), 0.8)


if __name__ == "__main__":
    unittest.main()
