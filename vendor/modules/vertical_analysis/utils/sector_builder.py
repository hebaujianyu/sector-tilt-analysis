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
sector_builder.py

Utility untuk membangun polygon sector berbentuk ARC
digunakan oleh Vertical Analysis Map Engine.
"""

import math
from qgis.core import QgsPointXY


def build_sector_polygon_planar(cx, cy, azimuth, beamwidth, radius, segments=36):
    """
    Build sector polygon berbentuk arc.

    Parameters
    ----------
    cx : float
        koordinat X center (UTM meter)

    cy : float
        koordinat Y center (UTM meter)

    azimuth : float
        arah sektor (derajat)

    beamwidth : float
        lebar sektor (derajat)

    radius : float
        jarak sektor (meter)

    segments : int
        jumlah titik arc

    Returns
    -------
    list[QgsPointXY]
        list titik polygon sector
    """

    points = []

    half_bw = beamwidth / 2.0

    start_angle = azimuth - half_bw
    end_angle = azimuth + half_bw

    start_rad = math.radians(start_angle)
    end_rad = math.radians(end_angle)

    step = (end_rad - start_rad) / segments

    # center point
    points.append(QgsPointXY(cx, cy))

    angle = start_rad

    for i in range(segments + 1):

        x = cx + radius * math.sin(angle)
        y = cy + radius * math.cos(angle)

        points.append(QgsPointXY(x, y))

        angle += step

    # close polygon
    points.append(QgsPointXY(cx, cy))

    return points