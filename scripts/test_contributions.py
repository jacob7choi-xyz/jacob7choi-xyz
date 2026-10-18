"""Run: python3 -m unittest discover -s scripts"""

import copy
import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from contributions import LOGIN_RE, DataError, merge, parse_calendar
from render_sequencer import levels, render


def payload(start=dt.date(2025, 10, 12), days=371, count=lambda i: i % 7):
    weeks, week = [], []
    for i in range(days):
        week.append({"date": (start + dt.timedelta(days=i)).isoformat(), "contributionCount": count(i)})
        if len(week) == 7:
            weeks.append({"contributionDays": week})
            week = []
    if week:
        weeks.append({"contributionDays": week})
    return {"data": {"user": {"contributionsCollection": {"contributionCalendar": {"weeks": weeks}}}}}


def first_day(p):
    return p["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"][0]["contributionDays"][0]


class ParseCalendar(unittest.TestCase):
    def test_valid(self):
        days = parse_calendar(payload(), "a")
        self.assertEqual(len(days), 371)

    def test_rejects_graphql_errors(self):
        p = payload()
        p["errors"] = [{"message": "nope"}]
        with self.assertRaises(DataError):
            parse_calendar(p, "a")

    def test_rejects_missing_user(self):
        with self.assertRaises(DataError):
            parse_calendar({"data": {"user": None}}, "a")

    def test_rejects_bad_values(self):
        for bad in (-1, 1.5, "3", True, None, 10**9):
            p = copy.deepcopy(payload())
            first_day(p)["contributionCount"] = bad
            with self.subTest(bad=bad), self.assertRaises(DataError):
                parse_calendar(p, "a")

    def test_rejects_bad_dates(self):
        for bad in ("2025-13-01", "2025-1-1", "<script>", None):
            p = copy.deepcopy(payload())
            first_day(p)["date"] = bad
            with self.subTest(bad=bad), self.assertRaises((DataError, ValueError)):
                parse_calendar(p, "a")

    def test_rejects_duplicate_dates(self):
        p = payload()
        weeks = p["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        weeks[1]["contributionDays"][0]["date"] = weeks[0]["contributionDays"][0]["date"]
        with self.assertRaises(DataError):
            parse_calendar(p, "a")

    def test_rejects_truncated_calendar(self):
        with self.assertRaises(DataError):
            parse_calendar(payload(days=30), "a")


class Logins(unittest.TestCase):
    def test_login_pattern(self):
        for ok in ("jacob7choi-xyz", "jacobjax7choi", "a"):
            self.assertTrue(LOGIN_RE.fullmatch(ok), ok)
        for bad in ("-a", "a-", "a--b", "a b", "a/../b", "x" * 40, ""):
            self.assertFalse(LOGIN_RE.fullmatch(bad), bad)


class MergeAndRender(unittest.TestCase):
    def test_merge_sums_and_fills_gaps(self):
        a = {dt.date(2026, 1, 1): 2, dt.date(2026, 1, 3): 1}
        b = {dt.date(2026, 1, 1): 3}
        self.assertEqual(
            merge([a, b]),
            [(dt.date(2026, 1, 1), 5), (dt.date(2026, 1, 2), 0), (dt.date(2026, 1, 3), 1)],
        )

    def test_render_is_wellformed_static_svg(self):
        days = merge([parse_calendar(payload(), "a"), parse_calendar(payload(count=lambda i: 0), "b")])
        for theme in ("dark", "light"):
            svg = render(days, theme)
            root = ET.fromstring(svg)  # raises if not well-formed XML
            self.assertTrue(root.tag.endswith("svg"))
            lowered = svg.lower()
            for forbidden in ("<script", "javascript:", "onload", "<foreignobject", "http://", "https://"):
                # The only URL allowed is the SVG namespace declaration.
                hits = lowered.replace('xmlns="http://www.w3.org/2000/svg"', "").count(forbidden)
                self.assertEqual(hits, 0, forbidden)

    def test_resting_frame_needs_no_animation(self):
        # The finished picture must come from geometry alone. Transforms may
        # appear only inside @keyframes, so a renderer that skips CSS animation
        # or reduced motion still shows the full calendar.
        svg = render(merge([parse_calendar(payload(), "a")]), "dark")
        css = svg.split("<style>")[1].split("</style>")[0]
        resting = "".join(line for line in css.splitlines() if not line.startswith("@keyframes"))
        self.assertNotIn("transform:", resting)

    def test_grid_has_one_cell_per_day(self):
        days = merge([parse_calendar(payload(), "a")])
        root = ET.fromstring(render(days, "dark"))
        ns = "{http://www.w3.org/2000/svg}"
        # Day cells are the 14px rects without a class. Legend swatches are
        # 10px, and the flash/ring overlays carry class="f" or class="r".
        cells = [r for r in root.iter(f"{ns}rect") if r.get("width") == "14" and not r.get("class")]
        self.assertEqual(len(cells), len(days))

    def test_labels_cover_both_ends_and_every_weekday(self):
        days = merge([parse_calendar(payload(), "a")])
        root = ET.fromstring(render(days, "dark"))
        texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
        months = [t for t in texts if t in {d.strftime("%b") for d, _ in days}]
        self.assertEqual(months[0], days[0][0].strftime("%b"))
        self.assertEqual(months[-1], days[-1][0].strftime("%b"))
        for name in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Less", "More"):
            self.assertIn(name, texts)

    def test_partial_first_month_keeps_its_label(self):
        # The window CI actually received on 2026-10-18 (UTC): 365 days from
        # Sun 2025-10-19, so October owns only two columns before November.
        days = merge([parse_calendar(payload(start=dt.date(2025, 10, 19), days=365), "a")])
        root = ET.fromstring(render(days, "dark"))
        texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
        self.assertEqual(texts.count("Oct"), 2)

    def test_headline_is_the_merged_total(self):
        a = parse_calendar(payload(count=lambda i: 2), "a")
        b = parse_calendar(payload(count=lambda i: 1), "b")
        days = merge([a, b])
        total = sum(c for _, c in days)
        self.assertEqual(total, 3 * 371)
        self.assertIn(f"{total:,} contributions in the last year", render(days, "dark"))

    def test_light_mode_outlines_every_square(self):
        days = merge([parse_calendar(payload(), "a")])
        light = render(days, "light")
        self.assertIn('<g stroke="#1f2328" stroke-width="1">', light)
        self.assertNotIn('stroke="#1f2328" stroke-width="1"', render(days, "dark"))
        # Faint cells must not fade their outline along with their fill.
        self.assertNotIn(' opacity="0.32"', light)

    def test_levels_bucket_like_github(self):
        self.assertEqual(levels([0, 0, 0]), [0, 0, 0])
        lv = levels([0, 1, 2, 3, 4, 5, 6, 7, 8, 100])
        self.assertEqual(lv[0], 0)
        self.assertEqual(lv[-1], 4)
        self.assertTrue(all(1 <= x <= 4 for x in lv[1:]))
        self.assertEqual(lv[1:], sorted(lv[1:]))

    def test_render_handles_all_zero_year(self):
        days = merge([parse_calendar(payload(count=lambda i: 0), "a")])
        ET.fromstring(render(days, "dark"))

    def test_render_is_deterministic(self):
        days = merge([parse_calendar(payload(), "a")])
        self.assertEqual(render(days, "dark"), render(days, "dark"))


if __name__ == "__main__":
    unittest.main()
