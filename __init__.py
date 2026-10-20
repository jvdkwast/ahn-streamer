# AHN Streamer - stream AHN point clouds (COPC) into QGIS
# Copyright (C) 2026 Hans van der Kwast
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version. See the LICENSE file.


def classFactory(iface):
    from .plugin import AhnStreamerPlugin
    return AhnStreamerPlugin(iface)
