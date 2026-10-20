"""Pure-Python logic for the AHN COPC tiles (no QGIS imports, unit-testable).

URL patterns are taken from the official AHN 'bladwijzer'
(https://basisdata.nl/hwh-ahn/AUX/bladwijzer/index.html), verified October 2026:

* AHN2-AHN5, re-derived 1x1 km sheets (zero-padded coordinates):
    {base}/AHN{n}_KM/01_LAZ/AHN{n}_C_{xxxxxx}_{yyyyyy}.COPC.LAZ
* AHN6, 1x1 km sheets, acquisition year in the name, coordinates NOT padded:
    {base}/AHN6/01_LAZ/AHN6_{year}_C_{x}_{y}.COPC.LAZ

Sheet names are the lower-left corner of a 1 km cell in RD New (EPSG:28992).
"""

import math

BASE_URL = "https://fsn1.your-objectstorage.com/hwh-ahn"
CELL = 1000

# Rough RD bounding box of the Netherlands (European part), used to clamp extents.
NL_XMIN, NL_YMIN, NL_XMAX, NL_YMAX = 0, 300000, 300000, 625000

AHN6_YEARS = (2025, 2026, 2027)
NEWEST = "newest"  # pseudo-version key; label "Newest available"

VERSIONS = {
    "AHN2": {"period": "2007-2012", "license": "CC0 1.0"},
    "AHN3": {"period": "2014-2019", "license": "CC0 1.0"},
    "AHN4": {"period": "2020-2022", "license": "CC0 1.0"},
    "AHN5": {"period": "2023-2024", "license": "CC BY 4.0"},
    "AHN6": {"period": "2025-2027", "license": "CC BY 4.0"},
}

# Order used for "newest available": try these in turn per cell.
NEWEST_ORDER = ("AHN6", "AHN5")

# AHN classification codes (ASPRS based, plus AHN specific 26 = kunstwerk).
CLASSES = {
    0: ("Never classified", "#bdbdbd"),
    1: ("Other (incl. vegetation)", "#4caf50"),
    2: ("Ground", "#a1662f"),
    6: ("Building", "#e53935"),
    9: ("Water", "#1e88e5"),
    14: ("High voltage", "#fdd835"),
    26: ("Civil structure", "#8e24aa"),
}

# Presets for the class filter: key -> (English label, list of classes or None = all).
CLASS_FILTERS = {
    "all": ("All points", None),
    "ground": ("Ground only (2)", [2]),
    "ground_water": ("Ground + water (2, 9)", [2, 9]),
    "buildings": ("Buildings (6)", [6]),
    "structures": ("Civil structures (26)", [26]),
    "no_other": ("Without vegetation/other (no 1)", [0, 2, 6, 9, 14, 26]),
}


def tile_name(x, y, pad=True):
    """Sheet name for the cell with lower-left corner (x, y)."""
    if pad:
        return "%06d_%06d" % (x, y)
    return "%d_%d" % (x, y)


def cells_for_extent(xmin, ymin, xmax, ymax, clamp=True):
    """Lower-left corners of all 1 km cells intersecting the extent (RD metres).

    An extent edge lying exactly on a cell boundary does not pull in the
    neighbouring cell.
    """
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if ymin > ymax:
        ymin, ymax = ymax, ymin
    if clamp:
        xmin, ymin = max(xmin, NL_XMIN), max(ymin, NL_YMIN)
        xmax, ymax = min(xmax, NL_XMAX), min(ymax, NL_YMAX)
        if xmin > xmax or ymin > ymax:
            return []
    x0 = int(math.floor(xmin / CELL)) * CELL
    y0 = int(math.floor(ymin / CELL)) * CELL
    x1 = int(math.ceil(xmax / CELL)) * CELL
    y1 = int(math.ceil(ymax / CELL)) * CELL
    if x1 == x0:
        x1 += CELL
    if y1 == y0:
        y1 += CELL
    return [(x, y) for y in range(y0, y1, CELL) for x in range(x0, x1, CELL)]


def count_cells(xmin, ymin, xmax, ymax):
    """Number of cells without building the list (cheap guard for huge extents)."""
    cells_x = math.ceil(max(xmax, xmin + 1) / CELL) - math.floor(xmin / CELL)
    cells_y = math.ceil(max(ymax, ymin + 1) / CELL) - math.floor(ymin / CELL)
    return int(cells_x * cells_y)


def candidate_urls(version, x, y, base=BASE_URL):
    """Possible COPC URLs for one cell, as a list of (version, url).

    For AHN6 the acquisition year is unknown beforehand, so every year is a
    candidate; the availability check decides which one exists. For the
    'newest' pseudo-version the candidates of AHN6 and AHN5 are combined.
    """
    base = base.rstrip("/")
    if version == NEWEST:
        out = []
        for v in NEWEST_ORDER:
            out.extend(candidate_urls(v, x, y, base))
        return out
    if version == "AHN6":
        name = tile_name(x, y, pad=False)
        return [
            ("AHN6", "%s/AHN6/01_LAZ/AHN6_%d_C_%s.COPC.LAZ" % (base, year, name))
            for year in AHN6_YEARS
        ]
    if version in ("AHN2", "AHN3", "AHN4", "AHN5"):
        name = tile_name(x, y, pad=True)
        return [(version, "%s/%s_KM/01_LAZ/%s_C_%s.COPC.LAZ" % (base, version, version, name))]
    raise ValueError("Onbekende AHN-versie: %s" % version)


def pick_best(version, available):
    """Choose the URL to load for one cell.

    available: list of (version, url) that exist.
    Preference: requested version (newest year first); for NEWEST, the first
    version in NEWEST_ORDER that has a hit.
    """
    if not available:
        return None
    order = NEWEST_ORDER if version == NEWEST else (version,)
    for v in order:
        hits = sorted(u for vv, u in available if vv == v)
        if hits:
            # year is part of the AHN6 file name, so the last sorted is newest
            return v, hits[-1]
    return None


def class_filter_expression(classes):
    """Point cloud subset string for a list of classification codes."""
    if not classes:
        return ""
    return " OR ".join("Classification = %d" % c for c in classes)
