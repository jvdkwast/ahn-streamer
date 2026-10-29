"""Dock panel: choose AHN version, class filter and styling, then stream the
COPC tiles for the current map canvas extent."""

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsSettings,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import ahn_tiles, loader
from .i18n import tr
from .availability import AvailabilityCache, AvailabilityTask

SETTINGS = "ahn_copc/"
RD = QgsCoordinateReferenceSystem("EPSG:28992")

# Share of the progress bar used by the availability check (rest: opening)
CHECK_SHARE_TILES = 0.3
CHECK_SHARE_VPC = 0.95


def _level(name):
    holder = getattr(Qgis, "MessageLevel", None)
    return (
        getattr(holder, name)
        if holder is not None and hasattr(holder, name)
        else getattr(Qgis, name)
    )


class AhnDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("AHN Streamer", parent)
        self.setObjectName("AhnStreamerDock")
        self.iface = iface
        self.cache = AvailabilityCache()
        self.task = None
        self._build_ui()
        self._restore()

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()

        # Combo boxes show translated labels and carry language-independent
        # as item data; the keys are what is stored in the settings.
        self.cb_version = QComboBox()
        self.cb_version.addItem(tr("Newest available"), ahn_tiles.NEWEST)
        for v in sorted(ahn_tiles.VERSIONS, reverse=True):
            self.cb_version.addItem(v, v)
        self.cb_version.setToolTip(
            tr(
                "'Newest available' loads AHN6 per 1 km sheet and falls back"
                " to AHN5."
            )
        )
        form.addRow(tr("Version"), self.cb_version)

        self.cb_classes = QComboBox()
        for key, (label, _classes) in ahn_tiles.CLASS_FILTERS.items():
            self.cb_classes.addItem(tr(label), key)
        form.addRow(tr("Points"), self.cb_classes)

        self.cb_render = QComboBox()
        for key, label in loader.RENDERERS.items():
            self.cb_render.addItem(tr(label), key)
        form.addRow(tr("Style"), self.cb_render)

        zrow = QHBoxLayout()
        self.sp_zmin = QDoubleSpinBox()
        self.sp_zmax = QDoubleSpinBox()
        for sp in (self.sp_zmin, self.sp_zmax):
            sp.setRange(-100, 70000)
            sp.setDecimals(1)
        zrow.addWidget(self.sp_zmin)
        zrow.addWidget(QLabel(tr("to")))
        zrow.addWidget(self.sp_zmax)
        self.lbl_z = QLabel(tr("Range"))
        form.addRow(self.lbl_z, zrow)
        self._range_mode = (
            None  # renderer whose range the spinboxes currently show
        )

        self.sp_max = QSpinBox()
        self.sp_max.setRange(1, 200)
        self.sp_max.setToolTip(
            tr("Maximum number of 1x1 km sheets to load at once.")
        )
        form.addRow(tr("Max. sheets"), self.sp_max)

        self.chk_vpc = QCheckBox(
            tr("Merge into one virtual point cloud (VPC)")
        )
        self.chk_vpc.setToolTip(
            tr(
                "All sheets in one layer (.vpc referring to the remote COPC"
                " files). New sheets are added to the same VPC. Zoomed out,"
                " QGIS shows the sheet outlines; zoomed in, the points."
            )
        )
        form.addRow("", self.chk_vpc)

        self.chk_sheets = QCheckBox(tr("Show sheets with status"))
        form.addRow("", self.chk_sheets)
        lay.addLayout(form)

        self.btn_load = QPushButton(tr("Load point cloud for map extent"))
        self.btn_load.setDefault(True)
        self.btn_apply = QPushButton(
            tr("Apply filter and style to loaded layers")
        )
        self.btn_remove = QPushButton(tr("Remove AHN layers"))
        self.btn_cancel = QPushButton(tr("Cancel"))
        self.btn_cancel.setVisible(False)
        for b in (
            self.btn_load,
            self.btn_cancel,
            self.btn_apply,
            self.btn_remove,
        ):
            lay.addWidget(b)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        lay.addStretch(1)
        footer = QLabel(
            tr(
                'Source: <a href="https://www.ahn.nl/dataroom">AHN</a>.'
                " AHN2-4: CC0, AHN5-6: CC BY 4.0 (attribution required). Data"
                " is streamed as COPC; nothing is downloaded."
            )
        )
        footer.setWordWrap(True)
        footer.setOpenExternalLinks(True)
        footer.setStyleSheet("color: gray; font-size: 8pt;")
        lay.addWidget(footer)
        self.setWidget(w)

        self.btn_load.clicked.connect(self.load_extent)
        self.btn_apply.clicked.connect(self.apply_to_loaded)
        self.btn_remove.clicked.connect(self.remove_layers)
        self.btn_cancel.clicked.connect(self.cancel)
        self.cb_render.currentIndexChanged.connect(
            lambda _i: self._render_changed(self._render_key())
        )

    def _render_key(self):
        return self.cb_render.currentData()

    @staticmethod
    def _select(combo, key, default):
        """Select the item whose data is `key` (or `default` if not found)."""
        index = combo.findData(key)
        if index < 0:
            index = combo.findData(default)
        combo.setCurrentIndex(max(index, 0))

    def _range_key(self, mode):
        return SETTINGS + "range/" + loader.RANGED[mode][0]

    def _store_range(self):
        if self._range_mode is not None:
            key = self._range_key(self._range_mode)
            s = QgsSettings()
            s.setValue(key + "/min", self.sp_zmin.value())
            s.setValue(key + "/max", self.sp_zmax.value())

    def _render_changed(self, mode):
        """Show the range of the chosen renderer in the spinboxes."""
        self._store_range()
        on = mode in loader.RANGED
        for wdg in (self.sp_zmin, self.sp_zmax, self.lbl_z):
            wdg.setEnabled(on)
        if not on:
            self._range_mode = None
            return
        attribute, dmin, dmax, unit = loader.RANGED[mode]
        s = QgsSettings()
        key = self._range_key(mode)
        for sp in (self.sp_zmin, self.sp_zmax):
            sp.setSuffix(unit)
        self.sp_zmin.setValue(float(s.value(key + "/min", dmin)))
        self.sp_zmax.setValue(float(s.value(key + "/max", dmax)))
        self.lbl_z.setText(
            tr("Height range") if attribute == "Z" else tr("Intensity range")
        )
        self._range_mode = mode

    def _range(self):
        """(min, max) of the current renderer, or (None, None) if none."""
        if self._render_key() in loader.RANGED:
            return self.sp_zmin.value(), self.sp_zmax.value()
        return None, None

    def _restore(self):
        s = QgsSettings()
        self._select(
            self.cb_version,
            s.value(SETTINGS + "version", ahn_tiles.NEWEST),
            ahn_tiles.NEWEST,
        )
        self._select(
            self.cb_classes, s.value(SETTINGS + "classes", "all"), "all"
        )
        self._select(
            self.cb_render,
            s.value(SETTINGS + "render", loader.RENDER_CLASSES),
            loader.RENDER_CLASSES,
        )
        self.sp_max.setValue(int(s.value(SETTINGS + "max_tiles", 16)))
        self.chk_sheets.setChecked(
            str(s.value(SETTINGS + "sheets", True)).lower() in ("true", "1")
        )
        self.chk_vpc.setChecked(
            str(s.value(SETTINGS + "vpc", False)).lower() in ("true", "1")
        )
        self._render_changed(self._render_key())

    def _save(self):
        s = QgsSettings()
        s.setValue(SETTINGS + "version", self.cb_version.currentData())
        s.setValue(SETTINGS + "classes", self.cb_classes.currentData())
        s.setValue(SETTINGS + "render", self._render_key())
        self._store_range()
        s.setValue(SETTINGS + "max_tiles", self.sp_max.value())
        s.setValue(SETTINGS + "sheets", self.chk_sheets.isChecked())
        s.setValue(SETTINGS + "vpc", self.chk_vpc.isChecked())

    def _busy(self, busy):
        self.btn_load.setEnabled(not busy)
        self.btn_apply.setEnabled(not busy)
        self.btn_remove.setEnabled(not busy)
        self.btn_cancel.setVisible(busy)
        self.progress.setVisible(busy)
        self.progress.setValue(0)
        self._cancel_open = False

    def _show_progress(self, pct, text):
        """Overall progress (0-100) with a label of the current phase."""
        self.progress.setFormat("%s  %%p%%" % text.replace("%", "%%"))
        self.progress.setValue(int(round(pct)))

    def _msg(self, text, level="Info", duration=6):
        self.iface.messageBar().pushMessage(
            "AHN Streamer", text, _level(level), duration
        )

    # ------------------------------------------------------------ actions
    def _subset(self):
        _label, classes = ahn_tiles.CLASS_FILTERS.get(
            self.cb_classes.currentData(), ("", None)
        )
        return ahn_tiles.class_filter_expression(classes)

    def _canvas_extent_rd(self):
        canvas = self.iface.mapCanvas()
        src = canvas.mapSettings().destinationCrs()
        extent = canvas.extent()
        if src != RD:
            xform = QgsCoordinateTransform(src, RD, QgsProject.instance())
            extent = xform.transformBoundingBox(extent)
        return extent

    def load_extent(self):
        if self.task is not None:
            return
        self._save()
        e = self._canvas_extent_rd()
        n = ahn_tiles.count_cells(
            e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()
        )
        max_tiles = self.sp_max.value()
        if n > max_tiles:
            self._msg(
                tr(
                    "The map extent covers about %d sheets of 1 km; the"
                    " maximum is %d. Zoom in or raise the maximum.",
                    n,
                    max_tiles,
                ),
                "Warning",
            )
            return
        cells = ahn_tiles.cells_for_extent(
            e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()
        )
        if not cells:
            self._msg(
                tr("The map extent is outside the Netherlands."), "Warning"
            )
            return

        version = self.cb_version.currentData()
        self.lbl_status.setText(
            tr("Checking availability of %d sheets...", len(cells))
        )
        self._busy(True)
        self.task = AvailabilityTask(
            cells,
            version,
            self.cache,
            on_done=self._task_done,
            need_header=self.chk_vpc.isChecked(),
        )
        self.task.as_vpc = self.chk_vpc.isChecked()
        # Share of the bar for the availability check; the rest is opening
        # the layers. Opening one remote COPC per sheet is the slow part; a
        # VPC opens instantly but needs the headers read during the check.
        share = CHECK_SHARE_VPC if self.task.as_vpc else CHECK_SHARE_TILES
        label = tr("Checking availability")
        self._show_progress(0, label)
        self.task.progressChanged.connect(
            lambda p: self._show_progress(p * share, label)
        )
        QgsApplication.taskManager().addTask(self.task)

    def cancel(self):
        if self.task is not None:
            self.task.cancel()
        self._cancel_open = True  # also stops opening layers

    def _task_done(self, task, ok):
        self.task = None
        if not ok:
            self._busy(False)
            if task.exception is not None:
                self.lbl_status.setText(tr("Error: %s", task.exception))
                self._msg(
                    tr("Error while checking: %s", task.exception),
                    "Critical",
                    10,
                )
            else:
                self.lbl_status.setText(tr("Cancelled."))
            return

        already = loader.loaded_urls()
        subset = self._subset()
        mode = self._render_key()
        zmin, zmax = self._range()

        layers, failed, skipped = [], 0, 0
        if task.as_vpc:
            layers, failed, skipped = self._load_as_vpc(
                task, mode, subset, zmin, zmax
            )
        else:
            todo = []
            for tile in sorted(task.result, key=lambda t: (-t["y"], t["x"])):
                if tile["url"] in already:
                    skipped += 1
                else:
                    todo.append(tile)
            share = CHECK_SHARE_TILES * 100
            for i, tile in enumerate(todo):
                if self._cancel_open:
                    break
                # Opening a remote COPC blocks while QGIS reads its header and
                # index, so update the bar before each sheet and let it paint.
                self._show_progress(
                    share + (100 - share) * i / len(todo),
                    tr("Opening sheet %d of %d", i + 1, len(todo)),
                )
                QCoreApplication.processEvents()
                layer = loader.make_layer(tile, mode, subset, zmin, zmax)
                if layer is None:
                    failed += 1
                else:
                    layers.append(layer)
            if layers:
                loader.add_layers(layers)
        self._busy(False)
        if self.chk_sheets.isChecked():
            loader.replace_sheets_layer(
                loader.sheets_layer(task.result, task.missing, task.errors)
            )

        size = sum(t["size"] for t in task.result) / 1e9
        shown = (
            tr("Newest available")
            if task.version == ahn_tiles.NEWEST
            else task.version
        )
        parts = [tr("%d sheets loaded", len(layers))]
        if skipped:
            parts.append(tr("%d already present", skipped))
        if task.missing:
            parts.append(
                tr("%d not available in %s", len(task.missing), shown)
            )
        if task.errors:
            parts.append(tr("%d network errors", len(task.errors)))
        if failed:
            parts.append(tr("%d could not be opened", failed))
        text = ", ".join(parts) + tr(
            ". (%.1f GB in total on the server; only the visible part is"
            " streamed.)",
            size,
        )
        self.lbl_status.setText(text)
        level = "Warning" if (task.errors or failed) else "Success"
        self._msg(text, level)

    def _load_as_vpc(self, task, mode, subset, zmin, zmax):
        """Merge the tiles into one VPC layer per version choice.

        Returns (tiles newly added, failed count, already-present count)
        so the status message can be shared with the per-tile mode.
        """
        # language-independent key: "AHN6", ..., or "newest"
        label = task.version
        old = loader.find_vpc_layer(label)
        tiles = {
            t["url"]: t
            for t in (loader.vpc_tiles_of(old) if old is not None else [])
        }
        new = [t for t in task.result if t["url"] not in tiles]
        skipped = len(task.result) - len(new)
        if not new:
            return [], 0, skipped
        for t in new:
            tiles[t["url"]] = t
        ordered = sorted(tiles.values(), key=lambda t: (-t["y"], t["x"]))
        self._show_progress(
            CHECK_SHARE_VPC * 100, tr("Writing virtual point cloud")
        )
        QCoreApplication.processEvents()
        layer = loader.make_vpc_layer(ordered, label, mode, subset, zmin, zmax)
        if layer is None:
            return [], len(new), skipped
        canvas = self.iface.mapCanvas()
        canvas.stopRendering()
        loader.replace_vpc_layer(old, layer)
        canvas.refresh()
        return new, 0, skipped

    def apply_to_loaded(self):
        self._save()
        subset = self._subset()
        mode = self._render_key()
        count = 0
        for layer in QgsProject.instance().mapLayers().values():
            if layer.customProperty(loader.PROP_KEY):
                layer.setSubsetString(subset)
                loader.apply_renderer(layer, mode, *self._range())
                count += 1
        self.lbl_status.setText(
            tr("Filter and style applied to %d layers.", count)
        )

    def remove_layers(self):
        canvas = self.iface.mapCanvas()
        # Stop a running render job of the remote point clouds first;
        # otherwise the old image stays visible until that job finishes.
        canvas.stopRendering()
        loader.remove_all()
        canvas.refresh()
        self.lbl_status.setText(tr("AHN layers removed."))

    def shutdown(self):
        self.cancel()
