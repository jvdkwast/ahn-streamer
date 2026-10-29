# AHN Streamer

QGIS plugin that streams the point clouds of the **Actueel Hoogtebestand Nederland
(AHN)**, the Dutch national elevation dataset, for the current map extent. The tiles
are Cloud Optimized Point Clouds (COPC) on the official AHN storage, and QGIS fetches only
the level of detail it needs through HTTP range requests. Nothing is downloaded or
converted.

![icon](icon.svg)

## Features

- AHN2, AHN3, AHN4, AHN5, AHN6, or **newest available** (AHN6 per 1 km sheet,
  falling back to AHN5)
- Class filter presets: ground, ground + water, buildings, civil structures, ...
- Styling: AHN classification colours, height above NAP, intensity, number of
  returns, or the QGIS default (RGB for AHN6, which is coloured from aerial imagery)
- 3D view follows the 2D symbology
- One layer per 1 km sheet, or all sheets **merged into one virtual point cloud (VPC)**
  that grows as you load more areas
- Optional sheet layer showing which sheets are available
- Availability and header cache, so revisiting an area is instant

## Usage

1. Open the panel from the toolbar or *Web → AHN Streamer*.
2. Zoom to an area in the Netherlands (by default at most 16 sheets of 1×1 km).
3. Choose a version, class filter and style, and click **Load point cloud for map extent**.

The interface is available in **English and Dutch**. It follows the QGIS language
setting (*Settings → Options → General → User interface translation*): Dutch for
`nl`, English for any other language. Translations live in `i18n.py`; adding a
language means adding a dictionary there.

## Processing Toolbox

AHN Streamer also adds its own provider to the Processing Toolbox (*AHN
Streamer*), so you can use it in graphical models, batch processing and
scripts:

| Algorithm | ID | Output |
|---|---|---|
| Create AHN virtual point cloud (VPC) for extent | `ahnstreamer:createvpc` | A `.vpc` that refers to the remote COPC sheets |
| AHN sheets for extent | `ahnstreamer:sheets` | Polygons of the 1×1 km sheets with status, version, size and COPC URL |

Both take an extent (e.g. from a layer of your study area), a version (`0` =
newest available, `1` = AHN6, `2` = AHN5, …, `5` = AHN2) and a maximum number of
sheets. The VPC can be chained into other point cloud algorithms, for example
to clip it to your study area or to create a DTM:

```python
import processing

vpc = processing.run("ahnstreamer:createvpc", {
    "EXTENT": "155000,157000,463000,465000 [EPSG:28992]",
    "VERSION": 0,
    "MAX_SHEETS": 100,
    "OUTPUT": "TEMPORARY_OUTPUT",
})["OUTPUT"]

processing.run("pdal:exportrastertin", {
    "INPUT": vpc,
    "RESOLUTION": 0.5,
    "FILTER_EXPRESSION": "Classification = 2",
    "OUTPUT": "/path/to/dtm.tif",
})
```

## Data source

The plugin uses the URL scheme of the official AHN sheet index
([bladwijzer](https://basisdata.nl/hwh-ahn/AUX/bladwijzer/index.html)):

| Version | URL pattern | Sheet name |
|---|---|---|
| AHN2–AHN5 | `…/hwh-ahn/AHN{n}_KM/01_LAZ/AHN{n}_C_{x}_{y}.COPC.LAZ` | zero padded, e.g. `098000_477000` |
| AHN6 | `…/hwh-ahn/AHN6/01_LAZ/AHN6_{year}_C_{x}_{y}.COPC.LAZ` | not padded; year 2025/2026/2027 |

`{x}_{y}` is the lower-left corner of the 1 km cell in RD New (EPSG:28992).

**Attribution:** source AHN (www.ahn.nl). AHN1–4 are CC0 1.0; AHN5–6 are CC BY 4.0, so
derived products must credit AHN. The plugin writes this into the layer metadata.

## Requirements

- QGIS 3.34 or newer (QGIS 4 supported). No external Python packages.
- Coverage: the European Netherlands only.

## Known limitations

- A VPC with remote files has no overview point cloud, so QGIS shows sheet outlines
  when zoomed out and points when zoomed in.
- QGIS calculates no statistics for a VPC. The plugin's own styles therefore use
  fixed value ranges, which you can set in the panel.

## Development

Unit tests for the tile, URL, header and availability logic run without QGIS:

```
python3 -m unittest discover -s tests
```

## License

GNU General Public License v2 or later, see [LICENSE](LICENSE).
