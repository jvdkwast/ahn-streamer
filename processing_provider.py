"""Processing provider: AHN Streamer algorithms for the Processing Toolbox,
graphical models and scripts (processing.run("ahnstreamer:createvpc", ...))."""

import os

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterPointCloudDestination,
    QgsProcessingProvider,
    QgsRectangle,
)
from qgis.PyQt.QtGui import QIcon

from . import ahn_tiles
from .availability import AvailabilityCache, Cancelled, resolve
from .i18n import tr
from .loader import T_DOUBLE, T_STRING, write_tiles_vpc

RD = QgsCoordinateReferenceSystem("EPSG:28992")
ICON = os.path.join(os.path.dirname(__file__), "icon.svg")

# Version choices: language-independent keys, newest first
VERSION_KEYS = [ahn_tiles.NEWEST] + sorted(ahn_tiles.VERSIONS, reverse=True)


def _version_labels():
    return [
        tr("Newest available") if k == ahn_tiles.NEWEST else k
        for k in VERSION_KEYS
    ]


def _integer_type():
    """Integer number type on QGIS 3 (unscoped) and QGIS 4 (scoped enum)."""
    holder = getattr(Qgis, "ProcessingNumberParameterType", None)
    if holder is not None:
        return holder.Integer
    return QgsProcessingParameterNumber.Integer


def _report(feedback, text):
    """Show a phase both next to the progress bar and in the log."""
    if hasattr(feedback, "setProgressText"):
        feedback.setProgressText(text)
    feedback.pushInfo(text)


class _AhnAlgorithm(QgsProcessingAlgorithm):
    """Shared parameters and the availability check."""

    EXTENT = "EXTENT"
    VERSION = "VERSION"
    MAX_SHEETS = "MAX_SHEETS"
    OUTPUT = "OUTPUT"

    # No group: the algorithms sit directly under "AHN Streamer"
    def group(self):
        return ""

    def groupId(self):
        return ""

    def icon(self):
        return QIcon(ICON)

    def _add_common_parameters(self):
        self.addParameter(
            QgsProcessingParameterExtent(self.EXTENT, tr("Extent"))
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VERSION,
                tr("Version"),
                options=_version_labels(),
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_SHEETS,
                tr("Maximum number of 1x1 km sheets"),
                type=_integer_type(),
                defaultValue=100,
                minValue=1,
                maxValue=5000,
            )
        )

    def _resolve(self, parameters, context, feedback, need_header):
        """Cells of the extent -> (version key, result, missing, errors)."""
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, RD)
        version = VERSION_KEYS[
            self.parameterAsEnum(parameters, self.VERSION, context)
        ]
        max_sheets = self.parameterAsInt(parameters, self.MAX_SHEETS, context)
        box = (
            extent.xMinimum(),
            extent.yMinimum(),
            extent.xMaximum(),
            extent.yMaximum(),
        )
        n = ahn_tiles.count_cells(*box)
        if n > max_sheets:
            raise QgsProcessingException(
                tr(
                    "The extent covers about %d sheets of 1 km; the maximum "
                    "is %d. Use a smaller extent or raise the maximum.",
                    n,
                    max_sheets,
                )
            )
        cells = ahn_tiles.cells_for_extent(*box)
        if not cells:
            raise QgsProcessingException(
                tr("The extent is outside the Netherlands.")
            )
        try:
            result, missing, errors = resolve(
                cells,
                version,
                AvailabilityCache(),
                need_header=need_header,
                is_canceled=feedback.isCanceled,
                progress=feedback.setProgress,
                describe=lambda text: _report(feedback, text),
            )
        except Cancelled:
            raise QgsProcessingException(tr("Cancelled."))
        if missing:
            feedback.pushWarning(
                tr("%d sheets not available in this version.", len(missing))
            )
        if errors:
            feedback.pushWarning(
                tr(
                    "%d sheets could not be checked (network error).",
                    len(errors),
                )
            )
        return version, result, missing, errors


