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
sector_geometry.py

Utility untuk membuat geometri sektor RF
berdasarkan azimuth dan coverage distance.
"""

import math

from qgis.core import (
    QgsPointXY,
    QgsGeometry
)


class SectorGeometry:
    """
    Membuat polygon sektor RF coverage.
    """

    # ======================================================
    # DESTINATION POINT
    # ======================================================

    @staticmethod
    def destination_point(origin, azimuth_deg, distance_m):
        """
        Menghitung titik tujuan dari origin.

        Parameters
        ----------
        origin : QgsPointXY
        azimuth_deg : float
        distance_m : float
        """

        R = 6378137.0

        lat1 = math.radians(origin.y())
        lon1 = math.radians(origin.x())

        az = math.radians(azimuth_deg)

        lat2 = lat1 + (distance_m / R) * math.cos(az)
        lon2 = lon1 + (distance_m / R) * math.sin(az) / math.cos(lat1)

        return QgsPointXY(
            math.degrees(lon2),
            math.degrees(lat2)
        )

    # ======================================================
    # CREATE SECTOR POLYGON
    # ======================================================

    @staticmethod
    def create_sector(
        center,
        azimuth,
        beamwidth,
        radius,
        segments=30
    ):
        """
        Membuat polygon sektor coverage.

        Parameters
        ----------
        center : QgsPointXY
        azimuth : float
        beamwidth : float
        radius : float
        segments : int
        """

        start_angle = azimuth - beamwidth / 2
        end_angle = azimuth + beamwidth / 2

        step = beamwidth / segments

        points = [center]

        angle = start_angle

        while angle <= end_angle:

            pt = SectorGeometry.destination_point(
                center,
                angle,
                radius
            )

            points.append(pt)

            angle += step

        points.append(center)

        return QgsGeometry.fromPolygonXY([points])

    # ======================================================
    # CREATE FOOTPRINT FROM BEAM SET
    # ======================================================

    @staticmethod
    def footprint_from_beams(
        center,
        azimuth,
        horizontal_beamwidth,
        lower_distance,
        upper_distance
    ):
        """
        Membuat coverage footprint polygon.

        Coverage area = area antara lower beam
        dan upper beam distance.
        """

        if lower_distance is None:
            lower_distance = 0

        if upper_distance is None:
            return None

        outer_sector = SectorGeometry.create_sector(
            center,
            azimuth,
            horizontal_beamwidth,
            upper_distance
        )

        inner_sector = SectorGeometry.create_sector(
            center,
            azimuth,
            horizontal_beamwidth,
            lower_distance
        )

        footprint = outer_sector.difference(inner_sector)

        return footprint