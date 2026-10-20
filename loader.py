"""Create remote COPC layers (streamed by QGIS via HTTP range requests),
renderers, the sheet overlay layer and attribution metadata."""

import json
import os
import time

from qgis.core import (
    QgsApplication,
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsPalLayerSettings,
    QgsPointCloudAttributeByRampRenderer,
    QgsPointCloudCategory,
    QgsPointCloudClassifiedRenderer,
    QgsPointCloudLayer,
    QgsPointCloudRendererRegistry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsStyle,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.core import Qgis
from qgis.PyQt.QtGui import QColor

from . import ahn_tiles, vpc
from .i18n import tr
from .log import log

# Field types: QMetaType on QGIS >= 3.38 (required on Qt6), QVariant before.
if Qgis.QGIS_VERSION_INT >= 33800:
    from qgis.PyQt.QtCore import QMetaType

    T_STRING, T_DOUBLE = QMetaType.Type.QString, QMetaType.Type.Double
else:
    from qgis.PyQt.QtCore import QVariant

    T_STRING, T_DOUBLE = QVariant.String, QVariant.Double

GROUP_NAME = "AHN Streamer"
SHEETS_PROP = (  # marks the sheet overlay layer (its name is translated)
    "ahn_copc/sheets"
)
PROP_KEY = "ahn_copc/url"  # custom property to recognise our layers
VPC_LABEL = "ahn_copc/vpc_label"
VPC_TILES = "ahn_copc/vpc_tiles"

# Renderer keys (stored in the settings) and their English labels
# (translated in the UI)
RENDER_DEFAULT = "default"
RENDER_CLASSES = "classes"
RENDER_HEIGHT = "height"
RENDER_INTENSITY = "intensity"
RENDER_RETURNS = "returns"
RENDERERS = {
    RENDER_CLASSES: "Classification (AHN colours)",
    RENDER_HEIGHT: "Height above NAP",
    RENDER_INTENSITY: "Intensity",
    RENDER_RETURNS: "Number of returns (vegetation/edges)",
    RENDER_DEFAULT: "QGIS default (RGB if present)",
}

# Renderers with a value range set in the panel:
#   mode -> (attribute, default min, default max, unit)
# The range is fixed instead of taken from layer statistics, because QGIS has
# no
# statistics for a VPC with remote files; a fixed range also makes adjacent
# tiles use identical colours.
RANGED = {
    RENDER_HEIGHT: ("Z", -5.0, 40.0, " m"),
    RENDER_INTENSITY: ("Intensity", 0.0, 2000.0, ""),
}

RETURN_COLORS = {
    1: "#d9d9d9",
    2: "#a1d99b",
    3: "#41ab5d",
    4: "#006d2c",
    5: "#00441b",
}


def get_group(create=True):
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(GROUP_NAME)
    if group is None and create:
        group = root.insertGroup(0, GROUP_NAME)
    return group


def loaded_urls():
    urls = set()
    for layer in QgsProject.instance().mapLayers().values():
        url = layer.customProperty(PROP_KEY)
        if url:
            urls.add(url)
    return urls


def _classified_renderer():
    cats = []
    for code, (label, color) in sorted(ahn_tiles.CLASSES.items()):
        cats.append(
            QgsPointCloudCategory(
                code, QColor(color), "%d %s" % (code, tr(label))
            )
        )
    r = QgsPointCloudClassifiedRenderer("Classification", cats)
    return r


def _returns_renderer():
    cats = []
    for n, color in sorted(RETURN_COLORS.items()):
        if n == 1:
            label = tr("1 return")
        elif n < 5:
            label = tr("%d returns", n)
        else:
            label = tr("5 or more returns")
        cats.append(QgsPointCloudCategory(n, QColor(color), label))
    for n in range(6, 16):  # higher counts get the darkest colour as well
        cats.append(
            QgsPointCloudCategory(
                n, QColor(RETURN_COLORS[5]), tr("%d returns", n)
            )
        )
    return QgsPointCloudClassifiedRenderer("NumberOfReturns", cats)


def _ramp_renderer(attribute, vmin, vmax, ramp_name, invert):
    r = QgsPointCloudAttributeByRampRenderer()
    r.setAttribute(attribute)
    r.setMinimum(vmin)
    r.setMaximum(vmax)
    ramp = QgsStyle.defaultStyle().colorRamp(ramp_name)
    shader = QgsColorRampShader(vmin, vmax)
    if ramp is not None:
        if invert:
            ramp.invert()
        shader.setSourceColorRamp(ramp)
        shader.classifyColorRamp(5, -1, QgsRectangle(), None)
    r.setColorRampShader(shader)
    return r


def ensure_3d_renderer(layer):
    """Give the layer a 3D renderer set to 'Follow 2D symbology'.

    QgsPointCloudLayer.convertRenderer3DFromRenderer2D() only updates an
    existing 3D renderer; layers created from Python have none (the QGIS GUI
    adds one when you load a layer by hand), which shows as "No rendering".
    """
    try:
        from qgis._3d import QgsPointCloudLayer3DRenderer
    except ImportError:  # QGIS built without 3D support
        return
    try:
        if layer.renderer3D() is None:
            # No symbol needed: convertFrom2DRenderer() creates it from the
            # 2D renderer.
            r3d = QgsPointCloudLayer3DRenderer()
            r3d.setLayer(layer)
            layer.setRenderer3D(r3d)
        if hasattr(layer, "setSync3DRendererTo2DRenderer"):
            layer.setSync3DRendererTo2DRenderer(True)
    except Exception as e:  # 3D problems must never block loading the 2D layer
        log("Could not set up the 3D renderer for %s: %s" % (layer.name(), e))


def apply_renderer(layer, mode, vmin=None, vmax=None):
    """Apply one of RENDERERS; vmin/vmax: value range for modes in RANGED."""
    ensure_3d_renderer(layer)
    if mode in RANGED:
        attribute, dmin, dmax, _ = RANGED[mode]
        vmin = dmin if vmin is None else vmin
        vmax = dmax if vmax is None else vmax
    if mode == RENDER_CLASSES:
        layer.setRenderer(_classified_renderer())
    elif mode == RENDER_HEIGHT:
        # Spectral inverted: low = blue, high = red
        layer.setRenderer(_ramp_renderer("Z", vmin, vmax, "Spectral", True))
    elif mode == RENDER_INTENSITY:
        layer.setRenderer(
            _ramp_renderer("Intensity", vmin, vmax, "Greys", True)
        )
    elif mode == RENDER_RETURNS:
        layer.setRenderer(_returns_renderer())
    else:
        # what QGIS would choose itself: RGB for AHN6, classification otherwise
        try:
            r = QgsPointCloudRendererRegistry.defaultRenderer(layer)
            if r is not None:
                layer.setRenderer(r)
        except TypeError as e:  # older QGIS signature
            log(
                "Could not create the default renderer for %s: %s"
                % (layer.name(), e)
            )
    # Convert the 3D renderer to the 2D symbology (explicit for older QGIS)
    if layer.renderer3D() is not None and hasattr(
        layer, "convertRenderer3DFromRenderer2D"
    ):
        try:
            layer.convertRenderer3DFromRenderer2D()
        except Exception as e:  # keep the 2D layer usable even if 3D fails
            log(
                "Could not convert the 3D renderer for %s: %s"
                % (layer.name(), e)
            )
    layer.triggerRepaint()


def _set_metadata(layer, version):
    info = ahn_tiles.VERSIONS.get(version, {})
    md = layer.metadata()
    md.setTitle(layer.name())
    md.setAbstract(
        tr(
            "Point cloud of the Actueel Hoogtebestand Nederland (%s, %s),"
            " streamed as Cloud Optimized Point Cloud (COPC).",
            version,
            info.get("period", ""),
        )
    )
    md.setRights([tr("Source: AHN (www.ahn.nl)")])
    md.setLicenses([info.get("license", "")])
    layer.setMetadata(md)


def make_layer(tile, renderer_mode, subset="", zmin=None, zmax=None):
    """QgsPointCloudLayer for one tile dict from AvailabilityTask, or None."""
    name = "%s %s" % (
        tile["version"],
        ahn_tiles.tile_name(tile["x"], tile["y"]),
    )
    layer = QgsPointCloudLayer(tile["url"], name, "copc")
    if not layer.isValid():
        return None
    if not layer.crs().isValid():
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:7415"))
    if subset:
        layer.setSubsetString(subset)
    apply_renderer(layer, renderer_mode, zmin, zmax)  # incl. 3D "Volg 2D"
    _set_metadata(layer, tile["version"])
    layer.setCustomProperty(PROP_KEY, tile["url"])
    return layer


def _wkt2(crs):
    variant = getattr(getattr(Qgis, "CrsWktVariant", None), "Wkt2_2019", None)
    if variant is None:
        variant = QgsCoordinateReferenceSystem.WKT2_2019
    return crs.toWkt(variant)


def vpc_dir():
    path = os.path.join(QgsApplication.qgisSettingsDirPath(), "ahn_copc_vpc")
    os.makedirs(path, exist_ok=True)
    return path


def find_vpc_layer(label):
    for layer in QgsProject.instance().mapLayers().values():
        if layer.customProperty(VPC_LABEL) == label:
            return layer
    return None


def vpc_tiles_of(layer):
    try:
        return json.loads(layer.customProperty(VPC_TILES) or "[]")
    except ValueError:
        return []


def make_vpc_layer(
    tiles, label, renderer_mode, subset="", zmin=None, zmax=None
):
    """Write a .vpc referencing the remote COPC tiles and open it as one layer.

    label: language-independent key of the version choice ("AHN6", "newest").

    tiles: dicts with x, y, version, url and optionally hdr {count, bbox}.
    """
    rd = QgsCoordinateReferenceSystem("EPSG:28992")
    xform = QgsCoordinateTransform(
        rd, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
    )

    def to_wgs84(x, y):
        p = xform.transform(QgsPointXY(x, y))
        return p.x(), p.y()

    entries = []
    for t in tiles:
        hdr = t.get("hdr") or {}
        bbox = hdr.get("bbox") or [
            t["x"],
            t["y"],
            -10.0,
            t["x"] + ahn_tiles.CELL,
            t["y"] + ahn_tiles.CELL,
            200.0,
        ]
        # point format from the header; fallback for tiles from an older plugin
        # version: AHN6 is coloured (RGB), older versions are not
        pdrf = hdr.get("pdrf", 7 if t["version"] == "AHN6" else 6)
        entries.append(
            {
                "id": (
                    "%s_%s"
                    % (t["version"], ahn_tiles.tile_name(t["x"], t["y"]))
                ),
                "url": t["url"],
                "bbox": bbox,
                "count": hdr.get("count", 0),
                "pdrf": pdrf,
            }
        )

    path = os.path.join(
        vpc_dir(),
        "%s_%d.vpc" % (label.replace(" ", "_"), int(time.time() * 1000)),
    )
    vpc.write_vpc(
        path,
        vpc.build_vpc(
            entries, to_wgs84, _wkt2(QgsCoordinateReferenceSystem("EPSG:7415"))
        ),
    )

    shown = tr("AHN newest") if label == ahn_tiles.NEWEST else label
    name = tr("%s VPC (%d sheets)", shown, len(tiles))
    layer = QgsPointCloudLayer(path, name, "vpc")
    if not layer.isValid():
        return None
    if subset:
        layer.setSubsetString(subset)
    apply_renderer(layer, renderer_mode, zmin, zmax)
    versions = sorted({t["version"] for t in tiles})
    _set_metadata(layer, versions[-1] if versions else "")
    keep = [
        {k: t[k] for k in ("x", "y", "version", "url", "hdr") if k in t}
        for t in tiles
    ]
    layer.setCustomProperty(PROP_KEY, path)
    layer.setCustomProperty(VPC_LABEL, label)
    layer.setCustomProperty(VPC_TILES, json.dumps(keep))
    return layer


def replace_vpc_layer(old, new):
    """Put `new` where `old` was in the layer tree; remove `old` + its file."""
    project = QgsProject.instance()
    group = get_group()
    old_path = old.customProperty(PROP_KEY) if old is not None else None
    project.addMapLayer(new, False)
    index = 0
    if old is not None:
        node = group.findLayer(old.id())
        if node is not None:
            index = group.children().index(node)
        project.removeMapLayer(old.id())
        _delete_file(old_path)
    else:
        index = len(group.children())
    group.insertLayer(index, new)


def _delete_file(path):
    if (
        path
        and path.endswith(".vpc")
        and os.path.dirname(os.path.abspath(path))
        == os.path.abspath(vpc_dir())
    ):
        try:
            os.remove(path)
        except OSError as e:
            log("Could not delete %s: %s" % (path, e), "Info")


def add_layers(layers):
    group = get_group()
    project = QgsProject.instance()
    for layer in layers:
        project.addMapLayer(layer, False)
        group.addLayer(layer)


def remove_all():
    project = QgsProject.instance()
    ids, files = [], []
    for lid, lyr in project.mapLayers().items():
        if lyr.customProperty(PROP_KEY) or lyr.customProperty(SHEETS_PROP):
            ids.append(lid)
            if lyr.customProperty(VPC_LABEL):
                files.append(lyr.customProperty(PROP_KEY))
    project.removeMapLayers(ids)
    for f in files:
        _delete_file(f)
    group = get_group(create=False)
    if group is not None and not group.children():
        group.parent().removeChildNode(group)


def sheets_layer(available, missing, errors):
    """Memory layer with the checked 1 km sheets and their status."""
    vl = QgsVectorLayer(
        "Polygon?crs=EPSG:28992", tr("AHN sheets 1 km"), "memory"
    )
    vl.setCustomProperty(SHEETS_PROP, True)
    pr = vl.dataProvider()
    pr.addAttributes(
        [
            QgsField("sheet", T_STRING),
            QgsField("version", T_STRING),
            QgsField("status", T_STRING),
            QgsField("size_mb", T_DOUBLE),
            QgsField("url", T_STRING),
        ]
    )
    vl.updateFields()

    def feat(x, y, version, status, size, url):
        f = QgsFeature(vl.fields())
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
        return f

    feats = [
        feat(
            t["x"], t["y"], t["version"], tr("available"), t["size"], t["url"]
        )
        for t in available
    ]
    feats += [feat(x, y, "", tr("not available"), 0, "") for (x, y) in missing]
    feats += [feat(x, y, "", tr("network error"), 0, "") for (x, y) in errors]
    pr.addFeatures(feats)
    vl.updateExtents()

    symbol = QgsFillSymbol.createSimple(
        {
            "color": "0,0,0,0",
            "outline_color": "#ea5a0c",
            "outline_width": "0.5",
        }
    )
    vl.renderer().setSymbol(symbol)

    pal = QgsPalLayerSettings()
    pal.fieldName = "sheet"
    fmt = QgsTextFormat()
    fmt.setSize(8)
    fmt.setColor(QColor("#ea5a0c"))
    pal.setFormat(fmt)
    vl.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    vl.setLabelsEnabled(True)
    return vl


def replace_sheets_layer(vl):
    project = QgsProject.instance()
    old = [
        lid
        for lid, lyr in project.mapLayers().items()
        if lyr.customProperty(SHEETS_PROP)
    ]
    project.removeMapLayers(old)
    project.addMapLayer(vl, False)
    get_group().insertLayer(0, vl)
