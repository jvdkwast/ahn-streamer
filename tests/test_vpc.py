import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vpc  # noqa: E402


def fake_header(count, bounds, minor=4):
    b = bytearray(375)
    b[:4] = b"LASF"
    b[24], b[25] = 1, minor
    struct.pack_into("<I", b, 107, 0 if minor >= 4 else count)
    max_x, min_x, max_y, min_y, max_z, min_z = bounds
    struct.pack_into("<6d", b, 179, max_x, min_x, max_y, min_y, max_z, min_z)
    struct.pack_into("<Q", b, 247, count)
    return bytes(b)


class TestVpc(unittest.TestCase):
    def test_parse_header_14(self):
        h = vpc.parse_las_header(
            fake_header(
                12345678901, (156000, 155000, 464000, 463000, 52.5, -3.25)
            )
        )
        self.assertEqual(h["count"], 12345678901)
        self.assertEqual(
            h["bbox"], [155000, 463000, -3.25, 156000, 464000, 52.5]
        )

    def test_parse_pdrf_with_laz_bits(self):
        b = bytearray(fake_header(1, (1, 0, 1, 0, 1, 0)))
        b[104] = 7 | 0x80  # compressed flag set, as in LAZ/COPC
        self.assertEqual(vpc.parse_las_header(bytes(b))["pdrf"], 7)

    def test_schema_rgb(self):
        names7 = [d["name"] for d in vpc.point_schema(7)]
        names6 = [d["name"] for d in vpc.point_schema(6)]
        for c in ("Red", "Green", "Blue"):
            self.assertIn(c, names7)
            self.assertNotIn(c, names6)
        self.assertIn("Infrared", [d["name"] for d in vpc.point_schema(8)])
        self.assertIn("Classification", names6)

    def test_vpc_has_schema(self):
        tiles = [
            {
                "id": "a",
                "url": "u",
                "bbox": [0, 0, 0, 1, 1, 1],
                "count": 1,
                "pdrf": 7,
            }
        ]
        f = vpc.build_vpc(tiles, lambda x, y: (x, y))["features"][0]
        self.assertIn(
            "Red", [d["name"] for d in f["properties"]["pc:schemas"]]
        )

    def test_parse_header_legacy(self):
        b = bytearray(fake_header(0, (1, 0, 1, 0, 1, 0), minor=2))
        struct.pack_into("<I", b, 107, 42)
        self.assertEqual(vpc.parse_las_header(bytes(b))["count"], 42)

    def test_bad_header(self):
        with self.assertRaises(ValueError):
            vpc.parse_las_header(b"<?xml version")

    def test_build_and_write(self):
        tiles = [
            {
                "id": "AHN4_155000_463000",
                "url": "https://x/a.COPC.LAZ",
                "bbox": [155000, 463000, -3, 156000, 464000, 50],
                "count": 10,
            }
        ]
        d = vpc.build_vpc(tiles, lambda x, y: (x / 1e5, y / 1e5), wkt2="WKT")
        f = d["features"][0]
        self.assertEqual(f["assets"]["data"]["href"], "https://x/a.COPC.LAZ")
        self.assertEqual(
            f["properties"]["proj:bbox"],
            [155000, 463000, -3, 156000, 464000, 50],
        )
        self.assertEqual(f["properties"]["pc:count"], 10)
        self.assertEqual(f["bbox"], [1.55, 4.63, -3, 1.56, 4.64, 50])
        self.assertEqual(len(f["geometry"]["coordinates"][0]), 5)
        path = os.path.join(tempfile.mkdtemp(), "t.vpc")
        vpc.write_vpc(path, d)
        with open(path) as fh:
            self.assertEqual(json.load(fh)["type"], "FeatureCollection")


if __name__ == "__main__":
    unittest.main()
