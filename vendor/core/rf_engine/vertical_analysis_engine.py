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
vertical_analysis_engine.py

Main RF Vertical Analysis Engine.

Engine ini menggabungkan seluruh core engine:

TerrainSampler
TerrainProfile
BeamGeometry
IntersectionSolver
CoverageEstimator
"""

from qgis.core import QgsPointXY

from ..terrain import TerrainSampler
from ..terrain import TerrainProfile

from .beam_geometry import BeamGeometry
from .intersection_solver import IntersectionSolver
from .coverage_estimator import CoverageEstimator
from ...ui.dialogs.defaults import RFDefaults  # Naik 3 level


class VerticalAnalysisEngine:
    """
    Main orchestrator untuk RF vertical analysis.
    """

    def __init__(self, dem_layer):
        self.dem_layer = dem_layer
        self.sampler = None  # Akan diinisialisasi saat run


    # ======================================================
    # MAIN ANALYSIS PIPELINE
    # ======================================================

    def run(
        self,
        site_point,
        azimuth,
        antenna_height,
        mech_tilt,
        elec_tilt,
        beamwidth,
        max_distance=RFDefaults.MAX_DISTANCE,
        step=RFDefaults.SAMPLING_STEP,
        dem_source="local",
        timeout=45  # <-- TAMBAHKAN PARAMETER INI
    ):
        """
        Run vertical RF analysis pipeline.
        
        Parameters
        ----------
        site_point : QgsPointXY
            Site location
        azimuth : float
            Azimuth angle in degrees
        antenna_height : float
            Antenna height above ground in meters
        mech_tilt : float
            Mechanical tilt in degrees
        elec_tilt : float
            Electrical tilt in degrees
        beamwidth : float
            Vertical beamwidth in degrees
        max_distance : float
            Maximum distance to sample in meters
        step : float
            Sampling step in meters
        dem_source : str
            "local" atau "online" untuk sumber data DEM
        """
        
        # =====================================================
        # VALIDASI INPUT (EXTRA SAFETY)
        # =====================================================
        if antenna_height <= 0:
            raise ValueError(f"Antenna height must be positive: {antenna_height}")
        
        if beamwidth <= 0:
            raise ValueError(f"Vertical beamwidth must be positive: {beamwidth}")
        
        if max_distance <= 0:
            raise ValueError(f"Max distance must be positive: {max_distance}")
        
        if step <= 0:
            raise ValueError(f"Sampling step must be positive: {step}")
        
        if step > max_distance:
            step = max_distance / 10  # Fallback ke 10% dari max distance
            print(f"⚠️ Step too large, adjusted to {step:.0f}m")
            
            
        # ======================================================
        # 1️⃣ TERRAIN SAMPLING
        # ======================================================

        # Buat sampler jika belum ada, atau gunakan yang sudah ada
        if self.sampler is None:
            self.sampler = TerrainSampler(self.dem_layer)

        try:
            terrain_sample = self.sampler.sample_profile(
                site_point,
                azimuth,
                max_distance,
                step,
                source=dem_source,
                timeout=timeout  # <-- GUNAKAN PARAMETER INI
            )
        except Exception as e:
            error_msg = str(e)
            print(f"❌ TERRAIN SAMPLING FAILED: {error_msg}")
            
            # Return error object instead of raising
            return {
                "error": True,
                "error_message": error_msg,
                "source": dem_source,
                "distances": [],
                "elevations": [],
                "main_beam": None,
                "upper_beam": None,
                "lower_beam": None,
                "impact_distance": None,
                "impact_point": None,
                "footprint_start_distance": None,
                "footprint_end_distance": None
            }

        distances = terrain_sample["distances"]
        elevations = terrain_sample["elevations"]

        # ======================================================
        # 2️⃣ TERRAIN PROFILE
        # ======================================================

        terrain_profile = TerrainProfile(
            distances,
            elevations,
            antenna_height
        )

        profile = terrain_profile.compute()

        terrain_angles = profile["terrain_angles"]

        # ======================================================
        # 3️⃣ BEAM GEOMETRY
        # ======================================================

        beam_engine = BeamGeometry(
            mech_tilt,
            elec_tilt,
            beamwidth
        )

        beam_geom = beam_engine.compute_with_distance(
            antenna_height
        )

        main_beam = beam_geom["main_beam"]
        upper_beam = beam_geom["upper_beam"]
        lower_beam = beam_geom["lower_beam"]

        # ======================================================
        # 4️⃣ TERRAIN INTERSECTION
        # ======================================================

        # Buat solver dengan elevations dan antenna_height
        solver = IntersectionSolver(
            distances=distances,
            elevations=elevations,
            antenna_height=antenna_height
        )
        
        intersection = solver.solve_beam_set(upper_beam, main_beam, lower_beam)
        
        # ======================================================
        # DEBUG: LIHAT ISI INTERSECTION
        # ======================================================
        print(f"\n🔍 INTERSECTION DETAILS:")
        print(f"  • Main beam: distance={intersection['main_beam'].get('distance')}, "
              f"terrain_height={intersection['main_beam'].get('terrain_height')}, "
              f"beam_height={intersection['main_beam'].get('beam_height')}, "
              f"blocked={intersection['main_beam'].get('blocked')}")
        print(f"  • Upper beam: distance={intersection['upper_beam'].get('distance')}, "
              f"terrain_height={intersection['upper_beam'].get('terrain_height')}")
        print(f"  • Lower beam: distance={intersection['lower_beam'].get('distance')}, "
              f"terrain_height={intersection['lower_beam'].get('terrain_height')}")
        
        # ======================================================
        # AMBIL BEAM HEIGHT DARI INTERSECTION SOLVER
        # ======================================================
        
        # Ambil beam height untuk setiap intersection point
        main_beam_height = None
        upper_beam_height = None
        lower_beam_height = None
        
        # Debug: lihat struktur intersection
        print(f"\n🔍 INTERSECTION STRUCTURE:")
        print(f"  • main_beam keys: {intersection['main_beam'].keys()}")
        
        # Main beam intersection height - gunakan terrain_height dari intersection
        if intersection["main_beam"].get("blocked", False):
            main_beam_height = intersection["main_beam"].get("terrain_height")
            if main_beam_height is not None:
                print(f"  📐 Main beam height at intersection: {main_beam_height:.1f}m (from terrain_height)")
            else:
                print(f"  ⚠️ Main beam terrain_height is None")
        
        # Upper beam intersection height
        if intersection["upper_beam"].get("blocked", False):
            upper_beam_height = intersection["upper_beam"].get("terrain_height")
            if upper_beam_height is not None:
                print(f"  📐 Upper beam height at intersection: {upper_beam_height:.1f}m")
        
        # Lower beam intersection height
        if intersection["lower_beam"].get("blocked", False):
            lower_beam_height = intersection["lower_beam"].get("terrain_height")
            if lower_beam_height is not None:
                print(f"  📐 Lower beam height at intersection: {lower_beam_height:.1f}m")
                
        
        print(f"\n🔍 INTERSECTION RESULTS:")
        print(f"  - Upper beam: {intersection['upper_beam']}")
        print(f"  - Main beam: {intersection['main_beam']}")
        print(f"  - Lower beam: {intersection['lower_beam']}")
        
        # ======================================================
        # AMBIL INTERSECTION POINTS
        # ======================================================
        
        main_intersection = intersection["main_beam"].get("distance")
        upper_intersection = intersection["upper_beam"].get("distance")
        lower_intersection = intersection["lower_beam"].get("distance")
        
        # Debug print intersection
        print(f"\n📊 INTERSECTION POINTS:")
        print(f"  - Main beam intersection: {main_intersection}")
        print(f"  - Upper beam intersection: {upper_intersection}")
        print(f"  - Lower beam intersection: {lower_intersection}")
        
        
        # ======================================================
        # SHADOW REGIONS - area di mana terrain di atas beam
        # ======================================================
        
        shadow_regions = []
        shadow_start = None
        
        # Gunakan terrain_angles dan main_beam untuk deteksi shadow
        for i, (d, t_angle) in enumerate(zip(distances, terrain_angles)):
            if t_angle > main_beam:  # Terrain blocking
                if shadow_start is None:
                    shadow_start = d
            else:
                if shadow_start is not None:
                    shadow_regions.append([shadow_start, d])
                    shadow_start = None
        
        # Handle if shadow continues to end
        if shadow_start is not None:
            shadow_regions.append([shadow_start, distances[-1]])
        
        print(f"📊 SHADOW REGIONS: {len(shadow_regions)} areas detected")
        
        
        # ======================================================
        # 5️⃣ COVERAGE ESTIMATION
        # ======================================================

        estimator = CoverageEstimator(
            antenna_height
        )

        coverage = estimator.estimate_all(
            beam_geom,
            intersection
        )

        final_cov = estimator.final_coverage(
            coverage
        )

        impact_distance = final_cov["distance"]
        
        # ======================================================
        # DEBUG LOGGING
        # ======================================================
        
        print(f"\n📊 ENGINE CALCULATION:")
        main_dist = beam_geom.get('distance_main')
        lower_dist = beam_geom.get('distance_lower')
        
        if main_dist is not None:
            print(f"  - Main beam free space: {main_dist:.0f}m")
        else:
            print(f"  - Main beam free space: None")
            
        if lower_dist is not None:
            print(f"  - Lower beam free space: {lower_dist:.0f}m")
        else:
            print(f"  - Lower beam free space: None")
        
        # HAPUS 3 BARIS INI - JANGAN TIMPA main_intersection
        # main_intersection = intersection.get('main_intersection_distance')
        # if main_intersection is not None:
        #     print(f"  - Main beam intersection: {main_intersection:.0f}")
        # else:
        #     print(f"  - Main beam intersection: None")
        
        # GANTI DENGAN INI (untuk debug saja, tanpa menimpa variabel)
        main_intersection_value = intersection["main_beam"].get("distance")
        if main_intersection_value is not None:
            print(f"  - Main beam intersection: {main_intersection_value:.0f}")
        else:
            print(f"  - Main beam intersection: None")
            
        if impact_distance is not None:
            print(f"  - Final impact distance: {impact_distance:.0f}")
        else:
            print(f"  - Final impact distance: None")
        print(f"  - Impact type: {final_cov['type']}")

        # ======================================================
        # FOOTPRINT DISTANCE COMPUTATION - FIXED (MENGGUNAKAN INTERSECTION)
        # ======================================================

        footprint_start = None
        footprint_end = None

        try:
            # ------------------------------------------
            # PRIORITY 1 : Gunakan intersection points dari upper/lower beam
            # ------------------------------------------
            
            # Pastikan variabel upper_intersection dan lower_intersession sudah didefinisikan
            # dari hasil intersection solver
            if 'lower_intersection' in locals() and lower_intersection is not None:
                footprint_start = lower_intersection
                print(f"  - Using lower beam intersection for start: {lower_intersection:.0f}m")
            elif beam_geom["distance_lower"]:
                footprint_start = beam_geom["distance_lower"] * 0.8
                print(f"  - Fallback start (lower beam): {footprint_start:.0f}m")
            
            if 'upper_intersection' in locals() and upper_intersection is not None:
                footprint_end = upper_intersection
                print(f"  - Using upper beam intersection for end: {upper_intersection:.0f}m")
            elif beam_geom["distance_upper"]:
                footprint_end = beam_geom["distance_upper"] * 1.2
                print(f"  - Fallback end (upper beam): {footprint_end:.0f}m")
            
            # ------------------------------------------
            # PRIORITY 2 : Fallback ke terrain impact jika intersection tidak ada
            # ------------------------------------------
            
            if footprint_start is None and impact_distance is not None and impact_distance > 0:
                footprint_start = impact_distance * 0.8
                print(f"  - Fallback start (terrain impact): {footprint_start:.0f}m")
            
            if footprint_end is None and impact_distance is not None and impact_distance > 0:
                footprint_end = impact_distance * 1.2
                print(f"  - Fallback end (terrain impact): {footprint_end:.0f}m")
            
            # ------------------------------------------
            # PRIORITY 3 : Fallback ke beam geometry
            # ------------------------------------------
            
            if footprint_start is None and beam_geom["distance_main"]:
                footprint_start = beam_geom["distance_main"] * 0.8
                print(f"  - Fallback start (main beam): {footprint_start:.0f}m")
            
            if footprint_end is None and beam_geom["distance_main"]:
                footprint_end = beam_geom["distance_main"] * 1.2
                print(f"  - Fallback end (main beam): {footprint_end:.0f}m")
            
            # ------------------------------------------
            # PRIORITY 4 : default RF fallback
            # ------------------------------------------
            
            if footprint_start is None:
                footprint_start = max_distance * 0.3
                print(f"  - Default start: {footprint_start:.0f}m")
            
            if footprint_end is None:
                footprint_end = max_distance * 0.6
                print(f"  - Default end: {footprint_end:.0f}m")
            
            # ------------------------------------------
            # PASTIKAN start < end
            # ------------------------------------------
            
            if footprint_start is not None and footprint_end is not None:
                if footprint_start > footprint_end:
                    footprint_start, footprint_end = footprint_end, footprint_start
                    print(f"  - Swapped to ensure start < end")
                    
        except Exception as e:
            print(f"⚠️ Footprint calculation error: {e}")
            pass


        # ======================================================
        # 6️⃣ IMPACT POINT
        # ======================================================

        impact_point = None

        if impact_distance is not None:
            impact_point = self._project_point(
                site_point,
                azimuth,
                impact_distance
            )

        # ======================================================
        # 7️⃣ UPPER & LOWER INTERSECTION POINTS (PATCH)
        # ======================================================

        upper_intersection_point = None
        lower_intersection_point = None

        if upper_intersection is not None:
            upper_intersection_point = self._project_point(
                site_point,
                azimuth,
                upper_intersection
            )
            print(f"  📍 Upper intersection point: ({upper_intersection_point.x():.6f}, {upper_intersection_point.y():.6f})")

        if lower_intersection is not None:
            lower_intersection_point = self._project_point(
                site_point,
                azimuth,
                lower_intersection
            )
            print(f"  📍 Lower intersection point: ({lower_intersection_point.x():.6f}, {lower_intersection_point.y():.6f})")

        # ======================================================
        # 8️⃣ BEAM END POINT (Main beam end - PATCH)
        # ======================================================

        beam_end_point = None
        main_beam_distance = beam_geom.get("distance_main")

        if main_beam_distance is not None and main_beam_distance > 0:
            beam_end_point = self._project_point(
                site_point,
                azimuth,
                main_beam_distance
            )
            print(f"  📍 Beam end point (main beam): ({beam_end_point.x():.6f}, {beam_end_point.y():.6f}) at {main_beam_distance:.0f}m")

        # ======================================================
        # FINAL RESULT
        # ======================================================

        return {

            # terrain
            "distances": distances,
            "elevations": elevations,

            # beam angles
            "main_beam": main_beam,
            "upper_beam": upper_beam,
            "lower_beam": lower_beam,

            # beam ground distance
            "distance_main": beam_geom["distance_main"],
            "distance_upper": beam_geom["distance_upper"],
            "distance_lower": beam_geom["distance_lower"],

            # terrain intersection
            "intersection": intersection,
            
            # intersection points (JARAK)
            "main_intersection_distance": main_intersection,
            "upper_intersection_distance": upper_intersection,
            "lower_intersection_distance": lower_intersection,
            
            # INTERSECTION POINTS (KOORDINAT) - PATCH
            "upper_intersection_point": upper_intersection_point,
            "lower_intersection_point": lower_intersection_point,
            "beam_end_point": beam_end_point,
            
            "shadow_regions": shadow_regions,

            # BEAM HEIGHTS AT INTERSECTION
            "main_beam_height": main_beam_height,
            "upper_beam_height": upper_beam_height,
            "lower_beam_height": lower_beam_height,

            # coverage
            "coverage": coverage,
            "final_coverage": final_cov,

            # impact
            "impact_distance": impact_distance,
            "impact_point": impact_point,

            # footprint distance
            "footprint_start_distance": footprint_start,
            "footprint_end_distance": footprint_end,

            # raw engine output (debug)
            "terrain_profile": profile,
            "beam_geometry": beam_geom

        }
        
        
    # ======================================================
    # POINT PROJECTION
    # ======================================================

    def _project_point(
        self,
        center,
        azimuth_deg,
        distance_m
    ):
        """
        Project geographic point from site.
        """

        import math

        EARTH_RADIUS = 6378137.0

        lat1 = math.radians(center.y())
        lon1 = math.radians(center.x())

        az = math.radians(azimuth_deg)

        d_div_r = distance_m / EARTH_RADIUS

        lat2 = lat1 + d_div_r * math.cos(az)

        lon2 = lon1 + (
            d_div_r * math.sin(az) / math.cos(lat1)
        )

        return QgsPointXY(
            math.degrees(lon2),
            math.degrees(lat2)
        )