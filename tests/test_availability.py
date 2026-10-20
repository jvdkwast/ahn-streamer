"""Tests AvailabilityTask.run() and the cache with a stub of qgis.core."""

import importlib
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()


def _install_stubs():
    qgis = types.ModuleType("qgis")
    core = types.ModuleType("qgis.core")

    class QgsTask:
        class Flag:
            CanCancel = 1

        def __init__(self, desc, flags):
            self._cancel = False
            self.progress = 0

        def isCanceled(self):
            return self._cancel

        def setProgress(self, p):
            self.progress = p

    class QgsApplication:
        @staticmethod
        def qgisSettingsDirPath():
            return TMP

        @staticmethod
        def locale():
            return "en_US"

    class QgsSettings:
        def value(self, key, default=None):
            return default

    core.QgsTask, core.QgsApplication, core.QgsSettings = (
        QgsTask,
        QgsApplication,
        QgsSettings,
    )
    core.QgsBlockingNetworkRequest = (
        object  # network calls are replaced by fakes below
    )

    class Qgis:
        Warning, Info, Critical = 1, 0, 2

    class QgsMessageLog:
        messages = []

        @staticmethod
        def logMessage(msg, tag, level):
            QgsMessageLog.messages.append((msg, tag, level))

    core.Qgis, core.QgsMessageLog = Qgis, QgsMessageLog
    qgis.core = core
    pyqt = types.ModuleType("qgis.PyQt")
    qtcore = types.ModuleType("qgis.PyQt.QtCore")
    qtnet = types.ModuleType("qgis.PyQt.QtNetwork")
    qtcore.QUrl = str
    qtnet.QNetworkRequest = object
    sys.modules.update(
        {
            "qgis": qgis,
            "qgis.core": core,
            "qgis.PyQt": pyqt,
            "qgis.PyQt.QtCore": qtcore,
            "qgis.PyQt.QtNetwork": qtnet,
        }
    )

    # expose the plugin dir as package "ahn_streamer"
    pkg = types.ModuleType("ahn_streamer")
    pkg.__path__ = [ROOT]
    sys.modules["ahn_streamer"] = pkg


_install_stubs()
availability = importlib.import_module("ahn_streamer.availability")
ahn_tiles = importlib.import_module("ahn_streamer.ahn_tiles")

EXISTING = {
    ahn_tiles.BASE_URL
    + "/AHN6/01_LAZ/AHN6_2026_C_98000_477000.COPC.LAZ": 203736291,
    ahn_tiles.BASE_URL
    + "/AHN5_KM/01_LAZ/AHN5_C_099000_477000.COPC.LAZ": 119703060,
    ahn_tiles.BASE_URL
    + "/AHN4_KM/01_LAZ/AHN4_C_098000_477000.COPC.LAZ": 248534833,
}
NETFAIL = {
    ahn_tiles.BASE_URL + "/AHN5_KM/01_LAZ/AHN5_C_100000_477000.COPC.LAZ"
}
calls = []


def fake_head(url):
    calls.append(url)
    if url in NETFAIL:
        return None, 0
    if url in EXISTING:
        return True, EXISTING[url]
    return False, 0


class TestAvailability(unittest.TestCase):
    def setUp(self):
        availability.head = fake_head
        calls.clear()
        self.cache = availability.AvailabilityCache(
            os.path.join(TMP, "c.json")
        )
        self.cache.clear()

    def run_task(self, cells, version):
        done = {}
        t = availability.AvailabilityTask(
            cells,
            version,
            self.cache,
            on_done=lambda task, ok: done.setdefault("ok", ok),
        )
        ok = t.run()
        t.finished(ok)
        self.assertTrue(done["ok"])
        return t

    def test_newest_fallback_and_errors(self):
        cells = [
            (98000, 477000),
            (99000, 477000),
            (100000, 477000),
            (101000, 477000),
        ]
        t = self.run_task(cells, ahn_tiles.NEWEST)
        got = {(r["x"], r["version"]) for r in t.result}
        self.assertEqual(got, {(98000, "AHN6"), (99000, "AHN5")})
        self.assertEqual(t.errors, [(100000, 477000)])
        self.assertEqual(t.missing, [(101000, 477000)])
        self.assertEqual(t.progress, 100.0)

    def test_cache_prevents_requests(self):
        cells = [(98000, 477000)]
        self.run_task(cells, "AHN4")
        self.assertEqual(len(calls), 1)
        calls.clear()
        # new cache object reads the saved file
        self.cache = availability.AvailabilityCache(
            os.path.join(TMP, "c.json")
        )
        t = self.run_task(cells, "AHN4")
        self.assertEqual(calls, [])
        self.assertEqual(t.result[0]["size"], 248534833)

    def test_headers_fetched_and_cached(self):
        hdr_calls = []

        def fake_read_header(url):
            hdr_calls.append(url)
            return {
                "count": 5,
                "bbox": [98000, 477000, -2, 99000, 478000, 30],
                "pdrf": 6,
            }

        availability.read_header = fake_read_header
        t = availability.AvailabilityTask(
            [(98000, 477000)], "AHN4", self.cache, need_header=True
        )
        self.assertTrue(t.run())
        self.assertEqual(t.result[0]["hdr"]["count"], 5)
        self.assertEqual(len(hdr_calls), 1)
        # second run: header from cache, no request
        t = availability.AvailabilityTask(
            [(98000, 477000)], "AHN4", self.cache, need_header=True
        )
        self.assertTrue(t.run())
        self.assertEqual(len(hdr_calls), 1)
        self.assertEqual(t.result[0]["hdr"]["bbox"][5], 30)

    def test_network_errors_not_cached(self):
        self.run_task([(100000, 477000)], "AHN5")
        self.assertIsNone(self.cache.get(next(iter(NETFAIL))))


if __name__ == "__main__":
    unittest.main()
