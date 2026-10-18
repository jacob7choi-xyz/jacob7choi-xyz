"""Run: python3 -m unittest discover -s scripts"""

import json
import math
import re
import unittest
from pathlib import Path

import sigpath

SIG = json.loads((Path(__file__).parent / "data" / "signature.json").read_text())


def decode(d: str) -> list[list[tuple[float, float]]]:
    """Independent decoder for the M/m/l output of sigpath.to_d."""
    subs, x, y = [], 0.0, 0.0
    for cmd, args in re.findall(r"([MmLl])([^MmLl]*)", d):
        n = [float(v) for v in re.findall(r"-?(?:\d+\.?\d*|\.\d+)", args)]
        pairs = list(zip(n[0::2], n[1::2]))
        if cmd == "M":
            x, y = pairs[0]
            subs.append([(x, y)])
        elif cmd == "m":
            x, y = x + pairs[0][0], y + pairs[0][1]
            subs.append([(x, y)])
        else:  # l
            for dx, dy in pairs:
                x, y = x + dx, y + dy
                subs[-1].append((x, y))
    return subs


class Serialisation(unittest.TestCase):
    def test_roundtrip_within_rounding(self):
        subs = sigpath.simplified(SIG["path"])
        back = decode(sigpath.to_d(subs))
        self.assertEqual(len(back), len(subs))
        for orig, got in zip(subs, back):
            # Zero-length steps are dropped, so compare point sets loosely by
            # checking every decoded point is within rounding of the original.
            dedup = [p for i, p in enumerate(orig) if i == 0 or (round(p[0] * 10), round(p[1] * 10)) != (round(orig[i - 1][0] * 10), round(orig[i - 1][1] * 10))]
            self.assertEqual(len(got), len(dedup))
            for a, b in zip(dedup, got):
                self.assertLess(math.dist(a, b), 0.071)  # half a tenth on each axis

    def test_fmt(self):
        cases = {0: "0", 12: "1.2", -3: "-.3", 3: ".3", 40: "4", -40: "-4", -125: "-12.5"}
        for tenths, want in cases.items():
            self.assertEqual(sigpath.fmt(tenths), want)


class Simplification(unittest.TestCase):
    def test_error_bounded_by_tolerance(self):
        for orig in sigpath.parse(SIG["path"]):
            simp = sigpath.rdp(orig, sigpath.TOLERANCE)
            segs = list(zip(simp, simp[1:]))
            for p in orig:
                d = min(seg_dist(p, a, b) for a, b in segs) if segs else 0
                self.assertLessEqual(d, sigpath.TOLERANCE + 1e-9)

    def test_closed_contours_stay_closed(self):
        before = [sigpath.is_closed(p) for p in sigpath.parse(SIG["path"])]
        after = [sigpath.is_closed(p) for p in sigpath.simplified(SIG["path"])]
        self.assertEqual(before, after)

    def test_actually_smaller(self):
        n0 = sum(map(len, sigpath.parse(SIG["path"])))
        n1 = sum(map(len, sigpath.simplified(SIG["path"])))
        self.assertLess(n1, n0 * 0.5)


def seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ((dx * dx + dy * dy) or 1)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


if __name__ == "__main__":
    unittest.main()
