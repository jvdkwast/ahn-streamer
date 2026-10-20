import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ahn_tiles as t  # noqa: E402

FSN = "https://fsn1.your-objectstorage.com/hwh-ahn"


class TestTiles(unittest.TestCase):
    def test_cells_simple(self):
        cells = t.cells_for_extent(155200, 463100, 156800, 463900)
        self.assertEqual(cells, [(155000, 463000), (156000, 463000)])

    def test_cells_exact_boundary(self):
        # extent exactly covering one cell must return just that cell
        self.assertEqual(
            t.cells_for_extent(155000, 463000, 156000, 464000),
            [(155000, 463000)],
        )

    def test_cells_point_extent(self):
        self.assertEqual(
            t.cells_for_extent(155500, 463500, 155500, 463500),
            [(155000, 463000)],
        )

    def test_cells_outside_nl(self):
        self.assertEqual(t.cells_for_extent(-50000, 0, -1000, 100), [])

    def test_count_matches(self):
        ext = (150300, 460100, 154900, 463700)
        self.assertEqual(t.count_cells(*ext), len(t.cells_for_extent(*ext)))

    def test_urls_ahn4_padded(self):
        # verified to exist (HTTP 206, COPC VLR present)
        self.assertEqual(
            t.candidate_urls("AHN4", 98000, 477000),
            [("AHN4", FSN + "/AHN4_KM/01_LAZ/AHN4_C_098000_477000.COPC.LAZ")],
        )

    def test_urls_ahn6_unpadded_years(self):
        urls = [u for _, u in t.candidate_urls("AHN6", 98000, 477000)]
        # verified to exist (HTTP 200)
        self.assertIn(
            FSN + "/AHN6/01_LAZ/AHN6_2026_C_98000_477000.COPC.LAZ", urls
        )
        self.assertIn(
            FSN + "/AHN6/01_LAZ/AHN6_2025_C_98000_477000.COPC.LAZ", urls
        )

    def test_newest_combines(self):
        vs = [v for v, _ in t.candidate_urls(t.NEWEST, 155000, 463000)]
        self.assertEqual(vs, ["AHN6"] * len(t.AHN6_YEARS) + ["AHN5"])

    def test_pick_best_newest_prefers_ahn6(self):
        a = [
            ("AHN5", "x/AHN5"),
            ("AHN6", "x/AHN6_2025"),
            ("AHN6", "x/AHN6_2026"),
        ]
        self.assertEqual(t.pick_best(t.NEWEST, a), ("AHN6", "x/AHN6_2026"))
        self.assertEqual(t.pick_best(t.NEWEST, a[:1]), ("AHN5", "x/AHN5"))
        self.assertIsNone(t.pick_best("AHN4", []))

    def test_filter_expression(self):
        self.assertEqual(t.class_filter_expression(None), "")
        self.assertEqual(
            t.class_filter_expression([2, 9]),
            "Classification = 2 OR Classification = 9",
        )

    def test_bad_version(self):
        with self.assertRaises(ValueError):
            t.candidate_urls("AHN7", 0, 0)


if __name__ == "__main__":
    unittest.main()
