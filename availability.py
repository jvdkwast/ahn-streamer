"""Availability check of AHN COPC tiles: HTTP HEAD requests in a QgsTask with a
persistent cache, so panning back to a known area is instant."""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from qgis.core import QgsApplication, QgsBlockingNetworkRequest, QgsTask
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from . import ahn_tiles, vpc
from .i18n import tr

CACHE_FILE = "ahn_copc_cache.json"
TTL_OK = 90 * 24 * 3600      # existing files: re-check after 90 days
TTL_MISSING = 3 * 24 * 3600  # missing files (AHN6 grows): re-check after 3 days
USER_AGENT = "QGIS-AHN-Streamer"


def _enum(cls, scope, name):
    """Scoped enum access that works on QGIS 3 (PyQt5) and QGIS 4 (PyQt6)."""
    holder = getattr(cls, scope, None)
    if holder is not None and hasattr(holder, name):
        return getattr(holder, name)
    return getattr(cls, name)


class AvailabilityCache:
    def __init__(self, path=None):
        self.path = path or os.path.join(QgsApplication.qgisSettingsDirPath(), CACHE_FILE)
        self._lock = threading.Lock()
        self._data = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                self._data = json.load(f)
        except (OSError, ValueError):
            self._data = {}

    def get(self, url):
        """True/False when known and fresh, None when unknown or stale."""
        with self._lock:
            entry = self._data.get(url)
        if not entry:
            return None
        ttl = TTL_OK if entry.get("ok") else TTL_MISSING
        if time.time() - entry.get("t", 0) > ttl:
            return None
        return entry

    def put(self, url, ok, size=0):
        with self._lock:
            old = self._data.get(url) or {}
            entry = {"ok": bool(ok), "size": int(size or 0), "t": int(time.time())}
            # keep the parsed header as long as the file did not change
            if ok and old.get("hdr") and old.get("size") == entry["size"]:
                entry["hdr"] = old["hdr"]
            self._data[url] = entry

    def get_header(self, url):
        with self._lock:
            entry = self._data.get(url) or {}
        hdr = entry.get("hdr")
        # headers cached by v0.2.0 lack the point format: fetch them again
        return hdr if hdr and "pdrf" in hdr else None

    def put_header(self, url, hdr):
        with self._lock:
            if url in self._data:
                self._data[url]["hdr"] = hdr

    def clear(self):
        with self._lock:
            self._data = {}
        self.save()

    def save(self):
        with self._lock:
            data = dict(self._data)
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass


def _status(reply):
    """HTTP status code of a QgsNetworkReplyContent, or None."""
    code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _request(url, extra_headers=None):
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"User-Agent", USER_AGENT.encode())
    for key, value in (extra_headers or {}).items():
        req.setRawHeader(key.encode(), value.encode())
    return req


def head(url):
    """(exists, size) for a URL; exists is None on network trouble.

    Uses QgsBlockingNetworkRequest (QGIS network stack), so the user's proxy,
    SSL and authentication settings apply. Safe to call from worker threads.
    """
    blocking = QgsBlockingNetworkRequest()
    blocking.head(_request(url))
    reply = blocking.reply()
    status = _status(reply)
    if status is not None and 200 <= status < 300:
        length = bytes(reply.rawHeader(b"Content-Length") or b"0") or b"0"
        try:
            return True, int(length)
        except ValueError:
            return True, 0
    if status in (403, 404, 410):  # object storage answers 403 for a missing key
        return False, 0
    return None, 0


def read_header(url):
    """Parsed LAS header (count, bbox, pdrf) via one range request, or None."""
    blocking = QgsBlockingNetworkRequest()
    blocking.get(_request(url, {"Range": "bytes=0-%d" % (vpc.LAS_HEADER_SIZE - 1)}))
    reply = blocking.reply()
    status = _status(reply)
    if status not in (200, 206):
        return None
    try:
        return vpc.parse_las_header(bytes(reply.content())[:vpc.LAS_HEADER_SIZE])
    except ValueError:
        return None


class AvailabilityTask(QgsTask):
    """Resolve, for each cell, which COPC URL exists.

    result: list of dicts {x, y, version, url, size} for available cells and
    `missing` / `errors` lists of (x, y) for the rest.
    """

    def __init__(self, cells, version, cache, base_url=ahn_tiles.BASE_URL, on_done=None, workers=8,
                 need_header=False):
        super().__init__(tr("AHN Streamer: checking availability"),
                         _enum(QgsTask, "Flag", "CanCancel"))
        self.need_header = need_header
        self.cells = cells
        self.version = version
        self.cache = cache
        self.base_url = base_url
        self.on_done = on_done
        self.workers = workers
        self.result = []
        self.missing = []
        self.errors = []
        self.exception = None

    def run(self):
        try:
            per_cell = {}
            todo = []
            for (x, y) in self.cells:
                per_cell[(x, y)] = {"available": [], "unknown": False, "sizes": {}}
                for ver, url in ahn_tiles.candidate_urls(self.version, x, y, self.base_url):
                    known = self.cache.get(url)
                    if known is None:
                        todo.append((x, y, ver, url))
                    elif known["ok"]:
                        per_cell[(x, y)]["available"].append((ver, url))
                        per_cell[(x, y)]["sizes"][url] = known.get("size", 0)

            total = max(len(todo), 1)
            done = 0
            if todo:
                with ThreadPoolExecutor(max_workers=self.workers) as ex:
                    futures = {ex.submit(head, url): (x, y, ver, url) for (x, y, ver, url) in todo}
                    for fut in as_completed(futures):
                        if self.isCanceled():
                            for f in futures:
                                f.cancel()
                            return False
                        x, y, ver, url = futures[fut]
                        exists, size = fut.result()
                        if exists is None:
                            per_cell[(x, y)]["unknown"] = True
                        else:
                            self.cache.put(url, exists, size)
                            if exists:
                                per_cell[(x, y)]["available"].append((ver, url))
                                per_cell[(x, y)]["sizes"][url] = size
                        done += 1
                        self.setProgress(100.0 * done / total)

            for (x, y), info in per_cell.items():
                best = ahn_tiles.pick_best(self.version, info["available"])
                if best:
                    ver, url = best
                    self.result.append({"x": x, "y": y, "version": ver, "url": url,
                                        "size": info["sizes"].get(url, 0)})
                elif info["unknown"]:
                    self.errors.append((x, y))
                else:
                    self.missing.append((x, y))

            if self.need_header:
                if not self._fetch_headers():
                    return False
            self.cache.save()
            return True
        except Exception as e:  # report in finished(), never crash QGIS
            self.exception = e
            return False

    def _fetch_headers(self):
        """Add 'hdr' (count, bbox) to each result tile; needed for a VPC."""
        todo = []
        for tile in self.result:
            hdr = self.cache.get_header(tile["url"])
            if hdr:
                tile["hdr"] = hdr
            else:
                todo.append(tile)
        if not todo:
            return True
        if hasattr(self, "setDescription"):
            self.setDescription(tr("AHN Streamer: reading headers for VPC"))
        done = 0
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {ex.submit(read_header, t["url"]): t for t in todo}
            for fut in as_completed(futures):
                if self.isCanceled():
                    for f in futures:
                        f.cancel()
                    return False
                tile = futures[fut]
                hdr = fut.result()
                if hdr:
                    tile["hdr"] = hdr
                    self.cache.put_header(tile["url"], hdr)
                done += 1
                self.setProgress(100.0 * done / len(todo))
        return True

    def finished(self, ok):
        if self.on_done:
            self.on_done(self, ok)
