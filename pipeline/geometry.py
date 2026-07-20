"""State boundary geometry for the site's maps. Census cartographic boundary
shapefiles (public domain) -> SVG path data.

- data/geometry/national.yaml — all states projected Albers-USA style
  (conic equal-area with Alaska/Hawaii/Puerto Rico insets) for the clickable
  US map.
- data/geometry/<st>.yaml — each state's outline in a local equirectangular
  projection plus the transform constants the site needs to plot city
  coordinates over it: x = (lng - minlng) * kx * s, y = (maxlat - lat) * s.

Shapefile + DBF parsed with struct (stdlib-only, formats are stable).
20m generalization for the national map (small paths), 5m for state pages.

Usage: python3 -m pipeline.geometry [--year 2024] [--force]
"""
import math
import struct
import sys
import zipfile
from pathlib import Path

from .util import DATA, SOURCES, dump_yaml, fetch

URL = ("https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_us_state_{res}.zip")

SKIP = {"as", "gu", "mp", "vi"}  # island areas without dataset coverage


def read_dbf(data: bytes) -> list[dict]:
    n_records = struct.unpack_from("<I", data, 4)[0]
    header_size, record_size = struct.unpack_from("<HH", data, 8)
    fields, off = [], 32
    while data[off] != 0x0D:
        name = data[off:off + 11].split(b"\0")[0].decode("ascii")
        length = data[off + 16]
        fields.append((name, length))
        off += 32
    rows = []
    for i in range(n_records):
        base = header_size + i * record_size + 1  # +1 deletion flag
        row, pos = {}, base
        for name, length in fields:
            row[name] = data[pos:pos + length].decode("latin-1").strip()
            pos += length
        rows.append(row)
    return rows


def read_shp(data: bytes) -> list[list[list[tuple[float, float]]]]:
    """Return, per record, a list of rings (each a list of (lng, lat))."""
    shapes, off = [], 100
    while off < len(data):
        content_len = struct.unpack_from(">i", data, off + 4)[0] * 2
        shape_type = struct.unpack_from("<i", data, off + 8)[0]
        if shape_type != 5:
            shapes.append([])
            off += 8 + content_len
            continue
        p = off + 8 + 4 + 32  # past type + bbox
        num_parts, num_points = struct.unpack_from("<ii", data, p)
        p += 8
        parts = list(struct.unpack_from(f"<{num_parts}i", data, p))
        p += 4 * num_parts
        pts = struct.unpack_from(f"<{num_points * 2}d", data, p)
        points = list(zip(pts[0::2], pts[1::2]))
        rings = [points[a:b] for a, b in zip(parts, parts[1:] + [num_points])]
        shapes.append(rings)
        off += 8 + content_len
    return shapes


def load_states(year: int, res: str, force: bool) -> dict[str, list]:
    cache = SOURCES / "census" / f"cb_{year}_us_state_{res}.zip"
    fetch(URL.format(y=year, res=res), cache, force=force)
    with zipfile.ZipFile(cache) as z:
        shp = next(n for n in z.namelist() if n.endswith(".shp"))
        dbf = next(n for n in z.namelist() if n.endswith(".dbf"))
        shapes = read_shp(z.read(shp))
        rows = read_dbf(z.read(dbf))
    out = {}
    for row, rings in zip(rows, shapes):
        st = row["STUSPS"].lower()
        if st and rings and st not in SKIP:
            out[st] = rings
    return out


def albers(lng, lat, lng0, phi1, phi2, phi0):
    phi1, phi2, phi0, lat, dl = map(math.radians, (phi1, phi2, phi0, lat, lng - lng0))
    n = (math.sin(phi1) + math.sin(phi2)) / 2
    C = math.cos(phi1) ** 2 + 2 * n * math.sin(phi1)
    rho = math.sqrt(max(C - 2 * n * math.sin(lat), 0)) / n
    rho0 = math.sqrt(max(C - 2 * n * math.sin(phi0), 0)) / n
    theta = n * dl
    return rho * math.sin(theta), rho0 - rho * math.cos(theta)


