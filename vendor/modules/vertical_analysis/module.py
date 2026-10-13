# -*- coding: utf-8 -*-
"""
TiltMaster - RF Vertical Analysis for QGIS

Copyright (C) 2026 Achmad Amrulloh

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

"""
module.py

Vertical Analysis Module

Menghubungkan UI dialog dengan controller RF engine.
"""

from qgis.utils import iface

from .controller import VerticalAnalysisController

from ...ui.dialogs.vertical_analysis_dialog import VerticalAnalysisDialog


class VerticalAnalysisModule:
    """
    RF Vertical Analysis Module
    """

    def __init__(self, dem_layer):

        self.dem_layer = dem_layer

        self.controller = VerticalAnalysisController(
            dem_layer
        )

        self.dialog = None

    # ======================================================
    # OPEN MODULE UI
    # ======================================================

    def run(self):
        """
        Membuka Vertical Analysis Dialog.
        """

        dialog = VerticalAnalysisDialog(
            parent=iface.mainWindow()
        )

        # attach controller setelah dialog dibuat
        dialog.controller = self.controller

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()