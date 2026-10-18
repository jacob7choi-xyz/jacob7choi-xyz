"""Run: python3 -m unittest discover -s scripts"""

import json
import math
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import build_header

DATA = Path(__file__).parent / "data"
SIG = json.loads((DATA / "signature.json").read_text())
PEN = json.loads((DATA / "signature_strokes.json").read_text())


def css(svg: str) -> str:
    return svg.split("<style>")[1].split("</style>")[0]


class Header(unittest.TestCase):
    def setUp(self):
        self.svg = {t: build_header.render(t, SIG, PEN["strokes"]) for t in ("dark", "light")}

    def test_wellformed_and_static_at_rest(self):
        for svg in self.svg.values():
            ET.fromstring(svg)
            resting = [l for l in css(svg).splitlines() if not l.startswith("@keyframes")]
            self.assertFalse([l for l in resting if "transform:" in l])

    def test_waiting_pen_strokes_paint_nothing(self):
        # Regression: WebKit paints a round cap even for a zero-length dash, so
        # a waiting stroke must not have ANY dash touching [0, pathLength=1].
        c = css(self.svg["dark"])
        d, g = map(float, re.search(r"\.pen path\{stroke-dasharray:([\d.]+) ([\d.]+)", c).groups())
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
        fill = float(re.search(r"\.ink\{animation:ink [\d.]+s \S+ ([\d.]+)s", c).group(1))
        self.assertLess(max(ends), fill)

    def test_pen_starts_after_github_load_jank(self):
        delays = [float(a) for a in re.findall(r"animation-delay:([\d.]+)s", self.svg["dark"])]
        self.assertGreaterEqual(min(delays), 0.8)


if __name__ == "__main__":
    unittest.main()