def project_region(rings_by_state, params):
    projected = {
        st: [[albers(lng, lat, *params) for lng, lat in ring] for ring in rings]
        for st, rings in rings_by_state.items()
    }
    xs = [x for rings in projected.values() for ring in rings for x, _ in ring]
    ys = [y for rings in projected.values() for ring in rings for _, y in ring]
    return projected, (min(xs), min(ys), max(xs), max(ys))


def fit(projected, bbox, x0, y0, w):
    """Scale projected coords to width w at (x0, y0), flipping y for SVG."""
    minx, miny, maxx, maxy = bbox
    s = w / (maxx - minx)
    out = {st: [[(x0 + (x - minx) * s, y0 + (maxy - y) * s) for x, y in ring]
                for ring in rings] for st, rings in projected.items()}
    return out, (maxy - miny) * s


def to_path(rings, nd=1):
    parts = []
    for ring in rings:
        if len(ring) < 4:
            continue
        coords = [f"{x:.{nd}f},{y:.{nd}f}" for x, y in ring]
        parts.append("M" + "L".join(coords) + "Z")
    return "".join(parts)


def build_national(year, force):
    states = load_states(year, "20m", force)
    conus = {st: r for st, r in states.items() if st not in ("ak", "hi", "pr")}
    proj, bbox = project_region(conus, (-96, 29.5, 45.5, 37.5))
    placed, h = fit(proj, bbox, 0, 0, 900)

    for st, params, x0, y0, w in (
        ("ak", (-154, 55, 65, 60), 0, h - 180, 250),
        ("hi", (-157, 8, 18, 13), 280, h - 70, 110),
        ("pr", (-66.4, 17.5, 18.5, 18), 750, h + 10, 80),
    ):
        if st not in states:
            continue
        rings = states[st]
        if st == "ak":  # Aleutians cross the antimeridian
            rings = [[(lng - 360 if lng > 0 else lng, lat) for lng, lat in r]
                     for r in rings]
        p, b = project_region({st: rings}, params)
        placed_st, _ = fit(p, b, x0, y0, w)
        placed[st] = placed_st[st]

    height = int(h + 60)
    dump_yaml(
        {"width": 900, "height": height,
         "states": {st: to_path(rings) for st, rings in sorted(placed.items())}},
        DATA / "geometry" / "national.yaml")
    print(f"national map: {len(placed)} states -> data/geometry/national.yaml")


def build_state_pages(year, force):
    states = load_states(year, "5m", force)
    for st, rings in sorted(states.items()):
        if st == "ak":
            rings = [[(lng - 360 if lng > 0 else lng, lat) for lng, lat in r]
                     for r in rings]
        lngs = [lng for r in rings for lng, _ in r]
        lats = [lat for r in rings for _, lat in r]
        minlng, maxlng = min(lngs), max(lngs)
        minlat, maxlat = min(lats), max(lats)
        kx = math.cos(math.radians((minlat + maxlat) / 2))
        s = 400 / ((maxlng - minlng) * kx)
        placed = [[((lng - minlng) * kx * s, (maxlat - lat) * s)
                   for lng, lat in ring] for ring in rings]
        dump_yaml(
            {"state": st, "w": 400, "h": round((maxlat - minlat) * s, 1),
             "minlng": round(minlng, 6), "maxlat": round(maxlat, 6),
             "kx": round(kx, 6), "s": round(s, 6),
             "path": to_path(placed)},
            DATA / "geometry" / f"{st}.yaml")
    print(f"state outlines: {len(states)} -> data/geometry/<st>.yaml")


def main(argv):
    year = 2024
    force = "--force" in argv
    if "--year" in argv:
        year = int(argv[argv.index("--year") + 1])
    build_national(year, force)
    build_state_pages(year, force)


if __name__ == "__main__":
    main(sys.argv[1:])
