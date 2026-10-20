import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtGui import QAction  # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # Qt5

from .dock import AhnDock
from .i18n import tr


class AhnStreamerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        self.action = QAction(icon, "AHN Streamer", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip(tr("Stream AHN point clouds for the map extent"))
        self.action.toggled.connect(self._toggle)
        self.iface.addWebToolBarIcon(self.action)
        self.iface.addPluginToWebMenu("AHN Streamer", self.action)

    def _toggle(self, on):
        if self.dock is None:
            self.dock = AhnDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self.dock.visibilityChanged.connect(self.action.setChecked)
        self.dock.setVisible(on)

    def unload(self):
        if self.dock is not None:
            self.dock.shutdown()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.iface.removePluginWebMenu("AHN Streamer", self.action)
        self.iface.removeWebToolBarIcon(self.action)
