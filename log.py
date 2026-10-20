"""Write to the QGIS Message Log panel (tab "AHN Streamer")."""

from qgis.core import Qgis, QgsMessageLog

TAG = "AHN Streamer"


def log(message, level="Warning"):
    """Log a message; level is "Info", "Warning" or "Critical"."""
    holder = getattr(Qgis, "MessageLevel", None)
    if holder is not None and hasattr(holder, level):
        qgis_level = getattr(holder, level)
    else:
        qgis_level = getattr(Qgis, level)
    QgsMessageLog.logMessage(str(message), TAG, qgis_level)
