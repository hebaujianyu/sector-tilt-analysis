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
beam_geometry.py

RF Beam Geometry Engine
Digunakan untuk menghitung sudut vertical beam antena.

Output:
- main beam
- upper beam edge
- lower beam edge

Sudut menggunakan konvensi:

0°  = horizontal
+°  = beam mengarah ke bawah
-°  = beam mengarah ke atas
"""

import math


class BeamGeometry:
    """
    Menghitung geometri vertical beam antena.
    """

    def __init__(
        self,
        mechanical_tilt: float,
        electrical_tilt: float,
        vertical_beamwidth: float
    ):

        self.mech_tilt = mechanical_tilt
        self.elec_tilt = electrical_tilt
        self.beamwidth = vertical_beamwidth

    # ======================================================
    # MAIN CALCULATION
    # ======================================================
    
    
    def compute(self):
        """
        Compute beam geometry.

        Visual offset ditambahkan pada upper beam agar garis tidak horizontal.
        Di real world, sinyal masih ada di luar -3dB beamwidth (half power),
        sehingga upper beam seharusnya masih sedikit menunduk.

        Returns
        -------
        dict
        """

        total_tilt = self.mech_tilt + self.elec_tilt

        half_bw = self.beamwidth / 2.0

        # =====================================================
        # VISUAL OFFSET: Agar upper beam tidak horizontal
        # Offset 0.2° membuat visualisasi lebih realistis
        # Nilai ini TIDAK mempengaruhi perhitungan impact distance
        # karena impact distance tetap menggunakan main beam
        # =====================================================
        VISUAL_OFFSET = 0.2  # derajat

        main_beam = total_tilt
        upper_beam = total_tilt - half_bw + VISUAL_OFFSET  # Tambah offset
        lower_beam = total_tilt + half_bw

        return {
            "mechanical_tilt": self.mech_tilt,
            "electrical_tilt": self.elec_tilt,
            "total_tilt": total_tilt,
            "beamwidth": self.beamwidth,
            "main_beam": main_beam,
            "upper_beam": upper_beam,
            "lower_beam": lower_beam
        }


    # ======================================================
    # GROUND INTERSECTION
    # ======================================================

    @staticmethod
    def ground_distance(
        antenna_height,
        beam_angle_deg
    ):
        """
        Menghitung jarak beam menyentuh ground.

        Parameters
        ----------
        antenna_height : float
        beam_angle_deg : float

        Returns
        -------
        float
        """

        # beam horizontal atau mengarah ke atas
        # tidak akan pernah menyentuh tanah
        if beam_angle_deg <= 0.01:
            return None

        angle_rad = math.radians(beam_angle_deg)

        try:
            distance = antenna_height / math.tan(angle_rad)
        except ZeroDivisionError:
            return None

        return distance

    # ======================================================
    # FULL GEOMETRY WITH DISTANCE
    # ======================================================

    def compute_with_distance(self, antenna_height):
        """
        Compute beam geometry + touchdown distance.

        Returns
        -------
        dict
        """

        geom = self.compute()

        upper_d = self.ground_distance(
            antenna_height,
            geom["upper_beam"]
        )

        main_d = self.ground_distance(
            antenna_height,
            geom["main_beam"]
        )

        lower_d = self.ground_distance(
            antenna_height,
            geom["lower_beam"]
        )

        geom.update({
            "distance_upper": upper_d,
            "distance_main": main_d,
            "distance_lower": lower_d
        })

        return geom