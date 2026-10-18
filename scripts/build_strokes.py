# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "numpy==2.2.6",
#   "pillow==11.2.1",
#   "scikit-image==0.25.2",
# ]
# ///
"""Derive pen strokes for the signature, so the header can write it by hand.

The signature in data/signature.json is a set of letter OUTLINES plus a few
open strokes (cursive connectors and the underline flourish). A pen does not
draw outlines; it draws along the middle of each letter. This script finds that
middle line:

  1. rasterise the filled letterforms at high resolution,
  2. thin them to a one-pixel skeleton,
  3. trace the skeleton into polylines and order them the way a hand would
     write: letter by letter, left to right, with the connectors where they
     fall and the flourish last,
  4. record, per stroke, how wide the pen must be to cover the letter there.

The header then animates a wide stroke along each centerline inside a mask, so
the filled letters appear exactly where the pen has been.

This is an OFFLINE build step with pinned third-party dependencies, run by hand
when the signature changes. CI never runs it; the workflow stays standard
library only. Output: scripts/data/signature_strokes.json

Usage: uv run --python 3.13 scripts/build_strokes.py
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from skimage.morphology import binary_dilation, disk, medial_axis

import sigpath

ROOT = Path(__file__).resolve().parent.parent
SCALE = 4  # raster pixels per signature unit
# The header outlines each letter with a 3-unit stroke, which reaches 1.5 units
# past the letter's edge. Pens must cover that too, or the outline is clipped.
OUTLINE_REACH = 1.5
PAD = 8  # signature units of padding around the box


def signed_area(pts) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2


def neighbours(sk, y, x):
    h, w = sk.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if (dy or dx) and 0 <= y + dy < h and 0 <= x + dx < w and sk[y + dy, x + dx]:
                yield y + dy, x + dx


def trace(sk) -> list[list[tuple[int, int]]]:
    """Split a skeleton into polylines that run between endpoints/junctions,
    then join them through junctions by choosing the straightest continuation,
    which is roughly how a pen carries through a crossing."""
    pix = {tuple(p) for p in np.argwhere(sk)}
    deg = {p: sum(1 for _ in neighbours(sk, *p)) for p in pix}
    nodes = {p for p, d in deg.items() if d != 2}
    seen_edges, edges = set(), []

    def walk(start, nxt):
        line = [start, nxt]
        prev, cur = start, nxt
        while cur not in nodes:
            step = [n for n in neighbours(sk, *cur) if n != prev and n not in line[-3:]]
            if not step:
                break
            prev, cur = cur, step[0]
            line.append(cur)
        return line

    for n in nodes:
        for nb in neighbours(sk, *n):
            key = frozenset((n, nb))
            if key in seen_edges:
                continue
            line = walk(n, nb)
            for a, b in zip(line, line[1:]):
                seen_edges.add(frozenset((a, b)))
            if len(line) > 2:
                edges.append(line)
    # Pure loops (an 'o' with no endpoint) have no nodes; start them anywhere.
    covered = {p for e in edges for p in e}
    for p in sorted(pix - covered):
        if p in covered:
            continue
        nb = next(neighbours(sk, *p), None)
        if nb is None:
            continue
        line = walk(p, nb)
        covered.update(line)
        if len(line) > 2:
            edges.append(line)
    return edges


def chain(edges):
    """Greedily join edges end to end through shared junctions, preferring the
    smallest change of direction."""
    edges = [list(e) for e in edges if len(e) > 6]
    strokes = []
    while edges:
        # Start from the leftmost free end: writing goes left to right.
        edges.sort(key=lambda e: min(e[0][1], e[-1][1]))
        cur = edges.pop(0)
        if cur[-1][1] < cur[0][1]:
            cur.reverse()
        while True:
            end, before = cur[-1], cur[max(0, len(cur) - 8)]
            heading = math.atan2(end[0] - before[0], end[1] - before[1])
            best, best_turn = None, 1.2  # radians; sharper turns lift the pen
            for i, e in enumerate(edges):
                for flip in (False, True):
                    cand = e[::-1] if flip else e
                    if math.dist(cand[0], end) > 3:
                        continue
                    ahead = cand[min(len(cand) - 1, 8)]
                    h2 = math.atan2(ahead[0] - cand[0][0], ahead[1] - cand[0][1])
                    turn = abs((h2 - heading + math.pi) % (2 * math.pi) - math.pi)
                    if turn < best_turn:
                        best, best_turn = (i, cand), turn
            if best is None:
                break
            edges.pop(best[0])
            cur.extend(best[1][1:])
        strokes.append(cur)
    return strokes


def polyline_len(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def main() -> None:
    sig = json.loads((ROOT / "scripts" / "data" / "signature.json").read_text())
    box = sig["box"]
    ox, oy = box["x"] - PAD, box["y"] - PAD
    W = int((box["w"] + 2 * PAD) * SCALE)
    H = int((box["h"] + 2 * PAD) * SCALE)

    # Fit the pens to exactly the simplified geometry the header draws.
    subs = sigpath.simplified(sig["path"])
    contours = [s for s in subs if sigpath.is_closed(s)]
    opens = [s for s in subs if not sigpath.is_closed(s)]

    # Outer contours share an orientation; holes (the inside of an 'o') run the
    # other way. Union the outers, then cut the holes.
    areas = [signed_area(c) for c in contours]
    outer_sign = 1 if sum(a for a in areas if a > 0) >= -sum(a for a in areas if a < 0) else -1
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    to_px = lambda p: ((p[0] - ox) * SCALE, (p[1] - oy) * SCALE)
    for c, a in zip(contours, areas):
        if a * outer_sign > 0:
            draw.polygon([to_px(p) for p in c], fill=1)
    for c, a in zip(contours, areas):
        if a * outer_sign < 0:
            draw.polygon([to_px(p) for p in c], fill=0)
    ink = np.array(img, dtype=bool)

    # medial_axis breaks ties randomly unless seeded; seed it so the build is
    # reproducible and a diff in the output always means a real change.
    skel, dist = medial_axis(ink, return_distance=True, rng=0)
    strokes = []
    for line in chain(trace(skel)):
        radius = max(dist[p] for p in line) / SCALE
        pts = [(x / SCALE + ox, y / SCALE + oy) for y, x in line]
        pts = sigpath.rdp(pts, sigpath.TOLERANCE)
        if len(pts) < 2:
            continue
        strokes.append({"pts": pts, "width": round(2 * radius + 2 * OUTLINE_REACH + 2, 2), "kind": "letter"})
    for o in opens:
        # Connectors and the flourish are already centrelines.
        kind = "flourish" if max(p[0] for p in o) - min(p[0] for p in o) > box["w"] * 0.5 else "connector"
        strokes.append({"pts": o, "width": 6.0, "kind": kind})

    # Writing order: by where each stroke starts, flourish always last.
    strokes.sort(key=lambda s: (s["kind"] == "flourish", min(p[0] for p in s["pts"][:1])))
    def raster(st) -> np.ndarray:
        img = Image.new("1", (W, H), 0)
        dr = ImageDraw.Draw(img)
        px = [to_px(p) for p in st["pts"]]
        w = max(1, int(st["width"] * SCALE))
        dr.line(px, fill=1, width=w, joint="curve")
        r = w / 2
        for x, y in px:
            dr.ellipse([x - r, y - r, x + r, y + r], fill=1)
        return np.array(img, dtype=bool)

    # Coverage: every pixel of the letters AND their outline must be reached by
    # some pen stroke, or part of the signature would stay hidden after the
    # animation finishes.
    target = binary_dilation(ink, disk(int(OUTLINE_REACH * SCALE)))
    count = np.zeros((H, W), dtype=np.uint16)
    for st in strokes:
        count += raster(st)

    # Prune: every <path> in the mask is another element the browser animates
    # and re-rasterises each frame. Drop letter strokes, shortest first, whose
    # every target pixel is also covered by some other stroke. Coverage stays
    # exactly what it was.
    before = len(strokes)
    for st in sorted([s for s in strokes if s["kind"] == "letter"], key=lambda s: polyline_len(s["pts"])):
        m = raster(st)
        if not (target & m & (count < 2)).any():
            count -= m
            strokes.remove(st)
    missed = int((target & (count == 0)).sum())
    frac = 1 - missed / max(1, int(target.sum()))

    for st in strokes:
        st["length"] = round(polyline_len(st["pts"]), 2)
        st["d"] = sigpath.to_d([st.pop("pts")])

    out = ROOT / "scripts" / "data" / "signature_strokes.json"
    out.write_text(json.dumps({
        "source_path_sha256": sig["path_sha256"],
        "geometry_sha256": sigpath.geometry_hash(subs),
        "tolerance": sigpath.TOLERANCE,
        "generator": "scripts/build_strokes.py",
        "coverage": round(frac, 5),
        "strokes": strokes,
    }))
    print(f"{len(strokes)} strokes (pruned from {before}), "
          f"coverage {frac:.4%} ({missed} px missed), wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