class CreateVpcAlgorithm(_AhnAlgorithm):
    SHEETS = "SHEETS"

    def name(self):
        return "createvpc"

    def displayName(self):
        return tr("Create AHN virtual point cloud (VPC) for extent")

    def shortHelpString(self):
        return tr(
            "Writes a virtual point cloud (.vpc) with all AHN COPC sheets "
            "(1x1 km) that intersect the extent. The VPC refers to the "
            "remote files on the official AHN storage, so the points are "
            "streamed, not downloaded. The output can be used as input for "
            "point cloud algorithms, e.g. to clip it or to create a DTM. "
            "Source: AHN (www.ahn.nl); AHN5 and AHN6 are CC BY 4.0."
        )

    def createInstance(self):
        return CreateVpcAlgorithm()

    def initAlgorithm(self, config=None):
        self._add_common_parameters()
        self.addParameter(
            QgsProcessingParameterPointCloudDestination(
                self.OUTPUT, tr("Virtual point cloud")
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(self.SHEETS, tr("Number of sheets"))
        )

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        if not path.lower().endswith(".vpc"):
            path = os.path.splitext(path)[0] + ".vpc"
        _version, result, _missing, _errors = self._resolve(
            parameters, context, feedback, need_header=True
        )
        if not result:
            raise QgsProcessingException(
                tr("No AHN sheets available for this extent and version.")
            )
        tiles = sorted(result, key=lambda t: (-t["y"], t["x"]))
        _report(feedback, tr("Writing virtual point cloud"))
        write_tiles_vpc(tiles, path, context.transformContext())
        feedback.pushInfo(
            tr("Virtual point cloud with %d sheets written.", len(tiles))
        )
        return {self.OUTPUT: path, self.SHEETS: len(tiles)}


class SheetsAlgorithm(_AhnAlgorithm):
    def name(self):
        return "sheets"

    def displayName(self):
        return tr("AHN sheets for extent")

    def shortHelpString(self):
        return tr(
            "Creates a polygon layer with the AHN sheets (1x1 km) that "
            "intersect the extent, with their status, version, size and "
            "COPC URL. Use the URLs in your own workflows or models."
        )

    def createInstance(self):
        return SheetsAlgorithm()

    def initAlgorithm(self, config=None):
        self._add_common_parameters()
        self.addParameter(
            QgsProcessingParameterFeatureSink(self.OUTPUT, tr("AHN sheets"))
        )

    def processAlgorithm(self, parameters, context, feedback):
        _version, result, missing, errors = self._resolve(
            parameters, context, feedback, need_header=False
        )
        fields = QgsFields()
        for name, typ in (
            ("sheet", T_STRING),
            ("version", T_STRING),
            ("status", T_STRING),
            ("size_mb", T_DOUBLE),
            ("url", T_STRING),
        ):
            fields.append(QgsField(name, typ))
        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            Qgis.WkbType.Polygon,
            RD,
        )
        if sink is None:
            raise QgsProcessingException(
                self.invalidSinkError(parameters, self.OUTPUT)
            )

        rows = [
            (
                t["x"],
                t["y"],
                t["version"],
                tr("available"),
                t["size"],
                t["url"],
            )
            for t in result
        ]
        rows += [(x, y, "", tr("not available"), 0, "") for x, y in missing]
        rows += [(x, y, "", tr("network error"), 0, "") for x, y in errors]
        for x, y, version, status, size, url in sorted(
            rows, key=lambda r: (-r[1], r[0])
        ):
            f = QgsFeature(fields)
            f.setGeometry(
                QgsGeometry.fromRect(
                    QgsRectangle(x, y, x + ahn_tiles.CELL, y + ahn_tiles.CELL)
                )
            )
            f.setAttributes(
                [
                    ahn_tiles.tile_name(x, y),
                    version,
                    status,
                    round(size / 1e6, 1) if size else None,
                    url,
                ]
            )
            sink.addFeature(f)
        return {self.OUTPUT: dest_id}


class AhnProcessingProvider(QgsProcessingProvider):
    def id(self):
        return "ahnstreamer"

    def name(self):
        return "AHN Streamer"

    def icon(self):
        return QIcon(ICON)

    def loadAlgorithms(self):
        self.addAlgorithm(CreateVpcAlgorithm())
        self.addAlgorithm(SheetsAlgorithm())

    def supportedOutputPointCloudLayerExtensions(self):
        return ["vpc"]

    def defaultPointCloudFileExtension(self):
        return "vpc"
