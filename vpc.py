"""Virtual Point Cloud (.vpc) writer and LAS/COPC header parser (no QGIS imports).

A VPC is a STAC ItemCollection (GeoJSON FeatureCollection) as written by
`pdal_wrench build_vpc` and read by QGIS (provider "vpc"). Each item points to
one point cloud file; here these are the remote AHN COPC URLs, so QGIS streams
them via HTTP range requests.
"""

import json
import struct

LAS_HEADER_SIZE = 375  # LAS 1.4 header, also used by COPC

STAC_EXTENSIONS = [
    "https://stac-extensions.github.io/pointcloud/v1.0.0/schema.json",
    "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
]


def _dim(name, typ, size):
    return {"name": name, "size": size, "type": typ}


def point_schema(pdrf):
    """Attribute schema (as in 'pc:schemas') for a LAS point data record format.

    QGIS builds the attribute list of a VPC layer from this field, so it must
    list e.g. Red/Green/Blue for the RGB renderer to become available. Names
    follow the attribute names of the QGIS COPC provider.
    """
    dims = [_dim("X", "floating", 8), _dim("Y", "floating", 8), _dim("Z", "floating", 8),
            _dim("Intensity", "unsigned", 2), _dim("ReturnNumber", "unsigned", 1),
            _dim("NumberOfReturns", "unsigned", 1), _dim("ScanDirectionFlag", "unsigned", 1),
            _dim("EdgeOfFlightLine", "unsigned", 1), _dim("Classification", "unsigned", 1),
            _dim("ScanAngleRank", "floating", 4), _dim("UserData", "unsigned", 1),
            _dim("PointSourceId", "unsigned", 2), _dim("Synthetic", "unsigned", 1),
            _dim("KeyPoint", "unsigned", 1), _dim("Withheld", "unsigned", 1)]
    if pdrf >= 6:
        dims += [_dim("Overlap", "unsigned", 1), _dim("ScannerChannel", "unsigned", 1)]
    if pdrf in (1, 3, 4, 5) or pdrf >= 6:
        dims.append(_dim("GpsTime", "floating", 8))
    if pdrf in (2, 3, 5, 7, 8, 10):
        dims += [_dim("Red", "unsigned", 2), _dim("Green", "unsigned", 2), _dim("Blue", "unsigned", 2)]
    if pdrf in (8, 10):
        dims.append(_dim("Infrared", "unsigned", 2))
    return dims


def parse_las_header(data):
    """Point count, 3D bounds and point format from the first 375 bytes of a LAS/LAZ/COPC file."""
    if len(data) < 227 or data[:4] != b"LASF":
        raise ValueError("Geen geldige LAS-header")
    minor = data[25]
    # bits 6/7 flag compression (LAZ); the low bits are the point format
    pdrf = data[104] & 0x3F
    max_x, min_x, max_y, min_y, max_z, min_z = struct.unpack_from("<6d", data, 179)
    count = struct.unpack_from("<I", data, 107)[0]
    if minor >= 4 and len(data) >= 255:
        count64 = struct.unpack_from("<Q", data, 247)[0]
        if count64:
            count = count64
    return {
        "count": int(count),
        "bbox": [min_x, min_y, min_z, max_x, max_y, max_z],
        "pdrf": int(pdrf),
    }


def _ring(xmin, ymin, xmax, ymax):
    return [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]]


def build_vpc(tiles, to_wgs84, wkt2="", epsg=7415, datetime="2000-01-01T00:00:00Z"):
    """Return the VPC as a dict.

    tiles: dicts with keys id, url, bbox ([minx,miny,minz,maxx,maxy,maxz] in
           RD/NAP), count and pdrf (LAS point data record format).
    to_wgs84: function (x, y) -> (lon, lat), used for the STAC geometry/bbox.
    """
    features = []
    for t in tiles:
        minx, miny, minz, maxx, maxy, maxz = t["bbox"]
        corners = [to_wgs84(x, y) for x, y in ((minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy))]
        lons = [c[0] for c in corners]
        lats = [c[1] for c in corners]
        geom = {"type": "Polygon", "coordinates": [[list(c) for c in corners + corners[:1]]]}
        props = {
            "datetime": datetime,
            "pc:count": int(t.get("count", 0)),
            "pc:encoding": "?",
            "pc:schemas": point_schema(int(t.get("pdrf", 6))),
            "pc:type": "lidar",
            "proj:bbox": [minx, miny, minz, maxx, maxy, maxz],
            "proj:geometry": {"type": "Polygon", "coordinates": _ring(minx, miny, maxx, maxy)},
            "proj:epsg": epsg,
        }
        if wkt2:
            props["proj:wkt2"] = wkt2
        features.append({
            "type": "Feature",
            "stac_version": "1.0.0",
            "stac_extensions": STAC_EXTENSIONS,
            "id": t["id"],
            "geometry": geom,
            "bbox": [min(lons), min(lats), minz, max(lons), max(lats), maxz],
            "properties": props,
            "links": [],
            "assets": {"data": {"href": t["url"], "roles": ["data"]}},
        })
    return {"type": "FeatureCollection", "features": features}


def write_vpc(path, vpc_dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(vpc_dict, f, indent=1)
