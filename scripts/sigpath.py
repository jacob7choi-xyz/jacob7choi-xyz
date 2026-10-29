"""Shared geometry for the signature: parse, simplify, split, serialise.

The source path (data/signature.json) is the website's signature, flattened to
~4,000 points. The header renders it at about 0.4 CSS px per unit, so most of
those points sit closer together than a pixel and only cost parse and raster
time. simplified() drops them with Ramer-Douglas-Peucker at TOLERANCE units,
which bounds the shape error at 0.32 device px even on a 2x display.

build_header.py draws both the outline and the fill from simplified(), so
the two steps always share exactly the same geometry.
Standard library only.
"""

import math
import re

TOLERANCE = 0.4  # signature units; ~0.16 CSS px at the header's render size

Point = tuple[float, float]


def parse(path: str) -> list[list[Point]]:
    """Split an M/L/C path into polylines, sampling cubics into 8 segments.

    Only absolute M, L and C with plain decimals are understood. Anything else
    (other commands, exponents) raises rather than being silently skipped."""
    if not re.fullmatch(r"[MLC0-9.,\s-]*", path):
        raise ValueError("unsupported path syntax")
    out = []
    for sub in re.findall(r"M[^M]+", path):
        pts: list[Point] = []
        cur: Point = (0.0, 0.0)
        for cmd, args in re.findall(r"([MLC])([^MLC]*)", sub):
            n = [float(x) for x in re.findall(r"-?(?:\d+\.?\d*|\.\d+)", args)]
            if cmd in "ML":
                for i in range(0, len(n), 2):
                    cur = (n[i], n[i + 1])
                    pts.append(cur)
            else:
                for i in range(0, len(n), 6):
                    c = (cur, n[i : i + 2], n[i + 2 : i + 4], n[i + 4 : i + 6])
                    for k in range(1, 9):
                        cur = bezier(c, k / 8)
                        pts.append(cur)
        out.append(pts)
    return out


def bezier(c, t: float) -> Point:
    """Point at t on the cubic Bezier with control points c = (p0, p1, p2, p3)."""
    p0, p1, p2, p3 = c
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def rdp(pts: list[Point], tol: float) -> list[Point]:
    """Ramer-Douglas-Peucker, iterative so long contours cannot hit the
    recursion limit."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        best, best_i = -1.0, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dx * (ay - y) - dy * (ax - x)) / length if length else math.hypot(x - ax, y - ay)
            if d > best:
                best, best_i = d, i
        if best > tol:
            keep[best_i] = True
            stack += [(a, best_i), (best_i, b)]
    return [p for p, k in zip(pts, keep) if k]


def is_closed(pts: list[Point]) -> bool:
    return math.dist(pts[0], pts[-1]) < 1


def simplified(path: str, tol: float = TOLERANCE) -> list[list[Point]]:
    return [rdp(p, tol) for p in parse(path)]


def to_d(subpaths: list[list[Point]]) -> str:
    """Serialise with relative moves. Deltas are taken between ROUNDED absolute
    coordinates, so rounding never accumulates along a contour."""
    parts = []
    px, py = 0, 0
    for pts in subpaths:
        r = [(round(x * 10), round(y * 10)) for x, y in pts]  # tenths of a unit
        x0, y0 = r[0]
        seg = [f"m{fmt(x0 - px)} {fmt(y0 - py)}" if parts else f"M{fmt(x0)} {fmt(y0)}"]
        deltas = [(x - prev_x, y - prev_y) for (prev_x, prev_y), (x, y) in zip(r, r[1:])]
        deltas = [d for d in deltas if d != (0, 0)]
        if deltas:
            seg.append("l" + " ".join(f"{fmt(dx)} {fmt(dy)}" for dx, dy in deltas))
        parts.append("".join(seg))
        # `m` after a subpath is relative to that subpath's last drawn point.
        px, py = (x0 + sum(d[0] for d in deltas), y0 + sum(d[1] for d in deltas))
    return "".join(parts)


def fmt(tenths: int) -> str:
    """12 -> '1.2', -3 -> '-.3', 40 -> '4'."""
    s = f"{tenths / 10:.1f}".rstrip("0").rstrip(".")
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s or "0"
