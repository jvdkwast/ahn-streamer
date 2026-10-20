"""Minimal translation layer (English source text, Dutch translations).

The language follows the QGIS user interface locale: Dutch for "nl*",
English otherwise. Plain Python instead of Qt .ts/.qm files keeps the plugin
free of compiled files and needs no Qt Linguist tooling.
"""

_LANG = None

NL = {
    # panel
    "Stream AHN point clouds for the map extent": "Stream AHN-puntenwolken voor het kaartbeeld",
    "Version": "Versie",
    "Points": "Punten",
    "Style": "Weergave",
    "Range": "Bereik",
    "Height range": "Bereik hoogte",
    "Intensity range": "Bereik intensiteit",
    "to": "tot",
    "Max. sheets": "Max. kaartbladen",
    "Maximum number of 1x1 km sheets to load at once.":
        "Maximaal aantal kaartbladen van 1x1 km per keer laden.",
    "'Newest available' loads AHN6 per 1 km sheet and falls back to AHN5.":
        "'Nieuwste beschikbaar' laadt per km-blad AHN6 en valt terug op AHN5.",
    "Merge into one virtual point cloud (VPC)": "Samenvoegen tot één virtuele puntenwolk (VPC)",
    "All sheets in one layer (.vpc referring to the remote COPC files). New sheets are added "
    "to the same VPC. Zoomed out, QGIS shows the sheet outlines; zoomed in, the points.":
        "Alle bladen in één laag (.vpc met verwijzingen naar de remote COPC-bestanden). Nieuwe "
        "bladen worden aan dezelfde VPC toegevoegd. Uitgezoomd toont QGIS de bladgrenzen; "
        "ingezoomd de punten.",
    "Show sheets with status": "Toon kaartbladen met status",
    "Load point cloud for map extent": "Laad puntenwolk voor kaartbeeld",
    "Apply filter and style to loaded layers": "Filter en weergave toepassen op geladen lagen",
    "Remove AHN layers": "Verwijder AHN-lagen",
    "Cancel": "Annuleren",
    'Source: <a href="https://www.ahn.nl/dataroom">AHN</a>. AHN2-4: CC0, AHN5-6: CC BY 4.0 '
    "(attribution required). Data is streamed as COPC; nothing is downloaded.":
        'Bron: <a href="https://www.ahn.nl/dataroom">AHN</a>. AHN2-4: CC0, AHN5-6: CC BY 4.0 '
        "(bronvermelding verplicht). Data wordt gestreamd als COPC; er wordt niets gedownload.",
    # versions, filters, styles
    "Newest available": "Nieuwste beschikbaar",
    "AHN newest": "AHN nieuwste",
    "All points": "Alle punten",
    "Ground only (2)": "Alleen maaiveld (2)",
    "Ground + water (2, 9)": "Maaiveld + water (2, 9)",
    "Buildings (6)": "Gebouwen (6)",
    "Civil structures (26)": "Kunstwerken (26)",
    "Without vegetation/other (no 1)": "Zonder vegetatie/overig (geen 1)",
    "Classification (AHN colours)": "Classificatie (AHN-kleuren)",
    "Height above NAP": "Hoogte t.o.v. NAP",
    "Intensity": "Intensiteit",
    "Number of returns (vegetation/edges)": "Aantal returns (vegetatie/randen)",
    "QGIS default (RGB if present)": "QGIS-standaard (RGB indien aanwezig)",
    # classes and legend
    "Never classified": "Nooit geclassificeerd",
    "Other (incl. vegetation)": "Overig (o.a. vegetatie)",
    "Ground": "Maaiveld",
    "Building": "Gebouw",
    "Water": "Water",
    "High voltage": "Hoogspanning",
    "Civil structure": "Kunstwerk",
    "1 return": "1 return",
    "%d returns": "%d returns",
    "5 or more returns": "5 of meer returns",
    # layers
    "AHN sheets 1 km": "AHN kaartbladen 1 km",
    "%s VPC (%d sheets)": "%s VPC (%d bladen)",
    "available": "beschikbaar",
    "not available": "niet beschikbaar",
    "network error": "netwerkfout",
    "Point cloud of the Actueel Hoogtebestand Nederland (%s, %s), streamed as "
    "Cloud Optimized Point Cloud (COPC).":
        "Puntenwolk van het Actueel Hoogtebestand Nederland (%s, %s), gestreamd als "
        "Cloud Optimized Point Cloud (COPC).",
    "Source: AHN (www.ahn.nl)": "Bron: AHN (www.ahn.nl)",
    # messages
    "The map extent covers about %d sheets of 1 km; the maximum is %d. "
    "Zoom in or raise the maximum.":
        "Het kaartbeeld beslaat ca. %d kaartbladen van 1 km; het maximum is %d. "
        "Zoom verder in of verhoog het maximum.",
    "The map extent is outside the Netherlands.": "Het kaartbeeld ligt buiten Nederland.",
    "Checking availability of %d sheets...": "Beschikbaarheid van %d kaartbladen controleren...",
    "Error: %s": "Fout: %s",
    "Error while checking: %s": "Fout bij controleren: %s",
    "Cancelled.": "Geannuleerd.",
    "%d sheets loaded": "%d bladen geladen",
    "%d already present": "%d al aanwezig",
    "%d not available in %s": "%d niet beschikbaar in %s",
    "%d network errors": "%d netwerkfouten",
    "%d could not be opened": "%d konden niet geopend worden",
    ". (%.1f GB in total on the server; only the visible part is streamed.)":
        ". (Totaal %.1f GB op de server, alleen het zichtbare deel wordt gestreamd.)",
    "Filter and style applied to %d layers.": "Filter en weergave toegepast op %d lagen.",
    "AHN layers removed.": "AHN-lagen verwijderd.",
    # background task
    "AHN Streamer: checking availability": "AHN Streamer: beschikbaarheid controleren",
    "AHN Streamer: reading headers for VPC": "AHN Streamer: headers lezen voor VPC",
}


def language():
    """'nl' or 'en', from the QGIS user interface locale (cached)."""
    global _LANG
    if _LANG is None:
        locale = ""
        try:
            from qgis.core import QgsApplication
            locale = QgsApplication.locale() or ""
        except Exception:
            pass
        if not locale:
            try:
                from qgis.core import QgsSettings
                locale = QgsSettings().value("locale/userLocale", "") or ""
            except Exception:
                pass
        _LANG = "nl" if str(locale).lower().startswith("nl") else "en"
    return _LANG


def set_language(lang):
    """Force a language ('nl'/'en'); used by tests."""
    global _LANG
    _LANG = lang


def tr(text, *args):
    """Translate `text` and apply %-formatting with `args`."""
    if language() == "nl":
        text = NL.get(text, text)
    return text % args if args else text
