"""canal_class.py: what kind of channel each mapped canal segment is.

ADDED in round 3 (ARCHITECTURE.md section 4.2). Nothing here changes the sealant plan, the
ranking or what the website shows: the functions sit beside the old ones.

The USGS canal file calls every line "Canal/Ditch". OpenStreetMap (a public, volunteer-made
map, downloaded by app/osm_canals.py) knows more: whether a line is a canal, a ditch or a drain,
whether a stretch is tagged as running underground, and more names. This module lays each USGS
segment over the OpenStreetMap lines and reads those three things off.

The three helpers at the top (dense, point_grid, line_near) were moved here from
app/build_site.py, which now imports them, so the pipeline and the website match lines the
same way. This file imports nothing heavy on purpose: the site build runs without the pipeline's
libraries.

WHAT "PIPED" MEANS HERE: only that OpenStreetMap tags the line as a tunnel. Many such tags are
short road culverts. So it is carried as a SHARE of the segment's length (piped_share) and is
never a statement that a canal is lined.
"""
from collections import Counter

CELL = 0.0005        # grid cell in degrees, about 50 metres
STEP = 0.0004        # put a point on a line at least every ~40 metres, so straight canals still match
OSM_KINDS = ["canal", "ditch", "drain"]
MATCHED_SHARE = 0.5  # a segment takes OpenStreetMap's label when OpenStreetMap follows at least half of it


def dense(line):
    """The points of a line with extra points added along long straight stretches."""
    out = [line[0]]
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        n = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / STEP))
        out += [(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n) for k in range(1, n + 1)]
    return out


def point_grid(lines):
    """A lookup from grid cell to the number of the first line that passes through it."""
    grid = {}
    for i, line in enumerate(lines):
        for x, y in dense(line):
            grid.setdefault((round(x / CELL), round(y / CELL)), i)
    return grid


def line_near(grid, x, y):
    """The number of a line within about 50 to 75 metres of the point, or None."""
    gx, gy = round(x / CELL), round(y / CELL)
    for dx in (0, -1, 1):
        for dy in (0, -1, 1):
            hit = grid.get((gx + dx, gy + dy))
            if hit is not None:
                return hit
    return None


def match_line(line, grid, ways):
    """Lay one USGS segment over the OpenStreetMap lines.

    line : the segment as [[lon, lat], ...]
    grid : point_grid of the OpenStreetMap lines
    ways : the OpenStreetMap lines themselves (each with kind, name, piped)

    Returns a dict:
      points       how many points the segment was checked at (one every ~40 metres)
      hits         how many of them lie on an OpenStreetMap line
      kind         "canal", "ditch" or "drain": the commonest kind among the hits, or None when
                   OpenStreetMap follows less than half of the segment
      piped_hits   how many points lie on a line tagged as running underground
      piped_share  piped_hits / points: the share of the segment's length that is tagged so
      name, name_hits   the commonest OpenStreetMap name among the hits ("" if none) and its count
    """
    points = dense(line)
    hits = [ways[i] for i in (line_near(grid, x, y) for x, y in points) if i is not None]
    matched = len(hits) >= MATCHED_SHARE * len(points)
    names = Counter(w["name"] for w in hits if w["name"])
    name, name_hits = names.most_common(1)[0] if names else ("", 0)
    piped_hits = sum(w["piped"] for w in hits)
    return {"points": len(points), "hits": len(hits),
            "kind": Counter(w["kind"] for w in hits).most_common(1)[0][0] if matched else None,
            "piped_hits": piped_hits, "piped_share": piped_hits / len(points),
            "name": name, "name_hits": name_hits}


def site_line(points, digits=4):
    """A line rounded the way the website draws it (4 decimals, repeated points dropped), so a
    segment is matched here exactly as app/build_site.py matches it."""
    out = []
    for lon, lat in (p[:2] for p in points):
        point = [round(lon, digits), round(lat, digits)]
        if not out or out[-1] != point:
            out.append(point)
    return out


def match_segments(lines, ways):
    """match_line for every segment. lines: one [[lon, lat], ...] per segment. Returns a list of dicts."""
    grid = point_grid([w["line"] for w in ways])
    return [match_line(site_line(line), grid, ways) for line in lines]
