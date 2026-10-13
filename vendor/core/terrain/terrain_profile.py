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
terrain_profile.py

Terrain profile processor untuk RF Vertical Analysis.

Input:
- distances[]
- elevations[]
- site_height

Output:
- terrain_angles[]
- relative_heights[]

Digunakan oleh intersection_solver untuk menghitung
beam-terrain intersection.
"""

import math


class TerrainProfile:
    """
    Menghitung profil terrain relatif terhadap site.
    """

    def __init__(
        self,
        distances,
        elevations,
        site_height
    ):

        if len(distances) != len(elevations):
            raise ValueError("distances and elevations length mismatch")

        self.distances = distances
        self.elevations = elevations
        self.site_height = site_height

    # ======================================================
    # MAIN PROFILE COMPUTATION
    # ======================================================

    def compute(self):
        """
        Compute terrain profile relative terhadap antenna height.
        """
        relative_heights = []
        terrain_angles = []

        # ABSOLUTE ANTENNA HEIGHT
        site_ground_elevation = self.elevations[0]
        antenna_absolute_height = site_ground_elevation + self.site_height

        print(f"\n📐 TERRAIN PROFILE:")
        print(f"  site_ground={site_ground_elevation:.0f}m, antenna_abs={antenna_absolute_height:.0f}m")

        for i, (d, elev) in enumerate(zip(self.distances, self.elevations)):

            if d == 0:
                relative_heights.append(0)
                terrain_angles.append(0)
                continue

            # tinggi terrain relatif terhadap antenna
            rel_h = elev - antenna_absolute_height
            angle_rad = math.atan2(rel_h, d)
            angle_deg = math.degrees(angle_rad)

            relative_heights.append(rel_h)
            terrain_angles.append(angle_deg)
            
            # Debug sample pertama dan terakhir
            if i < 3 or i > len(self.distances)-3:
                print(f"  d={d:.0f}m, elev={elev:.0f}m, rel_h={rel_h:.1f}m, angle={angle_deg:.2f}°")

        return {
            "distances": self.distances,
            "elevations": self.elevations,
            "relative_heights": relative_heights,
            "terrain_angles": terrain_angles
        }

    # ======================================================
    # MAX TERRAIN OBSTRUCTION
    # ======================================================

    def get_max_obstruction_angle(self):
        """
        Mengembalikan sudut terrain tertinggi terhadap site.

        Ini sering dipakai untuk quick LOS analysis.

        Returns
        -------
        float
        """

        max_angle = -999

        for d, elev in zip(self.distances, self.elevations):

            if d == 0:
                continue

            rel_h = elev - self.site_height

            angle = math.degrees(math.atan2(rel_h, d))

            if angle > max_angle:
                max_angle = angle

        return max_angle

    # ======================================================
    # TERRAIN HIGHEST POINT
    # ======================================================

    def get_highest_point(self):
        """
        Mengembalikan titik terrain tertinggi.

        Returns
        -------
        dict
        """

        max_h = -999999
        max_d = None

        for d, elev in zip(self.distances, self.elevations):

            rel_h = elev - self.site_height

            if rel_h > max_h:
                max_h = rel_h
                max_d = d

        return {
            "distance": max_d,
            "relative_height": max_h
        }