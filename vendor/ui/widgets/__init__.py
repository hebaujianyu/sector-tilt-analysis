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
TiltMaster plugin
UI Widgets Package

Widget yang digunakan oleh dialog dan modul UI plugin.

Saat ini tersedia:
- TerrainProfileWidget : menampilkan TiltMaster terrain profile
"""

from .terrain_profile_widget import TerrainProfileWidget

__all__ = [
    "TerrainProfileWidget"
]