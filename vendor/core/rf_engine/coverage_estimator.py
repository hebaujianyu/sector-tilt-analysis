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
coverage_estimator.py

RF Coverage Estimator

Engine ini menentukan coverage distance final
berdasarkan beam geometry dan terrain intersection.

Coverage bisa disebabkan oleh:
1. Beam menyentuh ground
2. Beam terhalang terrain
"""

class CoverageEstimator:
    """
    Menghitung coverage distance final.
    """

    def __init__(self, antenna_height):
        self.antenna_height = antenna_height

    # ======================================================
    # SINGLE BEAM ESTIMATION
    # ======================================================

    def estimate(
        self,
        beam_distance,
        intersection_result
    ):
        """
        Estimate coverage distance untuk satu beam.

        Parameters
        ----------
        beam_distance : float
            jarak beam menyentuh ground

        intersection_result : dict
            hasil dari IntersectionSolver

        Returns
        -------
        dict
        """

        if intersection_result["blocked"]:

            return {
                "coverage_distance": intersection_result["distance"],
                "coverage_type": "terrain_blocked"
            }

        if beam_distance is None:

            return {
                "coverage_distance": None,
                "coverage_type": "no_ground_intersection"
            }

        return {
            "coverage_distance": beam_distance,
            "coverage_type": "ground_hit"
        }

    # ======================================================
    # MULTI BEAM ESTIMATION
    # ======================================================

    def estimate_all(
        self,
        beam_geometry,
        intersection_results
    ):
        """
        Estimate coverage untuk semua beam.

        Parameters
        ----------
        beam_geometry : dict
        intersection_results : dict

        Returns
        -------
        dict
        """

        upper = self.estimate(
            beam_geometry["distance_upper"],
            intersection_results["upper_beam"]
        )

        main = self.estimate(
            beam_geometry["distance_main"],
            intersection_results["main_beam"]
        )

        lower = self.estimate(
            beam_geometry["distance_lower"],
            intersection_results["lower_beam"]
        )

        return {
            "upper_beam": upper,
            "main_beam": main,
            "lower_beam": lower
        }

    # ======================================================
    # FINAL COVERAGE DISTANCE - FIXED DENGAN SAFE ACCESS
    # ======================================================

    def final_coverage(self, coverage_results):
        """
        Menentukan coverage final sektor.
        PRIORITY: main beam intersection > main beam free space
        
        Parameters
        ----------
        coverage_results : dict
            Hasil dari estimate_all()
            
        Returns
        -------
        dict
            {'distance': float or None, 'type': str}
        """
        
        # =====================================================
        # VALIDASI INPUT
        # =====================================================
        if not isinstance(coverage_results, dict):
            print(f"❌ coverage_results is not a dict: {type(coverage_results)}")
            return {"distance": None, "type": "invalid_input"}
        
        if "main_beam" not in coverage_results:
            print(f"❌ coverage_results missing 'main_beam' key")
            return {"distance": None, "type": "missing_key"}
        
        main = coverage_results["main_beam"]
        
        # =====================================================
        # PRIORITY 1: Main beam intersection
        # =====================================================
        if isinstance(main, dict):
            cov_type = main.get("coverage_type")
            cov_dist = main.get("coverage_distance")
            
            if cov_type in ["terrain_blocked", "ground_hit"] and cov_dist is not None:
                print(f"  ✅ Using main beam: {cov_dist:.0f}m ({cov_type})")
                return {
                    "distance": cov_dist,
                    "type": cov_type
                }
        
        # =====================================================
        # PRIORITY 2: Main beam free space
        # =====================================================
        if isinstance(main, dict) and main.get("coverage_distance") is not None:
            cov_dist = main.get("coverage_distance")
            print(f"  ⚠️ No intersection, using free space: {cov_dist:.0f}m")
            return {
                "distance": cov_dist,
                "type": "ground_hit"
            }
        
        # =====================================================
        # PRIORITY 3: Fallback ke lower beam
        # =====================================================
        if "lower_beam" in coverage_results and isinstance(coverage_results["lower_beam"], dict):
            lower = coverage_results["lower_beam"]
            return {
                "distance": lower.get("coverage_distance"),
                "type": lower.get("coverage_type", "unknown")
            }
        
        # =====================================================
        # FINAL FALLBACK
        # =====================================================
        print(f"  ❌ No valid coverage found in results")
        return {
            "distance": None,
            "type": "no_coverage"
        }